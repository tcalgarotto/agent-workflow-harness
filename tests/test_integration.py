# SPDX-License-Identifier: Apache-2.0
"""M2b uses real Git, PostgreSQL and the M2a Docker validation profile."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
import hashlib
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import unittest
import uuid

try:
    from agent_workflow_harness.integration.gateway import Gateway
    from agent_workflow_harness.integration.git import Git, combine
    from agent_workflow_harness.integration.policy import Policy
    from agent_workflow_harness.integration.store import IntegrationStore
    from agent_workflow_harness.supervisor.artifacts import Artifacts, UnsafeExecution, canonical, encode_tree
    from agent_workflow_harness.supervisor.docker_backend import DockerBackend
    from agent_workflow_harness.supervisor.runner import Supervisor
    from agent_workflow_harness.coordinator.auth import Principal
    from agent_workflow_harness.coordinator.models import Project, Task
    from agent_workflow_harness.coordinator.store import Rejected
    from test_supervisor import profile, cmd, StoreAuthority
    from psycopg.conninfo import conninfo_to_dict
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

DSN = os.environ.get("AWH_TEST_DATABASE_URL")
REQUIRED = os.environ.get("AWH_REQUIRE_DOCKER") == "1"
if REQUIRED and (not AVAILABLE or not DSN):
    raise RuntimeError("M2b requires integration dependencies and disposable PostgreSQL")


def seed(root, files):
    source, bare = root/"source", root/"accepted.git"
    source.mkdir()
    for name, content in files.items():
        target = source/name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
    def git(*args):
        return subprocess.check_output(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgSign=false",
             "-c", "user.name=AWH test", "-c", "user.email=awh@localhost", "-C", str(source), *args],
             stderr=subprocess.DEVNULL)
    git("init", "-b", "main"); git("add", "."); git("commit", "-m", "Synthetic base")
    subprocess.run(["git", "clone", "--bare", "--no-hardlinks", str(source), str(bare)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    bare.chmod(0o700)
    return source, Git(str(bare), "refs/heads/main")


def chosen(worker="from pathlib import Path;Path('src/result').write_text('ready')", validator="pass"):
    value = profile(worker, validator, timeout_seconds=6)
    return value.model_copy(update={"validator_command": ["/usr/local/bin/python", "-I", "-S", "-c", validator]})


@unittest.skipUnless(AVAILABLE, "Install coordinator and supervisor extras")
class GitTests(unittest.TestCase):
    def test_plumbing_ignores_host_environment_hooks_filters_and_cas_failure(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            _, git = seed(root, {"src/a": b"base", "script": b"script"})
            base = git.head(); tree, modes = git.tree(base)
            modes["script"] = "100755"
            hook = root/"hook-ran"
            path = Path(git.repository)/"hooks/reference-transaction"
            path.write_text(f"#!/bin/sh\ntouch {hook}\nexit 1\n"); path.chmod(0o700)
            git.call("config", "filter.attack.clean", f"touch {hook}")
            tree[".gitattributes"] = b"* filter=attack\n"
            tree["src/a"] = b"candidate"
            os.environ["GIT_CONFIG_COUNT"] = "1"
            os.environ["GIT_CONFIG_KEY_0"] = "core.hooksPath"
            os.environ["GIT_CONFIG_VALUE_0"] = str(path.parent)
            try:
                commit = git.commit(tree, modes, base, "1"*32)
                git.integrate("demo", "1"*32, base, commit)
            finally:
                for key in ("GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"):
                    os.environ.pop(key, None)
            self.assertFalse(hook.exists())
            self.assertEqual(git.tree(commit), (tree, modes | {".gitattributes": "100644"}))
            self.assertTrue(git.effect("demo", "1"*32, base, commit))
            stale = git.commit({**tree, "src/a": b"stale"}, modes, base, "2"*32)
            with self.assertRaises(UnsafeExecution):
                git.integrate("demo", "2"*32, base, stale)
            self.assertEqual(git.head(), commit)
            self.assertIsNone(git.ref(git.marker("demo", "2"*32)))

    def test_bounded_regular_file_git_profile_and_full_revision(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); source, git = seed(root, {"a": b"base"})
            with self.assertRaisesRegex(UnsafeExecution, "full_git_object"):
                git.tree("HEAD")
            with self.assertRaisesRegex(UnsafeExecution, "private_owned"):
                Git(str(source), "refs/heads/main")
            link = root/"link"; link.symlink_to(git.repository)
            with self.assertRaises(UnsafeExecution):
                Git(str(link), "refs/heads/main")
            oid = git.call("hash-object", "-w", "--stdin", data=b"/etc/passwd").strip().decode()
            tree = git.call("mktree", data=f"120000 blob {oid}\tlink\n".encode()).strip().decode()
            commit = git.call("commit-tree", tree, "-p", git.head(), data=b"Unsupported link\n").strip().decode()
            with self.assertRaisesRegex(UnsafeExecution, "regular_files"):
                git.tree(commit)

    def test_file_level_merge_preserves_unrelated_changes_and_rejects_collisions(self):
        base = {"src/a": b"a", "src/b": b"b"}
        candidate = {"src/a": b"new", "src/b": b"b"}
        result, paths = combine(base, candidate, {**base, "src/b": b"other"})
        self.assertEqual(result, {"src/a": b"new", "src/b": b"other"})
        self.assertEqual(paths, ["src/a"])
        with self.assertRaisesRegex(UnsafeExecution, "conflicts"):
            combine(base, candidate, {**base, "src/a": b"other"})
        with self.assertRaisesRegex(UnsafeExecution, "collision"):
            combine({}, {"a": b"file"}, {"a/b": b"existing"})


@unittest.skipUnless(AVAILABLE and REQUIRED and DSN, "Set AWH_REQUIRE_DOCKER=1 and disposable PostgreSQL")
class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not conninfo_to_dict(DSN).get("dbname", "").startswith("awh_test_"):
            raise RuntimeError("Disposable awh_test_* database required")
        cls.backend = DockerBackend(os.environ.get("AWH_TEST_DOCKER_SOCKET", "/var/run/docker.sock"))
        cls.backend.preflight(chosen())

    def setUp(self):
        self.operator = Principal("operator", "controller", frozenset({"demo"}))
        self.worker = Principal("executor", "supervisor", frozenset({"demo"}), frozenset({"python"}))
        self.integrator = Principal("gateway", "integrator", frozenset({"demo"}))
        self.grants = {p.subject: p for p in (self.operator, self.worker, self.integrator)}
        self.store = IntegrationStore(DSN, self.grants.get)
        self.store.migrate()
        with self.store.connection() as c:
            c.execute("TRUNCATE awh_m1.projects CASCADE")
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.git = seed(self.root, {"src/input": b"input", "src/flag": b"safe",
            "src/a/value": b"base", "src/b/value": b"base", "tests/check.py": b"assert True\n"})
        self.base = self.git.head()
        self.artifacts = Artifacts(self.root/"state")
        self.store.create_project(self.operator, Project(protocol="m1", project_id="demo",
            resources=["path:src/", "path:tests/"], max_active_runs=3, budget_limit=200,
            max_lease_seconds=60, max_run_seconds=300))

    def configure(self, selected=None):
        self.profile = selected or chosen()
        self.policy = Policy(version="m2b", project_id="demo", repository=self.git.repository,
            supervisor_state=str(self.artifacts.root), branch=self.git.branch,
            profile=self.profile, protected_paths=[])
        self.store.register(self.operator, self.policy)
        self.gateway = Gateway(self.store, self.integrator, self.policy, self.artifacts, self.backend)

    def produce(self, task_id="task-a", scopes=None, budget=20):
        task = Task(protocol="m1", task_id=task_id, objective="Synthetic protected integration",
            acceptance_criteria=["Trusted fixture passes"], resources=scopes or ["path:src/"],
            dependencies=[], required_capabilities=["python"], priority=1, budget_limit=50)
        self.store.execute(self.operator, "demo", cmd("submit", task=task))
        self.store.execute(self.operator, "demo", cmd("accept", task_id=task_id, expected_revision=1))
        run = self.store.execute(self.worker, "demo", cmd("claim", budget=budget, lease_seconds=60))["run"]
        authority = StoreAuthority(self.store, self.worker, run)
        result = Supervisor(self.artifacts, self.backend).run(authority, self.source, self.profile)
        self.assertEqual(result["state"], "validated", result)
        return result, run

    def integrate(self, result, identity=None):
        return self.gateway.run(result["receipt_hash"], result["candidate_hash"], self.base, identity)

    def advance(self, changes):
        old = self.git.head(); tree, modes = self.git.tree(old)
        tree.update(changes)
        new = self.git.commit(tree, modes, old, uuid.uuid4().hex)
        self.git.call("update-ref", self.git.branch, new, old)
        return new

    def test_success_completes_task_releases_resources_and_binds_combined_receipt(self):
        self.configure(chosen(validator="from pathlib import Path;assert Path('src/result').read_text()=='ready'"))
        result, run = self.produce()
        state = self.integrate(result)
        self.assertEqual(state["state"], "committed", state)
        row = self.store.read(self.integrator, "demo", "integration", state["integration_id"])
        effect = row["document"]["effect"]
        self.assertEqual(self.git.head(), effect["commit"])
        self.assertEqual(self.git.tree(effect["commit"])[0]["src/result"], b"ready")
        receipt = json.loads(self.artifacts.get(effect["validation_receipt"]))["payload"]
        self.assertEqual(receipt["combined_hash"], row["document"]["combined_hash"])
        self.assertTrue(receipt["stopped_confirmed"])
        self.assertEqual(self.store.read(self.operator,"demo","task",run["task_id"])["state"], "completed")
        final = self.store.read(self.integrator,"demo","run",run["run_id"])
        self.assertEqual(final["spent"], 3)
        self.assertEqual(self.store.read(self.integrator,"demo","project")["reserved"], 0)
        replay = self.integrate(result)
        self.assertEqual(replay["state"], "not_admitted")
        self.assertEqual(self.git.head(), effect["commit"])

    def test_latest_base_is_preserved_and_exact_combination_is_revalidated(self):
        self.configure(chosen(validator="from pathlib import Path;assert Path('src/flag').read_text()=='safe'"))
        result, _ = self.produce()
        newer = self.advance({"src/input": b"another accepted change"})
        state = self.integrate(result)
        self.assertEqual(state["state"], "committed", state)
        self.assertEqual(self.git.tree(self.git.head())[0]["src/input"], b"another accepted change")
        row = self.store.read(self.integrator,"demo","integration",state["integration_id"])
        self.assertEqual(row["document"]["effect"]["expected_head"], newer)

    def test_candidate_pass_does_not_override_failed_combined_validation(self):
        self.configure(chosen(validator="from pathlib import Path;assert Path('src/flag').read_text()=='safe'"))
        result, _ = self.produce()
        newer = self.advance({"src/flag": b"reject"})
        state = self.integrate(result)
        self.assertEqual(state["state"], "aborted", state)
        self.assertEqual(state["error"], "combined_validation_failed")
        self.assertEqual(self.git.head(), newer)

    def test_conflicting_delivery_is_refused_without_overwrite(self):
        self.configure(); result, _ = self.produce()
        newer = self.advance({"src/result": b"other delivery"})
        with self.assertRaisesRegex(UnsafeExecution,"conflicts"):
            self.integrate(result)
        self.assertEqual(self.git.head(), newer)

    def test_changed_base_between_validation_and_cas_is_not_silently_overwritten(self):
        self.configure(); result, _ = self.produce()
        original = self.git.integrate
        def race(*args):
            self.winner = self.advance({"src/input": b"winner"})
            return original(*args)
        self.gateway.git = self.git
        self.git.integrate = race
        state = self.integrate(result)
        self.assertEqual(state["state"], "aborted", state)
        self.assertEqual(self.git.head(), self.winner)
        self.git.integrate = original
        retried = self.integrate(result)
        self.assertEqual(retried["state"], "committed", retried)
        self.assertEqual(self.git.tree(self.git.head())[0]["src/input"], b"winner")

    def test_protected_checks_require_independent_review_of_exact_base_and_diff(self):
        self.configure(chosen("from pathlib import Path;Path('tests/check.py').write_text('weakened')"))
        result, run = self.produce(scopes=["path:tests/"])
        denied = self.integrate(result)
        self.assertEqual(denied["state"], "not_admitted", denied)
        self.assertIn("authorized_review", denied["error"])
        doc, _, _ = self.gateway.plan(result["receipt_hash"],result["candidate_hash"],self.base)
        with self.assertRaisesRegex(Rejected, "forbidden"):
            self.store.approve(self.worker,self.policy,doc,doc["review_key"])
        self.store.approve(self.operator,self.policy,doc,doc["review_key"])
        self.advance({"src/input": b"new accepted base"})
        self.assertEqual(self.integrate(result)["state"], "not_admitted")
        doc, _, _ = self.gateway.plan(result["receipt_hash"],result["candidate_hash"],self.base)
        self.store.approve(self.operator,self.policy,doc,doc["review_key"])
        final = self.integrate(result)
        self.assertEqual(final["state"], "committed", final)

    def test_stale_authority_and_removed_capability_are_rejected(self):
        self.configure(); result, run = self.produce()
        self.grants[self.worker.subject] = replace(self.worker, capabilities=frozenset())
        self.assertIn("capability_grant_removed", self.integrate(result)["error"])
        self.grants[self.worker.subject] = self.worker
        task = self.store.read(self.operator,"demo","task",run["task_id"])
        self.store.execute(self.operator,"demo",cmd("cancel",task_id=run["task_id"],expected_revision=task["revision"]))
        self.assertIn("stale_authority", self.integrate(result)["error"])
        self.assertEqual(self.git.head(), self.base)

    def test_tampered_receipt_profile_git_base_and_unrecorded_receipt_fail_closed(self):
        self.configure(); result, _ = self.produce()
        original = json.loads(self.artifacts.get(result["receipt_hash"]))
        original["payload"]["binding"]["fence"] += 1
        forged = self.artifacts.put(canonical(original))
        with self.assertRaisesRegex(UnsafeExecution,"authentication_failed"):
            self.gateway.run(forged,result["candidate_hash"],self.base)
        changed = self.policy.model_copy(update={"profile":chosen(validator="assert False")})
        with self.assertRaisesRegex(Rejected,"policy_not_registered"):
            Gateway(self.store,self.integrator,changed,self.artifacts,self.backend).run(
                result["receipt_hash"],result["candidate_hash"],self.base)
        newer = self.advance({"src/input":b"different"})
        with self.assertRaisesRegex(UnsafeExecution,"base_does_not_match"):
            self.gateway.run(result["receipt_hash"],result["candidate_hash"],newer)
        with self.store.connection() as c:
            c.execute("UPDATE awh_m1.executions SET receipt_hash=%s", ("0"*64,))
        self.assertIn("validated_execution_receipt_required", self.integrate(result)["error"])

    def test_scope_is_rechecked_even_for_authenticated_faulty_producer(self):
        self.configure(); result, _ = self.produce(scopes=["path:src/result"])
        payload = json.loads(self.artifacts.get(result["receipt_hash"]))["payload"]
        candidate = {**self.git.tree(self.base)[0], "src/input":b"outside scope"}
        payload["candidate_hash"] = self.artifacts.put(encode_tree(candidate))
        result["candidate_hash"] = payload["candidate_hash"]
        result["receipt_hash"] = self.artifacts.receipt(payload)
        with self.store.connection() as c:
            c.execute("UPDATE awh_m1.executions SET receipt_hash=%s", (result["receipt_hash"],))
        self.assertIn("outside_accepted_scope", self.integrate(result)["error"])
        self.assertEqual(self.git.head(),self.base)

    def test_merge_credentials_and_completion_remain_unavailable_to_workers(self):
        self.configure(); result, run = self.produce()
        worker_gateway = Gateway(self.store,self.worker,self.policy,self.artifacts,self.backend)
        with self.assertRaisesRegex(Rejected,"forbidden"):
            worker_gateway.run(result["receipt_hash"],result["candidate_hash"],self.base)
        with self.assertRaisesRegex(Rejected,"forbidden"):
            self.store.register(self.integrator,self.policy)
        with self.assertRaisesRegex(Rejected,"governed_project"):
            self.store.execute(self.worker,"demo",cmd("finish",run_id=run["run_id"],
                fencing_token=run["fence"],artifact_ref="bypass"))

    def test_successful_git_effect_recovers_after_database_completion_failure(self):
        self.configure(); result, run = self.produce()
        settle = self.store.settle
        self.store.settle = lambda *args: (_ for _ in ()).throw(ConnectionError("injected unavailable SQL"))
        state = self.integrate(result)
        self.assertEqual(state["state"],"quarantined",state)
        merged = self.git.head(); self.assertNotEqual(merged,self.base,state)
        row = self.store.read(self.integrator,"demo","integration",state["integration_id"])
        self.assertEqual(row["state"],"prepared")
        task = self.store.read(self.operator,"demo","task",run["task_id"])
        with self.assertRaisesRegex(Rejected,"integration_reconciliation"):
            self.store.execute(self.operator,"demo",cmd("cancel",task_id=run["task_id"],expected_revision=task["revision"]))
        with self.store.connection() as c:
            c.execute("UPDATE awh_m1.runs SET lease_until=clock_timestamp()-interval '1 second'")
        self.assertEqual(self.store.execute(self.operator,"demo",cmd("sweep"))["expired"],0)
        self.store.settle = settle
        recovered = self.gateway.recover(state["integration_id"])
        self.assertEqual(recovered["state"],"committed",recovered)
        self.assertEqual(self.git.head(),merged)
        self.assertEqual(self.store.read(self.worker,"demo","run",run["run_id"])["spent"],3)
        self.assertEqual(self.gateway.recover(state["integration_id"])["state"],"committed")

    def test_crash_after_branch_update_without_marker_is_proved_by_accepted_ancestry(self):
        self.configure(); result, _ = self.produce()
        self.gateway.git = self.git
        def branch_only(pid, identity, expected, commit):
            self.git.call("update-ref",self.git.branch,commit,expected)
            raise ConnectionError("injected crash between ref publication")
        self.git.integrate = branch_only
        settle = self.store.settle
        self.store.settle = lambda *args: (_ for _ in ()).throw(ConnectionError("injected SQL failure"))
        state = self.integrate(result)
        self.assertEqual(state["state"],"quarantined",state)
        self.assertIsNone(self.git.ref(self.git.marker("demo",state["integration_id"])))
        self.advance({"src/input": b"later accepted change"})
        later = self.git.head()
        self.store.settle = settle
        recovered = self.gateway.recover(state["integration_id"])
        self.assertEqual(recovered["state"],"committed",recovered)
        self.assertEqual(self.git.head(),later)

    def test_crash_before_git_effect_aborts_without_reexecuting_validator(self):
        self.configure(); result, _ = self.produce()
        self.gateway.git.integrate = lambda *args: (_ for _ in ()).throw(ConnectionError("before CAS"))
        state = self.integrate(result)
        self.assertEqual(state["state"],"aborted",state)
        self.assertEqual(self.git.head(),self.base)
        self.assertEqual(self.gateway.recover(state["integration_id"])["state"],"aborted")

    def test_marker_without_accepted_commit_quarantines_instead_of_false_completion(self):
        self.configure(); result, _ = self.produce()
        def marker_only(pid, identity, expected, commit):
            self.gateway.git.call("update-ref",self.git.marker(pid,identity),commit,"0"*len(commit))
            raise ConnectionError("injected interruption between ref publications")
        self.gateway.git.integrate = marker_only
        state = self.integrate(result)
        self.assertEqual(state["state"],"quarantined",state)
        self.assertEqual(self.git.head(),self.base)
        with self.assertRaisesRegex(UnsafeExecution,"inconsistent_quarantine"):
            self.gateway.recover(state["integration_id"])

    def test_expired_lease_and_exhausted_allocation_cannot_admit_git_effect(self):
        self.configure(); result, run = self.produce(budget=2)
        self.assertIn("allocation_exhausted",self.integrate(result)["error"])
        with self.store.connection() as c:
            c.execute("UPDATE awh_m1.runs SET lease_until=clock_timestamp()-interval '1 second'")
        self.assertIn("stale_authority",self.integrate(result)["error"])
        self.assertEqual(self.git.head(),self.base)

    def test_combined_validator_has_no_write_authority_even_inside_task_scope(self):
        validation = ("from pathlib import Path; "
            "exec(\"if Path('src/flag').read_text()=='attack':\\n Path('src/result').write_text('forged')\")")
        self.configure(chosen(validator=validation)); result, _ = self.produce()
        newer = self.advance({"src/flag":b"attack"})
        state = self.integrate(result)
        self.assertEqual(state["state"],"aborted",state)
        self.assertEqual(state["error"],"combined_validation_failed")
        self.assertEqual(self.git.head(),newer)

    def test_policy_and_review_authority_cannot_be_replaced_or_self_asserted(self):
        self.configure(chosen("from pathlib import Path;Path('tests/check.py').write_text('changed')"))
        result, run = self.produce(scopes=["path:tests/"])
        with self.assertRaisesRegex(Rejected,"policy_is_immutable"):
            self.store.register(self.operator,self.policy.model_copy(update={"protected_paths":["src/"]}))
        doc, _, _ = self.gateway.plan(result["receipt_hash"],result["candidate_hash"],self.base)
        same_subject = replace(self.operator,subject=run["owner"])
        with self.assertRaisesRegex(Rejected,"independent_review"):
            self.store.approve(same_subject,self.policy,doc,doc["review_key"])
        self.store.approve(self.operator,self.policy,doc,doc["review_key"])
        self.grants.pop(self.operator.subject)
        self.assertIn("authorized_review",self.integrate(result)["error"])

    def test_sql_prepare_failure_cannot_authorize_git_effect(self):
        self.configure(); result, _ = self.produce()
        with self.store.connection() as c:
            c.execute("CREATE FUNCTION awh_m1.fail_prepare() RETURNS trigger LANGUAGE plpgsql AS $$ "
                      "BEGIN IF NEW.kind='integration.prepared' THEN RAISE EXCEPTION 'injected'; END IF; "
                      "RETURN NEW; END $$")
            c.execute("CREATE TRIGGER fail_prepare BEFORE INSERT ON awh_m1.outbox "
                      "FOR EACH ROW EXECUTE FUNCTION awh_m1.fail_prepare()")
        try:
            state = self.integrate(result)
            self.assertEqual(state["state"],"aborted",state)
            self.assertEqual(self.git.head(),self.base)
        finally:
            with self.store.connection() as c:
                c.execute("DROP TRIGGER fail_prepare ON awh_m1.outbox")
                c.execute("DROP FUNCTION awh_m1.fail_prepare()")

    def test_unconfirmed_validator_stop_holds_admission_and_resources_until_recovery(self):
        self.configure(); result, run = self.produce()
        stop = self.backend.stop
        self.backend.stop = lambda *args: False
        try:
            state = self.integrate(result)
            self.assertEqual(state["state"],"quarantined",state)
            task = self.store.read(self.operator,"demo","task",run["task_id"])
            self.store.execute(self.operator,"demo",cmd("cancel",task_id=run["task_id"],expected_revision=task["revision"]))
            with self.assertRaisesRegex(Rejected,"integration_reconciliation"):
                self.store.execute(self.operator,"demo",cmd("reconcile",run_id=run["run_id"],
                    fencing_token=run["fence"],evidence_ref="unsafe premature release"))
        finally:
            self.backend.stop = stop
        self.assertEqual(self.gateway.recover(state["integration_id"])["state"],"aborted")
        self.store.execute(self.operator,"demo",cmd("reconcile",run_id=run["run_id"],
            fencing_token=run["fence"],evidence_ref="validator stopped after recovery"))

    def test_parallel_disjoint_deliveries_require_current_base_validation(self):
        worker = """from pathlib import Path
for name in ['src/a/value','src/b/value']:
 try: Path(name).write_text('delivered')
 except PermissionError: pass
"""
        self.configure(chosen(worker))
        a, _ = self.produce("task-a",["path:src/a/"])
        b, _ = self.produce("task-b",["path:src/b/"])
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(self.integrate,item) for item in (a,b)]
            results = [f.result(timeout=30) for f in futures]
        self.assertTrue(any(r["state"]=="committed" for r in results),results)
        for candidate, state in zip((a,b),results):
            if state["state"]!="committed":
                retry = self.integrate(candidate)
                self.assertEqual(retry["state"],"committed",retry)
        accepted = self.git.tree(self.git.head())[0]
        self.assertEqual(accepted["src/a/value"],b"delivered")
        self.assertEqual(accepted["src/b/value"],b"delivered")

    def test_cli_auth_export_inspect_integrate_and_recover_in_separate_processes(self):
        self.configure(); result, _ = self.produce()
        tokens = {subject:secrets.token_urlsafe(32) for subject in self.grants}
        credentials = [{"subject":p.subject,"role":p.role,"projects":sorted(p.projects),
                        "capabilities":sorted(p.capabilities),
                        "token_sha256":hashlib.sha256(tokens[p.subject].encode()).hexdigest()}
                       for p in self.grants.values()]
        authfile = self.root/"auth.json"; authfile.write_text(json.dumps(credentials)); authfile.chmod(0o600)
        policyfile = self.root/"policy.json"; policyfile.write_text(self.policy.model_dump_json())
        def cli(subject, *args, success=True):
            env = {**os.environ,"AWH_DATABASE_URL":DSN,"AWH_AUTH_FILE":str(authfile),
                   "AWH_INTEGRATION_TOKEN":tokens[subject]}
            process = subprocess.run([sys.executable,"-c",
                "from agent_workflow_harness.integration.cli import main;raise SystemExit(main())",
                "--policy",str(policyfile),*args],env=env,cwd=self.root,capture_output=True,text=True,timeout=20)
            self.assertEqual(process.returncode,0 if success else 1,process.stderr)
            return [json.loads(line) for line in (process.stdout if success else process.stderr).splitlines()]
        self.assertEqual(cli("operator","register")[-1]["policy_hash"],self.policy.identity())
        self.assertEqual(cli("gateway","export","--base",self.base,"--destination",str(self.root/"export"))[-1]["base_commit"],self.base)
        arguments = ["--receipt",result["receipt_hash"],"--candidate",result["candidate_hash"],"--base",self.base]
        self.assertFalse(cli("gateway","inspect",*arguments)[-1]["accepted_for_integration"])
        self.assertEqual(cli("executor","integrate",*arguments,success=False)[-1]["error"],"forbidden")
        outputs = cli("gateway","integrate",*arguments)
        identity = outputs[0]["integration_id"]
        self.assertEqual(outputs[-1]["state"],"committed",outputs)
        self.assertEqual(cli("gateway","status","--integration-id",identity)[-1]["state"],"committed")
        self.assertEqual(cli("gateway","recover","--integration-id",identity)[-1]["state"],"committed")
        original = policyfile.read_text()
        policyfile.write_text(original[:-1]+',"project_id":"demo"}')
        self.assertEqual(cli("operator","register",success=False)[-1]["error"],
                         "integration_configuration_or_operation_failed")


if __name__ == "__main__":
    unittest.main()
