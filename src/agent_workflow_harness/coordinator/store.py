# SPDX-License-Identifier: Apache-2.0
"""PostgreSQL authority. All project mutations serialize on its project row.

The lock is intentionally coarse for M1: no in-process mutex can coordinate
different API processes. Never perform model, network or Git work inside it.
"""
from contextlib import contextmanager
from datetime import timedelta
import hashlib
from importlib.resources import files
import json
import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .models import resource_contains, resource_overlaps


class Rejected(Exception):
    def __init__(self, code: str, status: int = 409):
        self.code, self.status = code, status
        super().__init__(code)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode()).hexdigest()


def wire(value):
    """Persist precisely the response clients receive, including timestamps."""
    return json.loads(json.dumps(value, default=lambda item: item.isoformat()))


def authorize(principal, project_id, roles=None):
    if project_id not in principal.projects or (roles and principal.role not in roles):
        raise Rejected("forbidden", 403)


class Store:
    def __init__(self, dsn):
        self.dsn = dsn

    @contextmanager
    def connection(self):
        with psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=5) as conn:
            conn.execute("SET LOCAL lock_timeout = '3s'")
            conn.execute("SET LOCAL statement_timeout = '5s'")
            # Explicitly use READ COMMITTED; a snapshot before waiting for the
            # project lock would miss a competing process's committed grants.
            conn.execute("SET TRANSACTION ISOLATION LEVEL READ COMMITTED")
            yield conn

    def _migrations(self):
        return [(n, files(__package__).joinpath("migrations", f"{n:03d}.sql").read_text()) for n in (1, 2)]

    def migrate(self):
        with self.connection() as c:
            c.execute("SELECT pg_advisory_xact_lock(74201901)")
            c.execute("CREATE SCHEMA IF NOT EXISTS awh_m1")
            c.execute("CREATE TABLE IF NOT EXISTS awh_m1.schema_version "
                      "(version integer PRIMARY KEY, checksum text NOT NULL)")
            rows = c.execute("SELECT * FROM awh_m1.schema_version ORDER BY version").fetchall()
            migrations = self._migrations()
            expected = [{"version": n, "checksum": hashlib.sha256(source.encode()).hexdigest()}
                        for n, source in migrations]
            if rows != expected[:len(rows)]:
                raise Rejected("migration_version_or_checksum_mismatch")
            for (n, source), row in zip(migrations[len(rows):], expected[len(rows):]):
                c.execute(source)
                c.execute("INSERT INTO awh_m1.schema_version VALUES (%s,%s)", (n, row["checksum"]))

    def verify_schema(self):
        expected = [{"version": n, "checksum": hashlib.sha256(source.encode()).hexdigest()}
                    for n, source in self._migrations()]
        with self.connection() as c:
            if c.execute("SELECT * FROM awh_m1.schema_version ORDER BY version").fetchall() != expected:
                raise Rejected("migration_version_or_checksum_mismatch")

    def _event(self, c, pid, actor, kind, payload):
        c.execute("INSERT INTO awh_m1.outbox(project_id,actor,kind,payload) "
                  "VALUES (%s,%s,%s,%s)", (pid, actor, kind, Jsonb(wire(payload))))

    def create_project(self, principal, project):
        pid, doc = project.project_id, project.model_dump()
        authorize(principal, pid, {"controller"})
        with self.connection() as c:
            inserted = c.execute("INSERT INTO awh_m1.projects(project_id,document) "
                                 "VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING project_id",
                                 (pid, Jsonb(doc))).fetchone()
            row = self._project(c, pid)
            if row["document"] != doc:
                raise Rejected("project_already_exists_with_different_configuration")
            if inserted:
                self._event(c, pid, principal.subject, "project.created", {"project_id": pid})
            return wire(row)

    def _project(self, c, pid):
        row = c.execute("SELECT * FROM awh_m1.projects WHERE project_id=%s FOR UPDATE",
                        (pid,)).fetchone()
        if row is None:
            raise Rejected("project_not_found", 404)
        return row

    def _task(self, c, pid, tid):
        row = c.execute("SELECT * FROM awh_m1.tasks WHERE project_id=%s AND task_id=%s",
                        (pid, tid)).fetchone()
        if row is None:
            raise Rejected("task_not_found", 404)
        return row

    def _run(self, c, pid, rid):
        row = c.execute("SELECT * FROM awh_m1.runs WHERE project_id=%s AND run_id=%s",
                        (pid, rid)).fetchone()
        if row is None:
            raise Rejected("run_not_found", 404)
        return row

    def _clock(self, c):
        return c.execute("SELECT clock_timestamp() AS now").fetchone()["now"]

    def _expire(self, c, pid):
        rows = c.execute("UPDATE awh_m1.runs SET state='expired' WHERE project_id=%s "
                         "AND state='active' AND lease_until <= clock_timestamp() RETURNING *",
                         (pid,)).fetchall()
        for run in rows:
            c.execute("UPDATE awh_m1.tasks SET state='reconciling',revision=revision+1 "
                      "WHERE project_id=%s AND task_id=%s", (pid, run["task_id"]))
            self._event(c, pid, "coordinator", "run.expired", {"run_id": run["run_id"]})
        return len(rows)

    def execute(self, principal, pid, command):
        worker_ops = {"claim", "heartbeat", "charge", "finish"}
        roles = {"worker", "supervisor"} if command.operation in worker_ops else {"controller"}
        if command.operation in {"start_execution", "end_execution"}:
            roles = {"supervisor"}
        authorize(principal, pid, roles)
        request = command.model_dump()
        request_hash = digest(request)
        with self.connection() as c:
            project = self._project(c, pid)
            old = c.execute("SELECT * FROM awh_m1.commands WHERE project_id=%s "
                            "AND actor=%s AND command_id=%s",
                            (pid, principal.subject, command.command_id)).fetchone()
            if old:
                if old["request_hash"] != request_hash:
                    raise Rejected("idempotency_key_reused")
                # Historical receipt, not a fresh grant or lease renewal.
                return old["response"]
            # Do not change a controller's CAS revision as a hidden side effect
            # before checking it. Worker mutations independently check DB time.
            expired = self._expire(c, pid) if command.operation in {"claim", "sweep", "reconcile"} else 0
            result = self._dispatch(c, project, principal, command, expired)
            response = wire(result)
            c.execute("INSERT INTO awh_m1.commands VALUES (%s,%s,%s,%s,%s)",
                      (pid, principal.subject, command.command_id, request_hash, Jsonb(response)))
            self._event(c, pid, principal.subject, "command." + command.operation,
                        {"command_id": command.command_id, "request": request,
                         "result": response})
            return response

    def _check_document(self, c, project, doc):
        pid = project["project_id"]
        if doc["budget_limit"] > project["document"]["budget_limit"]:
            raise Rejected("task_budget_exceeds_project")
        if any(not any(resource_contains(parent, child)
                       for parent in project["document"]["resources"])
               for child in doc["resources"]):
            raise Rejected("resource_outside_project")
        for dependency in doc["dependencies"]:
            if dependency == doc["task_id"]:
                raise Rejected("dependency_cycle")
            self._task(c, pid, dependency)
        graph = {r["task_id"]: r["document"]["dependencies"] for r in c.execute(
            "SELECT task_id,document FROM awh_m1.tasks WHERE project_id=%s", (pid,)).fetchall()}
        graph[doc["task_id"]] = doc["dependencies"]
        pending, resolved = set(graph), set()
        while pending:
            ready = {key for key in pending if set(graph[key]) <= resolved}
            if not ready:
                raise Rejected("dependency_cycle")
            pending -= ready
            resolved |= ready

    def _dependencies(self, c, pid, doc):
        c.execute("DELETE FROM awh_m1.dependencies WHERE project_id=%s AND task_id=%s",
                  (pid, doc["task_id"]))
        for dependency in doc["dependencies"]:
            c.execute("INSERT INTO awh_m1.dependencies VALUES (%s,%s,%s)",
                      (pid, doc["task_id"], dependency))

    def _dispatch(self, c, project, principal, cmd, expired):
        pid, op = project["project_id"], cmd.operation
        if op == "sweep":
            return {"expired": expired}
        if op == "submit":
            doc = cmd.task.model_dump()
            self._check_document(c, project, doc)
            if c.execute("SELECT 1 FROM awh_m1.tasks WHERE project_id=%s AND task_id=%s",
                         (pid, doc["task_id"])).fetchone():
                raise Rejected("task_already_exists")
            c.execute("INSERT INTO awh_m1.tasks(project_id,task_id,document,state) "
                      "VALUES (%s,%s,%s,'proposed')", (pid, doc["task_id"], Jsonb(doc)))
            self._dependencies(c, pid, doc)
            return self._task(c, pid, doc["task_id"])
        if op == "claim":
            return self._claim(c, project, principal, cmd)
        if op in {"start_execution", "end_execution"}:
            return self._execution(c, principal, pid, cmd)
        if op in {"heartbeat", "charge", "finish", "reconcile"}:
            run = self._run(c, pid, cmd.run_id)
            if run["fence"] != cmd.fencing_token:
                raise Rejected("stale_fencing_token")
            if op in {"finish", "reconcile"} and c.execute(
                    "SELECT 1 FROM awh_m1.executions WHERE project_id=%s AND run_id=%s AND state='admitted'",
                    (pid, cmd.run_id)).fetchone():
                raise Rejected("execution_stop_not_confirmed")
            if op == "reconcile":
                if run["state"] not in {"expired", "revoked"}:
                    raise Rejected("run_does_not_require_reconciliation")
                # The controller attests the old executor/effects have been
                # reconciled. Burn unused allocation conservatively after loss.
                self._settle(c, principal, cmd, run, burn=True)
                c.execute("UPDATE awh_m1.runs SET state='reconciled' "
                          "WHERE project_id=%s AND run_id=%s", (pid, cmd.run_id))
                c.execute("UPDATE awh_m1.tasks SET state=CASE WHEN state='cancelled' "
                          "THEN state ELSE 'ready' END, revision=revision+1 "
                          "WHERE project_id=%s AND task_id=%s", (pid, run["task_id"]))
            else:
                self._authority(c, principal, run)
                if op == "heartbeat":
                    self._lease_limit(project, cmd)
                    until = min(self._clock(c) + timedelta(seconds=cmd.lease_seconds), run["deadline"])
                    c.execute("UPDATE awh_m1.runs SET lease_until=%s "
                              "WHERE project_id=%s AND run_id=%s", (until, pid, cmd.run_id))
                elif op == "charge":
                    if run["spent"] + cmd.units > run["allocated"]:
                        raise Rejected("allocation_exhausted")
                    self._move_budget(c, pid, run["task_id"], cmd.units, -cmd.units)
                    c.execute("UPDATE awh_m1.runs SET spent=spent+%s "
                              "WHERE project_id=%s AND run_id=%s", (cmd.units, pid, cmd.run_id))
                    self._ledger(c, principal, cmd, run, "charge", cmd.units)
                else:
                    self._settle(c, principal, cmd, run, burn=False)
                    c.execute("UPDATE awh_m1.runs SET state='submitted',artifact_ref=%s "
                              "WHERE project_id=%s AND run_id=%s", (cmd.artifact_ref, pid, cmd.run_id))
                    c.execute("UPDATE awh_m1.tasks SET state='submitted',revision=revision+1 "
                              "WHERE project_id=%s AND task_id=%s", (pid, run["task_id"]))
            return self._run(c, pid, cmd.run_id)
        task = self._task(c, pid, cmd.task_id)
        if task["revision"] != cmd.expected_revision:
            raise Rejected("stale_task_revision")
        if op == "revise":
            if task["state"] != "proposed" or cmd.task.task_id != cmd.task_id:
                raise Rejected("only_matching_proposal_can_be_revised")
            doc = cmd.task.model_dump()
            self._check_document(c, project, doc)
            c.execute("UPDATE awh_m1.tasks SET document=%s,revision=revision+1 "
                      "WHERE project_id=%s AND task_id=%s", (Jsonb(doc), pid, cmd.task_id))
            self._dependencies(c, pid, doc)
        elif op == "accept":
            if task["state"] != "proposed":
                raise Rejected("task_is_not_proposed")
            c.execute("UPDATE awh_m1.tasks SET state='ready',revision=revision+1, "
                      "accepted_revision=revision+1,contract_hash=%s "
                      "WHERE project_id=%s AND task_id=%s", (digest(task["document"]), pid, cmd.task_id))
        elif op == "cancel":
            if task["state"] in {"cancelled", "completed"}:
                raise Rejected("task_is_terminal")
            c.execute("UPDATE awh_m1.tasks SET state='cancelled',revision=revision+1 "
                      "WHERE project_id=%s AND task_id=%s", (pid, cmd.task_id))
            c.execute("UPDATE awh_m1.runs SET state='revoked' WHERE project_id=%s "
                      "AND task_id=%s AND state='active'", (pid, cmd.task_id))
        elif op == "decide":
            if task["state"] != "submitted":
                raise Rejected("task_has_no_submitted_candidate")
            state = "completed" if cmd.outcome == "complete" else "ready"
            c.execute("UPDATE awh_m1.tasks SET state=%s,revision=revision+1 "
                      "WHERE project_id=%s AND task_id=%s", (state, pid, cmd.task_id))
        return self._task(c, pid, cmd.task_id)

    def _lease_limit(self, project, cmd):
        if cmd.lease_seconds > project["document"]["max_lease_seconds"]:
            raise Rejected("lease_exceeds_project_limit")

    def _execution(self, c, principal, pid, cmd):
        run = self._run(c, pid, cmd.run_id)
        if run["fence"] != cmd.fencing_token or run["owner"] != principal.subject:
            raise Rejected("execution_owner_or_fence_mismatch", 403)
        if cmd.operation == "start_execution":
            self._authority(c, principal, run)
            if c.execute("SELECT 1 FROM awh_m1.executions WHERE project_id=%s AND "
                         "(execution_id=%s OR (run_id=%s AND state='admitted'))",
                         (pid, cmd.execution_id, cmd.run_id)).fetchone():
                raise Rejected("execution_already_admitted")
            if run["spent"] + 2 > run["allocated"]:
                raise Rejected("allocation_exhausted")
            self._move_budget(c, pid, run["task_id"], 2, -2)
            c.execute("UPDATE awh_m1.runs SET spent=spent+2 WHERE project_id=%s AND run_id=%s",
                      (pid, cmd.run_id))
            self._ledger(c, principal, cmd, run, "charge", 2)
            c.execute("INSERT INTO awh_m1.executions(project_id,execution_id,run_id,manifest_hash,owner,state) "
                      "VALUES (%s,%s,%s,%s,%s,'admitted')",
                      (pid, cmd.execution_id, cmd.run_id, cmd.manifest_hash, principal.subject))
        else:
            row = c.execute("SELECT * FROM awh_m1.executions WHERE project_id=%s AND execution_id=%s",
                            (pid, cmd.execution_id)).fetchone()
            if not row or row["run_id"] != cmd.run_id or row["state"] != "admitted":
                raise Rejected("execution_not_admitted")
            if not cmd.stopped_confirmed:
                raise Rejected("execution_stop_not_confirmed")
            if cmd.outcome == "validated":
                self._authority(c, principal, run)
                if not cmd.receipt_hash:
                    raise Rejected("validated_receipt_required")
            c.execute("UPDATE awh_m1.executions SET state='stopped',outcome=%s,receipt_hash=%s,"
                      "stopped_at=clock_timestamp() WHERE project_id=%s AND execution_id=%s",
                      (cmd.outcome, cmd.receipt_hash, pid, cmd.execution_id))
        return c.execute("SELECT * FROM awh_m1.executions WHERE project_id=%s AND execution_id=%s",
                         (pid, cmd.execution_id)).fetchone()

    def execution_authority(self, principal, pid, execution_id):
        authorize(principal, pid, {"supervisor"})
        with self.connection() as c:
            self._project(c, pid)
            row = c.execute("SELECT * FROM awh_m1.executions WHERE project_id=%s AND execution_id=%s",
                            (pid, execution_id)).fetchone()
            if not row or row["state"] != "admitted" or row["owner"] != principal.subject:
                raise Rejected("execution_not_admitted", 403)
            run = self._run(c, pid, row["run_id"])
            self._authority(c, principal, run)
            return wire({"execution": row, "run": run, "task": self._task(c, pid, run["task_id"])})

    def _claim(self, c, project, principal, cmd):
        pid = project["project_id"]
        self._lease_limit(project, cmd)
        held = c.execute("SELECT resource FROM awh_m1.reservations WHERE project_id=%s", (pid,)).fetchall()
        count = c.execute("SELECT count(*) AS n FROM awh_m1.runs WHERE project_id=%s "
                          "AND state IN ('active','expired','revoked')", (pid,)).fetchone()["n"]
        if count >= project["document"]["max_active_runs"]:
            return {"run": None, "reason": "slots_unavailable"}
        if project["spent"] + project["reserved"] + cmd.budget > project["document"]["budget_limit"]:
            return {"run": None, "reason": "project_budget_unavailable"}
        tasks = c.execute("SELECT t.* FROM awh_m1.tasks t WHERE t.project_id=%s "
                          "AND t.state='ready' AND NOT EXISTS (SELECT 1 FROM awh_m1.dependencies d "
                          "JOIN awh_m1.tasks p ON p.project_id=d.project_id AND p.task_id=d.dependency_id "
                          "WHERE d.project_id=t.project_id AND d.task_id=t.task_id AND p.state<>'completed') "
                          "ORDER BY (t.document->>'priority')::int + "
                          "LEAST(20, GREATEST(0,FLOOR(EXTRACT(EPOCH FROM "
                          "(clock_timestamp()-t.created_at))/3600))) DESC,t.created_at,t.task_id", (pid,)).fetchall()
        for task in tasks:
            doc = task["document"]
            if not set(doc["required_capabilities"]) <= principal.capabilities:
                continue
            if task["spent"] + task["reserved"] + cmd.budget > doc["budget_limit"]:
                continue
            if any(resource_overlaps(resource, h["resource"])
                   for resource in doc["resources"] for h in held):
                continue
            run_id, now = uuid.uuid4().hex, self._clock(c)
            fence = c.execute("UPDATE awh_m1.projects SET fence=fence+1 WHERE project_id=%s "
                              "RETURNING fence", (pid,)).fetchone()["fence"]
            c.execute("INSERT INTO awh_m1.runs(project_id,run_id,task_id,owner,fence,accepted_revision,"
                      "contract_hash,state,lease_until,deadline,allocated) "
                      "VALUES (%s,%s,%s,%s,%s,%s,%s,'active',%s,%s,%s)",
                      (pid, run_id, task["task_id"], principal.subject, fence, task["accepted_revision"],
                       task["contract_hash"], now + timedelta(seconds=cmd.lease_seconds),
                       now + timedelta(seconds=project["document"]["max_run_seconds"]), cmd.budget))
            for resource in doc["resources"]:
                c.execute("INSERT INTO awh_m1.reservations VALUES (%s,%s,%s)", (pid, run_id, resource))
            self._move_budget(c, pid, task["task_id"], 0, cmd.budget)
            c.execute("UPDATE awh_m1.tasks SET state='running',revision=revision+1 "
                      "WHERE project_id=%s AND task_id=%s", (pid, task["task_id"]))
            run = self._run(c, pid, run_id)
            self._ledger(c, principal, cmd, run, "reserve", cmd.budget)
            return {"run": run, "task": self._task(c, pid, task["task_id"])}
        return {"run": None, "reason": "no_eligible_task"}

    def _authority(self, c, principal, run):
        task = self._task(c, run["project_id"], run["task_id"])
        if run["owner"] != principal.subject:
            raise Rejected("run_owned_by_another_worker", 403)
        if (run["state"] != "active" or run["lease_until"] <= self._clock(c)
                or task["state"] != "running" or task["accepted_revision"] != run["accepted_revision"]
                or task["contract_hash"] != run["contract_hash"]):
            raise Rejected("inactive_or_stale_authority")
        if not set(task["document"]["required_capabilities"]) <= principal.capabilities:
            raise Rejected("capability_grant_removed", 403)

    def _move_budget(self, c, pid, tid, spent, reserved):
        c.execute("UPDATE awh_m1.projects SET spent=spent+%s,reserved=reserved+%s WHERE project_id=%s",
                  (spent, reserved, pid))
        c.execute("UPDATE awh_m1.tasks SET spent=spent+%s,reserved=reserved+%s "
                  "WHERE project_id=%s AND task_id=%s", (spent, reserved, pid, tid))

    def _ledger(self, c, principal, cmd, run, kind, units):
        c.execute("INSERT INTO awh_m1.budget_ledger(project_id,run_id,kind,units,command_id,actor) "
                  "VALUES (%s,%s,%s,%s,%s,%s)",
                  (run["project_id"], run["run_id"], kind, units, cmd.command_id, principal.subject))

    def _settle(self, c, principal, cmd, run, burn):
        remaining = run["allocated"] - run["spent"]
        self._move_budget(c, run["project_id"], run["task_id"], remaining if burn else 0, -remaining)
        if burn:
            c.execute("UPDATE awh_m1.runs SET spent=allocated WHERE project_id=%s AND run_id=%s",
                      (run["project_id"], run["run_id"]))
        self._ledger(c, principal, cmd, run, "burn" if burn else "release", remaining)
        c.execute("DELETE FROM awh_m1.reservations WHERE project_id=%s AND run_id=%s",
                  (run["project_id"], run["run_id"]))

    def read(self, principal, pid, kind, identifier=None, after=0, limit=100, after_task=""):
        authorize(principal, pid)
        with self.connection() as c:
            if not c.execute("SELECT 1 FROM awh_m1.projects WHERE project_id=%s", (pid,)).fetchone():
                raise Rejected("project_not_found", 404)
            if kind == "project":
                value = c.execute("SELECT * FROM awh_m1.projects WHERE project_id=%s", (pid,)).fetchone()
            elif kind == "task":
                value = self._task(c, pid, identifier)
            elif kind == "run":
                value = self._run(c, pid, identifier)
                value["lease_current"] = value["state"] == "active" and value["lease_until"] > self._clock(c)
            elif kind == "execution":
                value = c.execute("SELECT * FROM awh_m1.executions WHERE project_id=%s AND execution_id=%s",
                                  (pid, identifier)).fetchone()
                if not value:
                    raise Rejected("execution_not_found", 404)
            elif kind == "tasks":
                value = c.execute("SELECT * FROM awh_m1.tasks WHERE project_id=%s AND task_id>%s "
                                  "ORDER BY task_id LIMIT %s", (pid, after_task, limit)).fetchall()
            else:
                value = c.execute("SELECT * FROM awh_m1.outbox WHERE project_id=%s AND id>%s "
                                  "ORDER BY id LIMIT %s", (pid, after, limit)).fetchall()
            return wire(value)
