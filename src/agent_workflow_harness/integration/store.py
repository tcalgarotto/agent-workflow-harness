# SPDX-License-Identifier: Apache-2.0
"""Durable admission/commit permit; Git effects deliberately occur outside SQL."""
from datetime import timedelta
from types import SimpleNamespace

from psycopg.types.json import Jsonb

from ..coordinator.store import Store, Rejected, authorize, wire
from ..validation import contains


class IntegrationStore(Store):
    def __init__(self, dsn, subject_grant):
        super().__init__(dsn)
        self.subject_grant = subject_grant

    def register(self, principal, policy):
        pid = policy.project_id
        authorize(principal, pid, {"controller"})
        with self.connection() as c:
            self._project(c, pid)
            old = c.execute("SELECT policy_hash FROM awh_m1.integration_policies WHERE project_id=%s",
                            (pid,)).fetchone()
            if old:
                if old["policy_hash"] != policy.identity():
                    raise Rejected("integration_policy_is_immutable")
                return {"policy_hash": old["policy_hash"]}
            c.execute("INSERT INTO awh_m1.integration_policies VALUES (%s,%s,%s)",
                      (pid, policy.identity(), Jsonb(policy.model_dump())))
            self._event(c, pid, principal.subject, "integration.policy_registered",
                        {"policy_hash": policy.identity()})
            return {"policy_hash": policy.identity()}

    def _policy(self, c, policy):
        self._project(c, policy.project_id)
        row = c.execute("SELECT policy_hash FROM awh_m1.integration_policies WHERE project_id=%s",
                        (policy.project_id,)).fetchone()
        if not row or row["policy_hash"] != policy.identity():
            raise Rejected("integration_policy_not_registered_or_changed")

    def _candidate(self, c, policy, document, renew=False):
        pid, payload = policy.project_id, document["receipt"]
        binding = payload["binding"]
        run = self._run(c, pid, binding["run_id"])
        expected = {key: run[key] for key in ("project_id", "run_id", "task_id", "fence",
                                              "accepted_revision", "contract_hash", "owner")}
        if expected != binding:
            raise Rejected("candidate_authority_binding_mismatch")
        owner = self.subject_grant(run["owner"])
        if owner is None or owner.role != "supervisor" or pid not in owner.projects:
            raise Rejected("executor_grant_removed", 403)
        self._authority(c, owner, run)
        task = self._task(c, pid, run["task_id"])
        writable = [r[5:] for r in task["document"]["resources"] if r.startswith("path:")]
        if (payload["writable_paths"] != writable or any(not any(contains(scope, name) for scope in writable)
                for name in document["review"]["changed_paths"])):
            raise Rejected("candidate_outside_accepted_scope")
        execution = c.execute("SELECT * FROM awh_m1.executions WHERE project_id=%s AND execution_id=%s",
                              (pid, payload["execution_id"])).fetchone()
        if (not execution or execution["state"] != "stopped" or execution["outcome"] != "validated"
                or execution["receipt_hash"] != document["receipt_hash"]
                or execution["manifest_hash"] != payload["manifest_hash"]
                or execution["owner"] != run["owner"] or execution["run_id"] != run["run_id"]):
            raise Rejected("validated_execution_receipt_required")
        if c.execute("SELECT 1 FROM awh_m1.executions WHERE project_id=%s AND run_id=%s AND state='admitted'",
                     (pid, run["run_id"])).fetchone():
            raise Rejected("execution_stop_not_confirmed")
        if renew:
            until = min(self._clock(c) + timedelta(seconds=10), run["deadline"])
            c.execute("UPDATE awh_m1.runs SET lease_until=%s WHERE project_id=%s AND run_id=%s",
                      (until, pid, run["run_id"]))
        return run

    def approve(self, principal, policy, document, review_key):
        authorize(principal, policy.project_id, {"controller"})
        with self.connection() as c:
            self._policy(c, policy)
            run = self._candidate(c, policy, document)
            if principal.subject == run["owner"]:
                raise Rejected("independent_review_required", 403)
            c.execute("INSERT INTO awh_m1.integration_reviews(project_id,review_key,approver,document) "
                      "VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                      (policy.project_id, review_key, principal.subject, Jsonb(document["review"])))
            self._event(c, policy.project_id, principal.subject, "integration.review_approved",
                        {"review_key": review_key, "review": document["review"]})
            return {"review_key": review_key, "approved": True}

    def _review(self, c, policy, document):
        if not document["review"]["protected_paths"]:
            return
        row = c.execute("SELECT * FROM awh_m1.integration_reviews WHERE project_id=%s AND review_key=%s",
                        (policy.project_id, document["review_key"])).fetchone()
        reviewer = self.subject_grant(row["approver"]) if row else None
        if (not row or row["document"] != document["review"] or reviewer is None
                or reviewer.role != "controller" or policy.project_id not in reviewer.projects
                or reviewer.subject == document["receipt"]["binding"]["owner"]):
            raise Rejected("protected_check_change_requires_authorized_review", 403)

    def admit(self, principal, policy, identity, document):
        authorize(principal, policy.project_id, {"integrator"})
        with self.connection() as c:
            self._policy(c, policy)
            if c.execute("SELECT 1 FROM awh_m1.integrations WHERE project_id=%s AND "
                         "(integration_id=%s OR state='prepared' OR (run_id=%s AND state<>'aborted'))",
                         (policy.project_id, identity, document["receipt"]["binding"]["run_id"])).fetchone():
                raise Rejected("integration_exists_or_reconciliation_required")
            run = self._candidate(c, policy, document, renew=True)
            self._review(c, policy, document)
            if run["spent"] + 1 > run["allocated"]:
                raise Rejected("allocation_exhausted")
            self._move_budget(c, policy.project_id, run["task_id"], 1, -1)
            c.execute("UPDATE awh_m1.runs SET spent=spent+1 WHERE project_id=%s AND run_id=%s",
                      (policy.project_id, run["run_id"]))
            self._ledger(c, principal, SimpleNamespace(command_id="integration-"+identity), run, "charge", 1)
            c.execute("INSERT INTO awh_m1.integrations(project_id,integration_id,run_id,execution_id,state,document) "
                      "VALUES (%s,%s,%s,%s,'validating',%s)",
                      (policy.project_id, identity, run["run_id"], document["receipt"]["execution_id"], Jsonb(document)))
            self._event(c, policy.project_id, principal.subject, "integration.admitted", {"integration_id": identity})

    def _operation(self, c, principal, policy, identity):
        authorize(principal, policy.project_id, {"integrator"})
        self._policy(c, policy)
        row = c.execute("SELECT * FROM awh_m1.integrations WHERE project_id=%s AND integration_id=%s",
                        (policy.project_id, identity)).fetchone()
        if not row:
            raise Rejected("integration_not_found", 404)
        return row

    def check(self, principal, policy, identity):
        with self.connection() as c:
            row = self._operation(c, principal, policy, identity)
            if row["state"] != "validating":
                raise Rejected("integration_is_not_validating")
            self._candidate(c, policy, row["document"], renew=True)
            self._review(c, policy, row["document"])
            return True

    def prepare(self, principal, policy, identity, effect):
        with self.connection() as c:
            row = self._operation(c, principal, policy, identity)
            if row["state"] != "validating":
                raise Rejected("integration_is_not_validating")
            self._candidate(c, policy, row["document"])
            self._review(c, policy, row["document"])
            if c.execute("SELECT 1 FROM awh_m1.integrations WHERE project_id=%s AND state='prepared'",
                         (policy.project_id,)).fetchone():
                raise Rejected("integration_reconciliation_required")
            doc = {**row["document"], "effect": effect}
            c.execute("UPDATE awh_m1.integrations SET state='prepared',document=%s,updated_at=clock_timestamp() "
                      "WHERE project_id=%s AND integration_id=%s", (Jsonb(doc), policy.project_id, identity))
            self._event(c, policy.project_id, principal.subject, "integration.prepared",
                        {"integration_id": identity, "effect": effect})

    def settle(self, principal, policy, identity, committed):
        # Caller proves the Git marker (or its absence) under the operation lock.
        # This is reconciliation of a durable permit, never a fresh expired grant.
        with self.connection() as c:
            row = self._operation(c, principal, policy, identity)
            target = "committed" if committed else "aborted"
            if row["state"] == target:
                return wire(row)
            if row["state"] not in ({"prepared"} if committed else {"validating", "prepared"}):
                raise Rejected("integration_is_terminal")
            if committed:
                run = self._run(c, policy.project_id, row["run_id"])
                self._settle(c, principal, SimpleNamespace(command_id="integration-"+identity), run, burn=False)
                c.execute("UPDATE awh_m1.runs SET state='submitted',artifact_ref=%s "
                          "WHERE project_id=%s AND run_id=%s",
                          (row["document"]["effect"]["commit"], policy.project_id, row["run_id"]))
                c.execute("UPDATE awh_m1.tasks SET state='completed',revision=revision+1 "
                          "WHERE project_id=%s AND task_id=%s", (policy.project_id, run["task_id"]))
            c.execute("UPDATE awh_m1.integrations SET state=%s,updated_at=clock_timestamp() "
                      "WHERE project_id=%s AND integration_id=%s", (target, policy.project_id, identity))
            self._event(c, policy.project_id, principal.subject, "integration."+target,
                        {"integration_id": identity})
            return {"integration_id": identity, "state": target}
