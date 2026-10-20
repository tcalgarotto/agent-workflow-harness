# SPDX-License-Identifier: Apache-2.0
"""Real PostgreSQL acceptance tests. CI requires this suite, never SQLite mocks."""
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import hashlib
import multiprocessing
import os
import unittest
import uuid

try:
    import psycopg
    from psycopg.conninfo import conninfo_to_dict
    from fastapi.testclient import TestClient
    from pydantic import TypeAdapter, ValidationError
    from agent_workflow_harness.coordinator.api import create_app
    from agent_workflow_harness.coordinator.auth import Auth, Credential, Principal
    from agent_workflow_harness.coordinator.models import CommandBody, Project, Task
    from agent_workflow_harness.coordinator.store import Rejected, Store
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

DSN = os.environ.get("AWH_TEST_DATABASE_URL")
if os.environ.get("AWH_REQUIRE_POSTGRES") == "1" and (not AVAILABLE or not DSN):
    raise RuntimeError("Required M1 test dependencies/PostgreSQL configuration missing")


def command(operation, **kwargs):
    return TypeAdapter(CommandBody).validate_python(
        {"operation": operation, "command_id": uuid.uuid4().hex, **kwargs})


def concurrent_claim(dsn, worker):
    # Spawned processes have independent modules, connections and memory.
    return Store(dsn).execute(Principal(worker, "worker", frozenset({"demo"}),
                                      frozenset({"python"})), "demo",
                              command("claim", budget=10, lease_seconds=30))


@unittest.skipUnless(AVAILABLE, "Install coordinator test extras")
class ModelTests(unittest.TestCase):
    def test_reject_unsafe_resources_and_duplicate_values(self):
        for resource in ["path:../escape", "path:/absolute", "path:src//x", "path:src/./x",
                         "path:src\\x", "named:db:*", "other:db", "path:src/*"]:
            with self.subTest(resource=resource), self.assertRaises(ValidationError):
                Project(protocol="m1", project_id="demo", resources=[resource],
                        max_active_runs=3, budget_limit=100, max_lease_seconds=60, max_run_seconds=300)

    def test_strict_types_and_unknown_operations(self):
        for data in [dict(budget=True, lease_seconds=30), dict(budget=10, lease_seconds="30"),
                     dict(budget=10, lease_seconds=30, owner="forged")]:
            with self.subTest(data=data), self.assertRaises(ValidationError):
                command("claim", **data)
        with self.assertRaises(ValidationError):
            command("merge")

    def test_auth_fail_closed_and_duplicate_subject(self):
        entry = Credential(subject="worker", role="worker", projects=["demo"], capabilities=[],
                           token_sha256=hashlib.sha256(b"example-test-only-token").hexdigest())
        auth = Auth([entry])
        self.assertIsNone(auth.authenticate("wrong"))
        self.assertEqual(auth.authenticate("example-test-only-token").subject, "worker")
        with self.assertRaises(ValueError):
            Auth([])
        with self.assertRaises(ValueError):
            Auth([entry, entry])


@unittest.skipUnless(AVAILABLE and DSN, "Set AWH_TEST_DATABASE_URL to disposable PostgreSQL")
class CoordinatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # This suite truncates only its explicitly named disposable database.
        if not conninfo_to_dict(DSN).get("dbname", "").startswith("awh_test_"):
            raise RuntimeError("Tests require a disposable database named awh_test_*")
        cls.store = Store(DSN)
        cls.store.migrate()

    def setUp(self):
        with self.store.connection() as c:
            c.execute("TRUNCATE awh_m1.projects CASCADE")
        self.controller = Principal("operator", "controller", frozenset({"demo", "other"}))
        self.worker = Principal("worker-a", "worker", frozenset({"demo"}), frozenset({"python"}))
        self.other_worker = Principal("worker-b", "worker", frozenset({"demo"}), frozenset({"python"}))
        self.store.create_project(self.controller, Project(
            protocol="m1", project_id="demo", resources=["path:src/", "path:src2/", "named:test-db"],
            max_active_runs=3, budget_limit=100, max_lease_seconds=60, max_run_seconds=300))

    def task(self, tid="task-a", resources=None, dependencies=None, priority=0, budget=30, accept=True):
        task = Task(protocol="m1", task_id=tid, objective="Implement a bounded candidate",
                    acceptance_criteria=["Candidate satisfies contract"],
                    resources=resources if resources is not None else ["path:src/"],
                    dependencies=dependencies or [], required_capabilities=["python"],
                    priority=priority, budget_limit=budget)
        row = self.store.execute(self.controller, "demo", command("submit", task=task))
        if accept:
            row = self.store.execute(self.controller, "demo", command(
                "accept", task_id=tid, expected_revision=row["revision"]))
        return row

    def claim(self, worker=None, budget=10):
        return self.store.execute(worker or self.worker, "demo",
                                  command("claim", budget=budget, lease_seconds=30))

    def run_command(self, op, run, actor=None, **kwargs):
        return self.store.execute(actor or self.worker, "demo", command(
            op, run_id=run["run_id"], fencing_token=run["fence"], **kwargs))

    def get_task(self, tid="task-a"):
        return self.store.read(self.controller, "demo", "task", tid)

    def events(self):
        return self.store.read(self.controller, "demo", "events", limit=1000)

    def expire(self, run):
        with self.store.connection() as c:
            c.execute("UPDATE awh_m1.runs SET lease_until=clock_timestamp()-interval '1 second' "
                      "WHERE project_id='demo' AND run_id=%s", (run["run_id"],))

    def test_conflicting_claims_in_separate_processes(self):
        self.task("task-a", ["path:src/"])
        self.task("task-b", ["path:src/api.py"])
        with ProcessPoolExecutor(2, mp_context=multiprocessing.get_context("spawn")) as pool:
            results = list(pool.map(concurrent_claim, [DSN, DSN], ["worker-a", "worker-b"]))
        self.assertEqual(sum(r["run"] is not None for r in results), 1)
        with self.store.connection() as c:
            self.assertEqual(c.execute("SELECT count(*) AS n FROM awh_m1.reservations").fetchone()["n"], 1)

    def test_same_task_ten_connections_and_idempotent_claim(self):
        self.task()
        cmd = command("claim", budget=10, lease_seconds=30)
        with ThreadPoolExecutor(10) as pool:
            results = list(pool.map(lambda _: Store(DSN).execute(self.worker, "demo", cmd), range(10)))
        self.assertTrue(all(r == results[0] for r in results))
        self.assertEqual(len([e for e in self.events() if e["kind"] == "command.claim"]), 1)

    def test_disjoint_boundary_and_named_conflict(self):
        self.task("task-a", ["path:src/", "named:test-db"], priority=10)
        self.task("task-b", ["path:src2/"])
        self.task("task-c", ["named:test-db"])
        self.assertEqual(self.claim()["run"]["task_id"], "task-a")
        self.assertEqual(self.claim(self.other_worker)["run"]["task_id"], "task-b")
        self.assertIsNone(self.claim()["run"])

    def test_project_slot_limit(self):
        for index in range(4):
            self.task(f"task-{index}", [f"path:src/{index}"])
        self.assertTrue(all(self.claim()["run"] for _ in range(3)))
        self.assertEqual(self.claim()["reason"], "slots_unavailable")

    def test_priority_capability_and_dependency_admission(self):
        self.task("task-a", ["path:src/a"], priority=1)
        self.task("task-b", ["path:src/b"], dependencies=["task-a"], priority=100)
        self.task("task-c", ["path:src/c"], priority=10)
        incapable = Principal("no-capability", "worker", frozenset({"demo"}))
        self.assertIsNone(self.claim(incapable)["run"])
        self.assertEqual(self.claim()["run"]["task_id"], "task-c")
        run = self.claim()["run"]
        self.assertEqual(run["task_id"], "task-a")
        self.run_command("finish", run, artifact_ref="sha256:test-candidate")
        self.assertIsNone(self.claim()["run"])
        row = self.get_task("task-a")
        self.store.execute(self.controller, "demo", command("decide", task_id="task-a",
            expected_revision=row["revision"], outcome="complete", evidence_ref="manual:test-review"))
        self.assertEqual(self.claim()["run"]["task_id"], "task-b")

    def test_cas_proposals_immutable_acceptance_and_cycles(self):
        original = self.task(accept=False)
        self.task("task-b", dependencies=["task-a"], accept=False)
        updated = dict(original["document"], dependencies=["task-b"])
        with self.assertRaisesRegex(Rejected, "dependency_cycle"):
            self.store.execute(self.controller, "demo", command("revise", task_id="task-a",
                expected_revision=1, task=Task(**updated)))
        accepted = self.store.execute(self.controller, "demo", command("accept", task_id="task-a", expected_revision=1))
        with self.assertRaisesRegex(Rejected, "stale_task_revision"):
            self.store.execute(self.controller, "demo", command("cancel", task_id="task-a", expected_revision=1))
        with self.assertRaisesRegex(Rejected, "only_matching_proposal"):
            self.store.execute(self.controller, "demo", command("revise", task_id="task-a",
                expected_revision=accepted["revision"], task=Task(**original["document"])))

    def test_atomic_rollback_and_outbox(self):
        before = self.events()
        with self.assertRaisesRegex(Rejected, "resource_outside_project"):
            self.task(resources=["path:private/"])
        self.assertEqual(self.events(), before)
        # A failure at event persistence must roll back task and reservation too.
        self.task()
        original = self.store._event
        def fail(*args):
            raise RuntimeError("simulated process failure before commit")
        self.store._event = fail
        try:
            with self.assertRaises(RuntimeError):
                self.claim()
        finally:
            self.store._event = original
        self.assertEqual(self.get_task()["state"], "ready")
        self.assertEqual(self.store.read(self.controller, "demo", "project")["reserved"], 0)
        self.assertIsNotNone(self.claim()["run"])

    def test_budget_idempotency_restart_and_retry(self):
        self.task(budget=15)
        run = self.claim(budget=10)["run"]
        charge = command("charge", run_id=run["run_id"], fencing_token=run["fence"], units=7)
        charged = self.store.execute(self.worker, "demo", charge)
        self.assertEqual(Store(DSN).execute(self.worker, "demo", charge), charged)
        with self.assertRaisesRegex(Rejected, "allocation_exhausted"):
            self.run_command("charge", run, units=4)
        self.run_command("finish", run, artifact_ref="sha256:test-candidate")
        row = self.get_task()
        self.store.execute(self.controller, "demo", command("decide", task_id="task-a",
            expected_revision=row["revision"], outcome="retry", evidence_ref="manual:needs-fix"))
        self.assertIsNone(self.claim(budget=9)["run"])
        retried = self.claim(budget=8)["run"]
        self.assertGreater(retried["fence"], run["fence"])
        self.assertEqual(self.get_task()["spent"], 7)
        with self.assertRaisesRegex(Rejected, "idempotency_key_reused"):
            self.store.execute(self.worker, "demo", charge.model_copy(update={"units": 6}))

    def test_project_budget_no_oversubscription(self):
        self.task("task-a", ["path:src/a"], budget=80)
        self.task("task-b", ["path:src/b"], budget=80)
        self.claim(budget=80)
        self.assertEqual(self.claim(budget=30)["reason"], "project_budget_unavailable")

    def test_expired_authority_retains_resources_until_controller_reconciliation(self):
        self.task()
        run = self.claim()["run"]
        self.expire(run)
        with self.assertRaisesRegex(Rejected, "inactive_or_stale"):
            self.run_command("charge", run, units=1)
        self.task("task-b", ["path:src/api.py"])
        self.assertIsNone(self.claim()["run"])
        self.assertEqual(self.get_task()["state"], "reconciling")
        with self.assertRaisesRegex(Rejected, "forbidden"):
            self.run_command("reconcile", run, evidence_ref="forged")
        self.run_command("reconcile", run, actor=self.controller, evidence_ref="manual:executor-stopped")
        self.assertEqual(self.get_task()["spent"], 10)
        self.assertIsNotNone(self.claim()["run"])
        with self.assertRaisesRegex(Rejected, "inactive_or_stale"):
            self.run_command("finish", run, artifact_ref="late")

    def test_owner_fencing_heartbeat_and_cancel(self):
        self.task()
        run = self.claim()["run"]
        with self.assertRaisesRegex(Rejected, "another_worker"):
            self.run_command("heartbeat", run, actor=self.other_worker, lease_seconds=30)
        with self.assertRaisesRegex(Rejected, "stale_fencing"):
            self.run_command("charge", dict(run, fence=run["fence"]+1), units=1)
        renewed = self.run_command("heartbeat", run, lease_seconds=60)
        self.assertGreater(renewed["lease_until"], run["lease_until"])
        with self.assertRaisesRegex(Rejected, "lease_exceeds"):
            self.run_command("heartbeat", run, lease_seconds=61)
        row = self.get_task()
        self.store.execute(self.controller, "demo", command("cancel", task_id="task-a",
                                                           expected_revision=row["revision"]))
        with self.assertRaisesRegex(Rejected, "inactive_or_stale"):
            self.run_command("heartbeat", run, lease_seconds=30)
        self.run_command("reconcile", run, actor=self.controller, evidence_ref="manual:stopped")
        self.assertEqual(self.get_task()["state"], "cancelled")

    def test_api_auth_scope_roles_and_bounded_json(self):
        credentials = []
        for subject, role, projects in [("operator", "controller", ["demo"]),
                                        ("worker-a", "worker", ["demo"]),
                                        ("outsider", "controller", ["other"])]:
            credentials.append(Credential(subject=subject, role=role, projects=projects,
                capabilities=["python"], token_sha256=hashlib.sha256(subject.encode()).hexdigest()))
        client = TestClient(create_app(self.store, Auth(credentials)))
        path = "/v1/projects/demo"
        self.assertEqual(client.get(path).status_code, 401)
        self.assertEqual(client.get(path, headers={"Authorization": "Bearer invalid"}).status_code, 401)
        self.assertEqual(client.get(path, headers={"Authorization": "Bearer outsider"}).status_code, 403)
        headers = {"Authorization": "Bearer worker-a"}
        self.assertEqual(client.post(path+"/commands", headers=headers,
            json=command("sweep").model_dump()).status_code, 403)
        self.task()
        response = client.post(path+"/commands", headers=headers,
            json=command("claim", budget=10, lease_seconds=30).model_dump())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["run"]["owner"], "worker-a")
        self.assertEqual(client.post(path+"/commands", headers=headers,
            content='{"x":1,"x":2}').status_code, 400)
        self.assertEqual(client.post(path+"/commands", headers=headers, content='{"x":NaN}').status_code, 400)
        self.assertEqual(client.post(path+"/commands", headers=headers, content=b"x"*1_000_001).status_code, 413)
        self.assertEqual(client.post(path+"/commands", headers=headers,
            json={"operation":"claim","command_id":"abcdefgh","budget":True,"lease_seconds":30}).status_code, 422)
        self.assertEqual(client.get(path+"/events?after=0&limit=2", headers=headers).status_code, 200)
        self.assertEqual(len(client.get(path+"/events?after=0&limit=2", headers=headers).json()), 2)

    def test_project_scope_and_migration_repeat(self):
        self.store.migrate()
        self.store.verify_schema()
        self.task()
        outsider = Principal("outsider", "controller", frozenset({"other"}))
        with self.assertRaisesRegex(Rejected, "forbidden"):
            self.store.read(outsider, "demo", "task", "task-a")
        with self.assertRaisesRegex(Rejected, "forbidden"):
            self.store.execute(self.worker, "demo", command("cancel", task_id="task-a", expected_revision=2))

    def test_expired_idempotent_receipt_cannot_renew_authority(self):
        self.task()
        cmd = command("claim", budget=10, lease_seconds=30)
        receipt = self.store.execute(self.worker, "demo", cmd)
        self.expire(receipt["run"])
        self.assertEqual(self.store.execute(self.worker, "demo", cmd), receipt)
        self.assertFalse(self.store.read(self.worker, "demo", "run", receipt["run"]["run_id"])["lease_current"])
        with self.assertRaisesRegex(Rejected, "inactive_or_stale"):
            self.run_command("heartbeat", receipt["run"], lease_seconds=30)

    def test_removed_capability_and_absolute_deadline(self):
        self.task()
        run = self.claim()["run"]
        removed = Principal(self.worker.subject, "worker", self.worker.projects)
        with self.assertRaisesRegex(Rejected, "capability_grant_removed"):
            self.run_command("charge", run, actor=removed, units=1)
        with self.store.connection() as c:
            c.execute("UPDATE awh_m1.runs SET deadline=clock_timestamp()+interval '20 seconds' "
                      "WHERE project_id='demo' AND run_id=%s", (run["run_id"],))
        renewed = self.run_command("heartbeat", run, lease_seconds=60)
        self.assertEqual(renewed["lease_until"], renewed["deadline"])

    def test_unaccepted_unknown_dependencies_and_no_budget_reset(self):
        self.task(accept=False)
        self.assertIsNone(self.claim()["run"])
        with self.assertRaisesRegex(Rejected, "task_not_found"):
            self.task("task-b", dependencies=["missing-task"])
        row = self.get_task()
        self.store.execute(self.controller, "demo", command("accept", task_id="task-a", expected_revision=row["revision"]))
        run = self.claim()["run"]
        self.expire(run)
        self.store.execute(self.controller, "demo", command("sweep"))
        self.assertIsNone(Store(DSN).execute(self.other_worker, "demo",
            command("claim", budget=10, lease_seconds=30))["run"])
        self.assertEqual(self.get_task()["reserved"], 10)

    def test_event_cursor_restart_and_project_isolation(self):
        self.task()
        first = self.events()
        self.claim()
        newer = Store(DSN).read(self.controller, "demo", "events", after=first[-1]["id"])
        self.assertEqual(len(newer), 1)
        self.assertEqual(newer[0]["kind"], "command.claim")
        self.store.create_project(self.controller, Project(protocol="m1", project_id="other",
            resources=[], max_active_runs=1, budget_limit=10, max_lease_seconds=30, max_run_seconds=300))
        self.assertTrue(all(e["project_id"] == "demo" for e in self.events()))

    def test_cancel_expired_run_does_not_create_hidden_cas_livelock(self):
        self.task()
        run = self.claim()["run"]
        self.expire(run)
        row = self.get_task()
        cancelled = self.store.execute(self.controller, "demo", command("cancel", task_id="task-a",
                                                                        expected_revision=row["revision"]))
        self.assertEqual(cancelled["state"], "cancelled")
        self.assertEqual(self.store.read(self.worker, "demo", "run", run["run_id"])["state"], "revoked")


if __name__ == "__main__":
    unittest.main()
