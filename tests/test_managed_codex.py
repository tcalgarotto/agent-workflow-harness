# SPDX-License-Identifier: Apache-2.0
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from agent_workflow_harness.executors.managed_codex import (
    BoundaryReceipt,
    BoundaryUnavailable,
    BoundaryViolation,
    ManagedCodexAppServer,
    _binding_digest,
)
from agent_workflow_harness.executors.protocol import PreparedExecution, TaskBinding


class FakeProcess:
    def __init__(self, stdout):
        self.stdin = StringIO()
        self.stdout = StringIO(stdout)
        self.exit_code = None

    def poll(self):
        return self.exit_code

    def wait(self, timeout=None):
        if self.exit_code is None:
            raise TimeoutError()
        return self.exit_code


class FakeBoundary:
    def __init__(self, execution, stdout):
        self.execution = execution
        self.process = FakeProcess(stdout)
        self.prepared = 0
        self.spawned = 0
        self.stop_result = True

    def prepare(self, execution, profile_id):
        self.prepared += 1
        return BoundaryReceipt(profile_id, str(Path(execution.workspace).resolve()),
                               _binding_digest(execution), "isolated-run", "network-policy",
                               "awh-tool-gateway")

    def spawn(self, receipt, command):
        self.spawned += 1
        assert command == ["codex", "app-server", "--listen", "stdio://"]
        return self.process

    def terminate(self, process, grace_seconds):
        if self.stop_result:
            process.exit_code = -9
        return self.stop_result


def rpc_results():
    return "\n".join([
        '{"id":1,"result":{}}',
        '{"id":2,"result":{"thread":{"id":"thread_1"}}}',
        '{"id":3,"result":{"turn":{"id":"turn_1"}}}',
        '{"id":4,"result":{}}',
    ]) + "\n"


class ManagedCodexTest(unittest.TestCase):
    def prepared(self, directory):
        binding = TaskBinding("project-a", "task-a", "run-a", 7, "a" * 64,
                              "codex-cli-1")
        return PreparedExecution(binding, Path(directory))

    def test_requires_a_boundary_before_any_agent_can_start(self):
        with self.assertRaises(BoundaryUnavailable):
            ManagedCodexAppServer("codex-cli-1", None, lambda *_: True)

    def test_denied_or_stale_authority_never_prepares_or_spawns(self):
        with tempfile.TemporaryDirectory() as directory:
            execution = self.prepared(directory)
            boundary = FakeBoundary(execution, rpc_results())
            adapter = ManagedCodexAppServer("codex-cli-1", boundary,
                                            lambda *_: False)
            with self.assertRaises(BoundaryViolation):
                adapter.start(execution, "work")
            self.assertEqual(0, boundary.prepared)
            self.assertEqual(0, boundary.spawned)

    def test_receipt_must_bind_the_exact_run_and_profile_before_spawn(self):
        with tempfile.TemporaryDirectory() as directory:
            execution = self.prepared(directory)

            class InvalidReceiptBoundary(FakeBoundary):
                def prepare(self, execution, profile_id):
                    self.prepared += 1
                    return BoundaryReceipt(profile_id, str(Path(execution.workspace).resolve()),
                                           "wrong-run", "isolated-run", "network-policy",
                                           "awh-tool-gateway")

            boundary = InvalidReceiptBoundary(execution, rpc_results())
            adapter = ManagedCodexAppServer("codex-cli-1", boundary, lambda *_: True)
            with self.assertRaises(BoundaryViolation):
                adapter.start(execution, "work")
            self.assertEqual(0, boundary.spawned)

    def test_lifecycle_reports_interrupt_request_separately_from_stop_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            execution = self.prepared(directory)
            boundary = FakeBoundary(execution, rpc_results())
            adapter = ManagedCodexAppServer("codex-cli-1", boundary, lambda *_: True)
            session = adapter.start(execution, "work")
            self.assertEqual("thread_1", session.session_id)
            self.assertEqual("turn_1", session.turn_id)

            requested = adapter.request_cancel(session)
            self.assertTrue(requested.requested)
            self.assertFalse(requested.confirmed)

            confirmed = adapter.confirm_termination(session)
            self.assertTrue(confirmed.requested)
            self.assertTrue(confirmed.confirmed)
            self.assertEqual(-9, confirmed.process_exit_code)

    def test_task_bound_to_another_profile_is_rejected_before_authority_check(self):
        with tempfile.TemporaryDirectory() as directory:
            execution = self.prepared(directory)
            boundary = FakeBoundary(execution, rpc_results())
            adapter = ManagedCodexAppServer("codex-cli-2", boundary, lambda *_: True)
            with self.assertRaises(BoundaryViolation):
                adapter.start(execution, "work")
            self.assertEqual(0, boundary.spawned)


if __name__ == "__main__":
    unittest.main()
