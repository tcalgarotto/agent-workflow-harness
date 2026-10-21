# SPDX-License-Identifier: Apache-2.0
import json
from io import StringIO
import unittest

from agent_workflow_harness.executors.codex_app_server import (
    app_server_command,
    CodexAppServerClient,
    CodexProtocolError,
    initialized_notification,
    initialize_request,
    interrupt_turn_request,
    normalize_event,
    resume_thread_request,
    rpc_request,
    start_thread_request,
    start_turn_request,
)
from agent_workflow_harness.executors.protocol import PreparedExecution, TaskBinding
from pathlib import Path
import tempfile


class CodexAppServerProtocolTest(unittest.TestCase):
    def test_command_uses_local_stdio_transport_only(self):
        self.assertEqual(
            ["/usr/bin/codex", "app-server", "--listen", "stdio://"],
            app_server_command("/usr/bin/codex"),
        )
        with self.assertRaises(ValueError):
            app_server_command("")

    def test_rpc_request_is_single_json_line_and_omits_jsonrpc_header(self):
        line = rpc_request(2, "initialize", {"clientInfo": {"name": "awh"}})
        self.assertEqual(line.count("\n"), 1)
        self.assertEqual({
            "id": 2,
            "method": "initialize",
            "params": {"clientInfo": {"name": "awh"}},
        }, json.loads(line))
        with self.assertRaises(ValueError):
            rpc_request(-1, "initialize", {})

    def test_lifecycle_requests_bind_turns_to_prepared_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binding = TaskBinding("project-a", "task-a", "run-a", 1, "a" * 64,
                                  "codex-cli-1")
            execution = PreparedExecution(binding, root)
            init = json.loads(initialize_request())
            self.assertEqual("initialize", init["method"])
            self.assertEqual("initialized", json.loads(initialized_notification())["method"])

            thread = json.loads(start_thread_request(execution))
            self.assertEqual("thread/start", thread["method"])
            self.assertEqual(str(root), thread["params"]["cwd"])
            resume = json.loads(resume_thread_request(execution, "thread_123"))
            self.assertEqual("thread/resume", resume["method"])
            self.assertTrue(resume["params"]["excludeTurns"])

            turn = json.loads(start_turn_request(execution, "thread_123", "Inspect task"))
            self.assertEqual("turn/start", turn["method"])
            self.assertEqual("externalSandbox", turn["params"]["sandboxPolicy"]["type"])
            self.assertEqual("restricted", turn["params"]["sandboxPolicy"]["networkAccess"])
            self.assertEqual("never", turn["params"]["approvalPolicy"])
            cancel = json.loads(interrupt_turn_request("thread_123", "turn_9"))
            self.assertEqual("turn/interrupt", cancel["method"])

    def test_lifecycle_requests_reject_unsafe_ids_and_unprepared_paths(self):
        binding = TaskBinding("p", "t", "r", 1, "a" * 64, "codex-cli-1")
        with self.assertRaises(ValueError):
            resume_thread_request(PreparedExecution(binding, Path("relative")), "../secret")
        with tempfile.TemporaryDirectory() as temporary:
            execution = PreparedExecution(binding, Path(temporary))
            with self.assertRaises(ValueError):
                start_turn_request(execution, "thread_123", " ")

    def test_known_events_are_normalized_without_free_form_payload(self):
        line = json.dumps({
            "method": "turn/completed",
            "params": {"threadId": "thread_123", "turn": {"id": "turn_2"},
                       "finalText": "must not be retained"},
        })
        event = normalize_event(line)
        self.assertEqual("turn.completed", event.kind)
        self.assertEqual("thread_123", event.session_id)
        self.assertEqual("turn_2", event.turn_id)
        self.assertNotIn("must not be retained", repr(event))

    def test_interrupted_turn_completion_is_not_reported_as_success(self):
        event = normalize_event(json.dumps({
            "method": "turn/completed",
            "params": {"threadId": "thread_1", "turn": {
                "id": "turn_1", "status": "interrupted",
            }},
        }))
        self.assertEqual("turn.cancelled", event.kind)
        self.assertEqual("interrupted", event.status)

    def test_client_handshake_start_resume_event_and_cancel_flow(self):
        with tempfile.TemporaryDirectory() as temporary:
            binding = TaskBinding("project-a", "task-a", "run-a", 1, "a" * 64,
                                  "codex-cli-1")
            execution = PreparedExecution(binding, Path(temporary))
            incoming = "\n".join([
                '{"id":1,"result":{}}',
                '{"method":"thread/started","params":{"thread":{"id":"thread_1"}}}',
                '{"id":2,"result":{"thread":{"id":"thread_1"}}}',
                '{"id":3,"result":{"turn":{"id":"turn_1"}}}',
                '{"id":4,"result":{}}',
                '{"method":"turn/completed","params":{"threadId":"thread_1",'
                '"turn":{"id":"turn_1","status":"interrupted"}}}',
                '{"id":5,"result":{"thread":{"id":"thread_1"}}}',
                '{"id":6,"result":{"turn":{"id":"turn_2"}}}',
            ]) + "\n"
            output = StringIO()
            client = CodexAppServerClient(StringIO(incoming), output)
            client.initialize()
            self.assertEqual(("thread_1", "turn_1"), client.start(execution, "Do task"))
            event = client.next_event()
            self.assertEqual("session.started", event.kind)
            self.assertTrue(client.request_cancel("thread_1", "turn_1"))
            self.assertEqual("turn.cancelled", client.next_event().kind)
            self.assertEqual(("thread_1", "turn_2"), client.resume(
                execution, "thread_1", "Continue task"))

            requests = [json.loads(line) for line in output.getvalue().splitlines()]
            self.assertEqual(["initialize", "initialized", "thread/start", "turn/start",
                              "turn/interrupt", "thread/resume", "turn/start"],
                             [entry["method"] for entry in requests])

    def test_client_requires_handshake_and_sanitizes_rpc_errors(self):
        client = CodexAppServerClient(StringIO(""), StringIO())
        with self.assertRaises(CodexProtocolError):
            client.start(PreparedExecution(
                TaskBinding("p", "t", "r", 1, "a" * 64, "codex-cli-1"), Path("/tmp")),
                "Do task")
        client = CodexAppServerClient(StringIO(
            '{"id":1,"error":{"message":"private path /secret"}}\n'), StringIO())
        with self.assertRaisesRegex(CodexProtocolError, "request failed") as error:
            client.initialize()
        self.assertNotIn("/secret", str(error.exception))

    def test_unknown_malformed_and_unsafe_messages_fail_closed(self):
        self.assertIsNone(normalize_event("not json"))
        self.assertIsNone(normalize_event('{"method":"unknown/event","params":{}}'))
        self.assertIsNone(normalize_event(json.dumps({
            "method": "thread/started", "params": {"thread": {"id": "../secret"}},
        })))


if __name__ == "__main__":
    unittest.main()
