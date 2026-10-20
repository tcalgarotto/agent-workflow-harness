# SPDX-License-Identifier: Apache-2.0
"""M2a adversarial checks against real Linux containers and PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import threading
import time
import unittest
import uuid

try:
    import docker
    from pydantic import TypeAdapter
    from agent_workflow_harness.supervisor.artifacts import (
        Artifacts, UnsafeExecution, canonical, decode_tree, encode_tree, from_archive, snapshot)
    from agent_workflow_harness.supervisor.docker_backend import DockerBackend
    from agent_workflow_harness.supervisor.profile import Profile, PYTHON_IMAGE
    from agent_workflow_harness.supervisor.runner import Supervisor
    from agent_workflow_harness.coordinator.auth import Principal
    from agent_workflow_harness.coordinator.models import CommandBody, Project, Task
    from agent_workflow_harness.coordinator.store import Store, Rejected
    from psycopg.conninfo import conninfo_to_dict
    AVAILABLE = True
except ImportError:
    AVAILABLE = False

DSN = os.environ.get("AWH_TEST_DATABASE_URL")
REQUIRED = os.environ.get("AWH_REQUIRE_DOCKER") == "1"
if REQUIRED and (not AVAILABLE or not DSN):
    raise RuntimeError("M2a requires Docker extras and disposable PostgreSQL")


def profile(worker="pass", validator="pass", **kwargs):
    return Profile(version="m2a", image=PYTHON_IMAGE,
        worker_command=["/usr/local/bin/python", "-I", "-c", worker],
        validator_command=["/usr/local/bin/python", "-I", "-c", validator],
        **dict({"timeout_seconds": 4, "memory_mb": 128, "pids": 32,
                "cpu_millis": 500, "workspace_mb": 16, "output_bytes": 65536}, **kwargs))


def cmd(operation, **kwargs):
    return TypeAdapter(CommandBody).validate_python(
        {"operation": operation, "command_id": uuid.uuid4().hex, **kwargs})


class StoreAuthority:
    """Same real coordinator boundary as HTTP, without introducing test sleeps/network."""
    def __init__(self, store, principal, run):
        self.store, self.principal, self.run = store, principal, run
        self.pid, self.rid = run["project_id"], run["run_id"]

    def info(self):
        return {"run": self.store.read(self.principal, self.pid, "run", self.rid),
                "task": self.store.read(self.principal, self.pid, "task", self.run["task_id"])}

    def begin(self, identity, manifest_hash):
        return self.store.execute(self.principal, self.pid, cmd("start_execution", run_id=self.rid,
            fencing_token=self.run["fence"], execution_id=identity, manifest_hash=manifest_hash))

    def check(self, identity):
        return self.store.execution_authority(self.principal, self.pid, identity)

    def end(self, identity, outcome, receipt_hash=None):
        return self.store.execute(self.principal, self.pid, cmd("end_execution", run_id=self.rid,
            fencing_token=self.run["fence"], execution_id=identity, stopped_confirmed=True,
            outcome=outcome, receipt_hash=receipt_hash))

    def lookup(self, identity):
        try:
            return self.store.read(self.principal, self.pid, "execution", identity)
        except Rejected as error:
            if error.status == 404:
                return None
            raise


@unittest.skipUnless(AVAILABLE, "Install supervisor/coordinator test extras")
class ArtifactTests(unittest.TestCase):
    def test_snapshot_rejects_symlinks_hardlinks_and_excludes_metadata(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root/"good.txt").write_bytes(b"good")
            (root/".env").write_text("SECRET")
            (root/".git").mkdir()
            (root/".git/config").write_text("private")
            self.assertEqual(snapshot(root), {"good.txt": b"good"})
            (root/"link").symlink_to(root/"good.txt")
            with self.assertRaises(UnsafeExecution):
                snapshot(root)
            (root/"link").unlink()
            os.link(root/"good.txt", root/"hard")
            with self.assertRaises(UnsafeExecution):
                snapshot(root)

    def test_untrusted_archives_never_extract_paths_or_links(self):
        for name, kind in [("workspace/../escape", tarfile.REGTYPE),
                           ("workspace/link", tarfile.SYMTYPE),
                           ("workspace/link", tarfile.LNKTYPE),
                           ("workspace/fifo", tarfile.FIFOTYPE),
                           ("workspaceevil/escape", tarfile.REGTYPE)]:
            raw = io.BytesIO()
            with tarfile.open(fileobj=raw, mode="w") as archive:
                entry = tarfile.TarInfo(name); entry.type = kind
                entry.linkname = "/etc/passwd"
                archive.addfile(entry, io.BytesIO())
            with self.subTest(name=name, kind=kind), self.assertRaises(UnsafeExecution):
                from_archive([raw.getvalue()])

    def test_receipt_authentication_and_changed_candidate(self):
        with tempfile.TemporaryDirectory() as name:
            artifacts = Artifacts(Path(name))
            candidate = artifacts.put(encode_tree({"src/a": b"good"}))
            receipt = artifacts.receipt({"candidate_hash": candidate, "profile_hash": "profile"})
            self.assertEqual(artifacts.verify(receipt, candidate, "profile")["candidate_hash"], candidate)
            other = artifacts.put(encode_tree({"src/a": b"changed"}))
            with self.assertRaisesRegex(UnsafeExecution, "input_mismatch"):
                artifacts.verify(receipt, other, "profile")
            forged = json.loads(artifacts.get(receipt)); forged["payload"]["profile_hash"] = "forged"
            forged_id = artifacts.put(canonical(forged))
            with self.assertRaisesRegex(UnsafeExecution, "authentication_failed"):
                artifacts.verify(forged_id, candidate, "forged")
            path = artifacts.root/"blobs"/candidate
            path.chmod(0o600); path.write_bytes(b"tampered")
            with self.assertRaisesRegex(UnsafeExecution, "artifact_hash_mismatch"):
                artifacts.verify(receipt, candidate, "profile")

    def test_private_root_and_execution_locks(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); root.chmod(0o755)
            with self.assertRaises(UnsafeExecution):
                Artifacts(root)
            root.chmod(0o700); a = Artifacts(root)
            with a.lock("operation"):
                with self.assertRaisesRegex(UnsafeExecution, "busy"):
                    with a.lock("operation"):
                        pass


@unittest.skipUnless(AVAILABLE and REQUIRED and DSN, "Set AWH_REQUIRE_DOCKER=1 and disposable PostgreSQL")
class SupervisorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not conninfo_to_dict(DSN).get("dbname", "").startswith("awh_test_"):
            raise RuntimeError("Disposable awh_test_* database required")
        cls.store = Store(DSN)
        cls.store.migrate()
        cls.backend = DockerBackend(os.environ.get("AWH_TEST_DOCKER_SOCKET", "/var/run/docker.sock"))
        cls.backend.preflight(profile())  # Missing controls/image fail, never skip.

    def setUp(self):
        with self.store.connection() as c:
            c.execute("TRUNCATE awh_m1.projects CASCADE")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.source = root/"source"; self.source.mkdir()
        (self.source/"src").mkdir()
        (self.source/"src/input.txt").write_text("input")
        (self.source/"protected.txt").write_text("protected")
        self.artifacts = Artifacts(root/"state")
        self.supervisor = Supervisor(self.artifacts, self.backend)
        self.operator = Principal("operator", "controller", frozenset({"demo"}))
        self.identity = Principal("executor", "supervisor", frozenset({"demo"}), frozenset({"python"}))
        self.store.create_project(self.operator, Project(protocol="m1", project_id="demo",
            resources=["path:src/"], max_active_runs=3, budget_limit=100,
            max_lease_seconds=60, max_run_seconds=300))
        task = Task(protocol="m1", task_id="task-a", objective="Synthetic bounded execution",
            acceptance_criteria=["Trusted fixture passes"], resources=["path:src/"],
            dependencies=[], required_capabilities=["python"], priority=1, budget_limit=50)
        self.store.execute(self.operator, "demo", cmd("submit", task=task))
        self.store.execute(self.operator, "demo", cmd("accept", task_id="task-a", expected_revision=1))
        run = self.store.execute(self.identity, "demo", cmd("claim", budget=20, lease_seconds=60))["run"]
        self.authority = StoreAuthority(self.store, self.identity, run)

    def execute(self, chosen=None, identity=None):
        return self.supervisor.run(self.authority, self.source, chosen or profile(), identity)

    def assert_stopped(self, state):
        self.assertTrue(state["stopped_confirmed"], state)
        for name in state["containers"]:
            with self.assertRaises(docker.errors.NotFound):
                self.backend.client.containers.get(name)
            with self.assertRaises(docker.errors.NotFound):
                self.backend.client.volumes.get(name+"-memory")
        self.assertEqual(self.authority.lookup(state["execution_id"])["state"], "stopped")

    def test_pipeline_receipt_exact_tree_commands_and_read_only_validator(self):
        chosen = profile("from pathlib import Path; Path('src/result').write_text('ready')",
                         "from pathlib import Path; assert Path('src/result').read_text()=='ready'; "
                         "assert Path('protected.txt').read_text()=='protected'")
        state = self.execute(chosen)
        self.assertEqual(state["state"], "validated", state)
        self.assert_stopped(state)
        receipt = self.artifacts.verify(state["receipt_hash"], state["candidate_hash"], chosen.identity())
        self.assertEqual(receipt["commands"]["validator"], chosen.validator_command)
        self.assertEqual(receipt["binding"]["contract_hash"], self.authority.run["contract_hash"])
        self.assertEqual(decode_tree(self.artifacts.get(state["candidate_hash"]))["src/result"], b"ready")
        self.assertFalse((self.source/"src/result").exists())
        run = self.store.read(self.identity, "demo", "run", self.authority.rid)
        self.assertEqual(run["spent"], 2)

    def test_real_permissions_host_secrets_sockets_network_and_cgroups(self):
        os.environ["AWH_M2A_HOST_CANARY"] = "host-secret-not-for-container"
        self.addCleanup(os.environ.pop, "AWH_M2A_HOST_CANARY", None)
        attack = '''import os,socket
from pathlib import Path
assert os.getuid()==10001
assert 'AWH_M2A_HOST_CANARY' not in os.environ
assert not Path('/var/run/docker.sock').exists()
assert not Path('/workspace/.git').exists()
for path in ['protected.txt','../outside','/etc/awh-escape','/sys/fs/cgroup/pids.max']:
 try: Path(path).write_text('escape')
 except (PermissionError,OSError): pass
 else: raise AssertionError('write escaped: '+path)
assert 'CapEff:\\t0000000000000000' in Path('/proc/self/status').read_text()
assert 'NoNewPrivs:\\t1' in Path('/proc/self/status').read_text()
assert Path('/sys/fs/cgroup/pids.max').read_text().strip()=='32'
assert int(Path('/sys/fs/cgroup/memory.max').read_text())==128*1024*1024
assert int(Path('/sys/fs/cgroup/memory.swap.max').read_text())==0
quota,period=map(int,Path('/sys/fs/cgroup/cpu.max').read_text().split())
assert quota/period==0.5
s=socket.socket();s.settimeout(0.2)
assert s.connect_ex(('198.51.100.1',443))!=0
s.close()
Path('src/allowed').write_text('allowed')
Path('src/program').write_text('#!/bin/sh\\nexit 0\\n')
Path('src/program').chmod(0o755)
import subprocess
try: subprocess.run(['src/program'],check=True)
except PermissionError: pass
else: raise AssertionError('workspace unexpectedly executable')
'''
        state = self.execute(profile(attack))
        self.assertEqual(state["state"], "validated", state)
        self.assert_stopped(state)

    def test_validator_cannot_write_candidate_or_forge_receipt(self):
        state = self.execute(profile("pass", "from pathlib import Path; Path('src/input.txt').write_text('forged')"))
        self.assertEqual(state["state"], "failed", state)
        self.assertEqual(state["error"], "validator_failed")
        self.assertIsNone(state["receipt_hash"])
        self.assert_stopped(state)

    def test_symlink_output_is_rejected(self):
        state = self.execute(profile("import os; os.symlink('/etc/passwd','src/link')"))
        self.assertEqual(state["state"], "failed", state)
        self.assertIsNone(state["receipt_hash"])
        self.assert_stopped(state)

    def test_wall_timeout_kills_descendants(self):
        state = self.execute(profile("import os,time; pid=os.fork(); time.sleep(30)", timeout_seconds=1))
        self.assertEqual(state["state"], "timed_out", state)
        self.assertIsNone(state["receipt_hash"])
        self.assert_stopped(state)

    def test_output_flood_is_bounded_and_not_success(self):
        state = self.execute(profile("print('x'*100000)", output_bytes=1024))
        self.assertEqual(state["state"], "failed", state)
        self.assertEqual(len(self.artifacts.get(state["worker_output_hash"])), 1024)
        self.assertIsNone(state["receipt_hash"])
        self.assert_stopped(state)

    def test_fork_limit_is_enforced_by_kernel(self):
        attack = '''import os,time,signal
children=[]
limited=False
try:
 for i in range(64):
  try: pid=os.fork()
  except OSError: limited=True; break
  if pid==0: time.sleep(30); os._exit(0)
  children.append(pid)
finally:
 for pid in children: os.kill(pid,signal.SIGKILL)
 for pid in children: os.waitpid(pid,0)
assert limited and len(children)<32
'''
        state = self.execute(profile(attack, pids=16))
        self.assertEqual(state["state"], "validated", state)
        self.assert_stopped(state)

    def test_memory_limit_does_not_produce_validated_receipt(self):
        state = self.execute(profile("x=bytearray(512*1024*1024)", memory_mb=64))
        self.assertNotEqual(state["state"], "validated", state)
        self.assertIsNone(state["receipt_hash"])
        self.assert_stopped(state)

    def test_cancellation_and_revocation_stop_running_container(self):
        for revoke in (False, True):
            identity = uuid.uuid4().hex
            chosen = profile("import time;time.sleep(30)", timeout_seconds=8)
            with ThreadPoolExecutor(1) as pool:
                result = pool.submit(self.execute, chosen, identity)
                for _ in range(100):
                    if self.backend.client.containers.list(filters={"name":"awh-m2a-"+identity+"-worker"}):
                        break
                    time.sleep(0.05)
                else:
                    self.fail("worker never started")
                if revoke:
                    task = self.store.read(self.operator, "demo", "task", "task-a")
                    self.store.execute(self.operator, "demo", cmd("cancel", task_id="task-a", expected_revision=task["revision"]))
                else:
                    self.artifacts.cancel(identity)
                state = result.result(timeout=10)
            self.assertEqual(state["state"], "authority_lost" if revoke else "cancelled", state)
            self.assertIsNone(state["receipt_hash"])
            self.assert_stopped(state)

    def test_duplicate_admission_and_stop_barrier(self):
        identity = uuid.uuid4().hex
        self.authority.begin(identity, "0"*64)
        with self.assertRaisesRegex(Rejected, "already_admitted"):
            self.authority.begin(uuid.uuid4().hex, "1"*64)
        with self.assertRaisesRegex(Rejected, "stop_not_confirmed"):
            self.store.execute(self.identity, "demo", cmd("finish", run_id=self.authority.rid,
                fencing_token=self.authority.run["fence"], artifact_ref="premature"))
        with self.assertRaisesRegex(Rejected, "stop_not_confirmed"):
            self.store.execute(self.identity, "demo", cmd("end_execution", run_id=self.authority.rid,
                fencing_token=self.authority.run["fence"], execution_id=identity,
                stopped_confirmed=False, outcome="failed"))
        worker = Principal(self.identity.subject,"worker",self.identity.projects,self.identity.capabilities)
        with self.assertRaisesRegex(Rejected, "forbidden"):
            self.store.execute(worker, "demo", cmd("end_execution", run_id=self.authority.rid,
                fencing_token=self.authority.run["fence"], execution_id=identity,
                stopped_confirmed=True, outcome="failed"))
        self.authority.end(identity, "recovered")

    def test_restart_recovery_stops_orphan_without_reexecuting(self):
        # Reproduce the durable state at a crash immediately after container start.
        identity = uuid.uuid4().hex
        manifest_hash = "0"*64
        names = [f"awh-m2a-{identity}-worker", f"awh-m2a-{identity}-validator"]
        state = {"execution_id":identity,"manifest_hash":manifest_hash,"containers":names,
                 "manifest":{"binding":{"project_id":"demo","run_id":self.authority.rid}},
                 "state":"admitted","receipt_hash":None,"candidate_hash":None}
        self.artifacts.write_state(identity, state)
        self.authority.begin(identity, manifest_hash)
        self.backend.create(names[0],identity,manifest_hash,profile())
        recovered = Supervisor(Artifacts(self.artifacts.root), DockerBackend()).recover(self.authority,identity)
        self.assertEqual(recovered["state"], "recovered", recovered)
        self.assert_stopped(recovered)
        self.assertEqual(self.store.read(self.identity,"demo","run",self.authority.rid)["spent"],2)

    def test_crash_after_volume_creation_is_recoverable(self):
        identity = uuid.uuid4().hex; manifest_hash = "0"*64
        names=[f"awh-m2a-{identity}-worker",f"awh-m2a-{identity}-validator"]
        state={"execution_id":identity,"manifest_hash":manifest_hash,"containers":names,
               "manifest":{"binding":{"project_id":"demo","run_id":self.authority.rid}},
               "state":"prepared","receipt_hash":None,"candidate_hash":None}
        self.artifacts.write_state(identity,state)
        self.authority.begin(identity,manifest_hash)
        self.backend.client.volumes.create(name=names[0]+"-memory",labels={
            "awh.m2a.execution":identity,"awh.m2a.manifest":manifest_hash})
        recovered=self.supervisor.recover(self.authority,identity)
        self.assertEqual(recovered["state"],"recovered")
        self.assert_stopped(recovered)

    def test_two_workspaces_temporary_files_and_loopback_ports_are_separate(self):
        identity = uuid.uuid4().hex; manifest = "0"*64
        names = [f"awh-m2a-{identity}-a", f"awh-m2a-{identity}-b"]
        chosen = profile("import socket,time; from pathlib import Path; "
            "s=socket.socket();s.bind(('127.0.0.1',43210)); "
            "assert not Path('/tmp/marker').exists();Path('/tmp/marker').write_text('private');"
            "time.sleep(0.3); assert Path('src/input.txt').read_text() in ['A','B']")
        containers = []
        try:
            for name, value in zip(names, [b"A", b"B"]):
                container = self.backend.create(name,identity,manifest,chosen)
                containers.append(container)
                self.backend.populate(container,{"src/input.txt":value},["src/"])
            with ThreadPoolExecutor(2) as pool:
                results = list(pool.map(lambda c:self.backend.execute(c,chosen.worker_command,chosen,lambda:True),containers))
            self.assertTrue(all(r["exit_code"]==0 for r in results),results)
            self.assertEqual([self.backend.capture(c)["src/input.txt"] for c in containers],[b"A",b"B"])
        finally:
            for name in names:self.backend.stop(name,identity,manifest)

    def test_exact_file_scope_does_not_grant_parent_directory(self):
        identity=uuid.uuid4().hex;manifest="0"*64;name=f"awh-m2a-{identity}-worker"
        chosen=profile("from pathlib import Path;Path('src/a').write_text('allowed');"
                       "Path('src/not-allowed').write_text('escape')")
        try:
            container=self.backend.create(name,identity,manifest,chosen)
            self.backend.populate(container,{"src/a":b"base","src/other":b"protected"},["src/a"])
            result=self.backend.execute(container,chosen.worker_command,chosen,lambda:True)
            self.assertNotEqual(result["exit_code"],0)
            candidate=self.backend.capture(container)
            self.assertEqual(candidate,{"src/a":b"allowed","src/other":b"protected"})
        finally:self.backend.stop(name,identity,manifest)

    def test_unconfirmed_stop_quarantines_admission_until_real_recovery(self):
        original=self.backend.stop
        self.backend.stop=lambda *args:False  # Inject unavailable control transport.
        try:
            state=self.execute()
            self.assertEqual(state["state"],"quarantined",state)
            self.assertFalse(state["stopped_confirmed"])
            self.assertEqual(self.authority.lookup(state["execution_id"])["state"],"admitted")
            with self.assertRaisesRegex(Rejected,"stop_not_confirmed"):
                self.store.execute(self.identity,"demo",cmd("finish",run_id=self.authority.rid,
                    fencing_token=self.authority.run["fence"],artifact_ref="not-stopped"))
        finally:self.backend.stop=original
        recovered=self.supervisor.recover(self.authority,state["execution_id"])
        self.assertEqual(recovered["state"],"recovered")
        self.assert_stopped(recovered)

    def test_container_watchdog_terminates_without_host_monitor(self):
        identity=uuid.uuid4().hex;manifest="0"*64;name=f"awh-m2a-{identity}-worker"
        try:
            container=self.backend.create(name,identity,manifest,profile(timeout_seconds=1))
            execution=self.backend.client.api.exec_create(container.id,
                ["/usr/local/bin/python","-I","-c","import time;time.sleep(30)"],user="10001:10001")
            self.backend.client.api.exec_start(execution["Id"],detach=True)
            # No Supervisor.execute/guard is running: the container must stop itself.
            container.wait(timeout=15)
            container.reload()
            self.assertFalse(container.attrs["State"]["Running"])
            self.assertFalse(self.backend.client.api.exec_inspect(execution["Id"])["Running"])
        finally:self.backend.stop(name,identity,manifest)


if __name__ == "__main__":
    unittest.main()
