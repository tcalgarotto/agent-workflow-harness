# SPDX-License-Identifier: Apache-2.0
"""Pure protocol helpers for the local Codex app-server adapter.

This module does not launch Codex. A task-scoped process boundary is required
before a live agent session can be enabled.
"""
from __future__ import annotations

import json
from queue import SimpleQueue
import re
from pathlib import Path
from typing import TextIO

from .protocol import ExecutorEvent, PreparedExecution


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class CodexProtocolError(RuntimeError):
    """Sanitized app-server protocol failure; raw provider output is not retained."""


class CodexAppServerClient:
    """Synchronous JSON-RPC client over an already isolated stdio process.

    The caller must launch the server inside the approved task process boundary.
    This class deliberately does not spawn processes or claim isolation.
    """

    def __init__(self, reader: TextIO, writer: TextIO):
        self._reader = reader
        self._writer = writer
        self._request_id = 0
        self._events = SimpleQueue()
        self._initialized = False

    def request(self, method: str, params: dict) -> dict:
        self._request_id += 1
        request_id = self._request_id
        self._writer.write(rpc_request(request_id, method, params))
        self._writer.flush()
        while True:
            message = self._read_message()
            if message.get("id") == request_id:
                if "error" in message:
                    raise CodexProtocolError("Codex app-server request failed")
                result = message.get("result")
                if not isinstance(result, dict):
                    raise CodexProtocolError("Codex app-server returned an invalid result")
                return result
            event = normalize_event(json.dumps(message, ensure_ascii=False))
            if event is not None:
                self._events.put(event)

    def notify(self, method: str, params: dict) -> None:
        if not method or not isinstance(params, dict):
            raise ValueError("invalid app-server notification")
        self._writer.write(json.dumps({"method": method, "params": params},
                                      separators=(",", ":"), ensure_ascii=False) + "\n")
        self._writer.flush()

    def initialize(self) -> dict:
        if self._initialized:
            raise CodexProtocolError("Codex app-server is already initialized")
        result = self.request("initialize", {"clientInfo": {
            "name": "agent-workflow-harness", "title": "Agent Workflow Harness",
            "version": "0.1.0",
        }})
        self.notify("initialized", {})
        self._initialized = True
        return result

    def start(self, execution: PreparedExecution, prompt: str, *, model: str | None = None):
        self._require_initialized()
        params = {"cwd": _workspace(execution), "serviceName": "agent-workflow-harness"}
        if model is not None:
            params["model"] = model
        result = self.request("thread/start", params)
        thread = result.get("thread")
        session_id = thread.get("id") if isinstance(thread, dict) else None
        if not isinstance(session_id, str) or not _SAFE_ID.fullmatch(session_id):
            raise CodexProtocolError("Codex app-server returned an invalid thread ID")
        return self.start_turn(execution, session_id, prompt)

    def resume(self, execution: PreparedExecution, session_id: str, prompt: str):
        self._require_initialized()
        if not isinstance(session_id, str) or not _SAFE_ID.fullmatch(session_id):
            raise ValueError("session ID has an invalid shape")
        result = self.request("thread/resume", {"threadId": session_id, "excludeTurns": True})
        thread = result.get("thread")
        resumed_id = thread.get("id") if isinstance(thread, dict) else None
        if resumed_id != session_id:
            raise CodexProtocolError("Codex app-server resumed a different thread")
        return self.start_turn(execution, session_id, prompt)

    def start_turn(self, execution: PreparedExecution, session_id: str, prompt: str):
        self._require_initialized()
        params = json.loads(start_turn_request(execution, session_id, prompt,
                                               request_id=self._request_id + 1))
        result = self.request(params["method"], params["params"])
        turn = result.get("turn")
        turn_id = turn.get("id") if isinstance(turn, dict) else None
        if not isinstance(turn_id, str) or not _SAFE_ID.fullmatch(turn_id):
            raise CodexProtocolError("Codex app-server returned an invalid turn ID")
        return session_id, turn_id

    def request_cancel(self, session_id: str, turn_id: str) -> bool:
        self._require_initialized()
        params = json.loads(interrupt_turn_request(session_id, turn_id,
                                                   request_id=self._request_id + 1))
        self.request(params["method"], params["params"])
        return True  # Accepted request only; the process/turn may still be running.

    def next_event(self) -> ExecutorEvent:
        if not self._events.empty():
            return self._events.get()
        while True:
            event = normalize_event(json.dumps(self._read_message(), ensure_ascii=False))
            if event is not None:
                return event

    def _read_message(self) -> dict:
        line = self._reader.readline()
        if not line or len(line) > 1_000_000:
            raise CodexProtocolError("Codex app-server stream ended or exceeded the line limit")
        try:
            message = json.loads(line)
        except (TypeError, json.JSONDecodeError):
            raise CodexProtocolError("Codex app-server emitted invalid JSON") from None
        if not isinstance(message, dict):
            raise CodexProtocolError("Codex app-server emitted an invalid message")
        return message

    def _require_initialized(self):
        if not self._initialized:
            raise CodexProtocolError("Codex app-server handshake is required")


def _workspace(execution: PreparedExecution) -> str:
    workspace = Path(execution.workspace)
    if not workspace.is_absolute() or not workspace.is_dir():
        raise ValueError("prepared execution requires an existing absolute workspace")
    return str(workspace.resolve())


def app_server_command(executable: str = "codex") -> list[str]:
    """Return the local, stdio-only app-server command (never a network listener)."""
    if not executable or "\x00" in executable:
        raise ValueError("Codex executable must be a non-empty path or command")
    return [executable, "app-server", "--listen", "stdio://"]


def initialize_request(request_id: int = 0) -> str:
    return rpc_request(request_id, "initialize", {"clientInfo": {
        "name": "agent-workflow-harness", "title": "Agent Workflow Harness",
        "version": "0.1.0",
    }})


def initialized_notification() -> str:
    return json.dumps({"method": "initialized", "params": {}}, separators=(",", ":")) + "\n"


def start_thread_request(execution: PreparedExecution, request_id: int = 1,
                         service_name: str = "agent-workflow-harness") -> str:
    """Create a provider thread bound to the task's working directory."""
    workspace = Path(execution.workspace)
    if not workspace.is_absolute() or not workspace.is_dir():
        raise ValueError("prepared execution requires an existing absolute workspace")
    return rpc_request(request_id, "thread/start", {
        "cwd": str(workspace.resolve()),
        "serviceName": service_name,
    })


def resume_thread_request(execution: PreparedExecution, session_id: str,
                          request_id: int = 2) -> str:
    """Ask Codex to resume a thread; AWH must revalidate task authority first."""
    if not isinstance(session_id, str) or not _SAFE_ID.fullmatch(session_id):
        raise ValueError("session ID has an invalid shape")
    return rpc_request(request_id, "thread/resume", {
        "threadId": session_id,
        "excludeTurns": True,
    })


def start_turn_request(execution: PreparedExecution, session_id: str, prompt: str,
                       request_id: int = 3) -> str:
    """Start a turn that relies on an external task sandbox for enforcement.

    The app-server sandbox field is an instruction to Codex, not independent
    AWH enforcement. The caller must start app-server through a verified
    task-scoped boundary before sending this request.
    """
    workspace = Path(execution.workspace)
    if not workspace.is_absolute() or not workspace.is_dir():
        raise ValueError("prepared execution requires an existing absolute workspace")
    if not isinstance(session_id, str) or not _SAFE_ID.fullmatch(session_id):
        raise ValueError("session ID has an invalid shape")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 200_000:
        raise ValueError("prompt must contain 1 to 200000 characters")
    return rpc_request(request_id, "turn/start", {
        "threadId": session_id,
        "input": [{"type": "text", "text": prompt}],
        "cwd": str(workspace.resolve()),
        "approvalPolicy": "never",
        "sandboxPolicy": {"type": "externalSandbox", "networkAccess": "restricted"},
    })


def interrupt_turn_request(session_id: str, turn_id: str, request_id: int = 4) -> str:
    if (not isinstance(session_id, str) or not _SAFE_ID.fullmatch(session_id)
            or not isinstance(turn_id, str) or not _SAFE_ID.fullmatch(turn_id)):
        raise ValueError("session and turn IDs must have safe shapes")
    return rpc_request(request_id, "turn/interrupt", {
        "threadId": session_id, "turnId": turn_id,
    })


def rpc_request(request_id: int, method: str, params: dict) -> str:
    """Serialize a JSON-RPC request for Codex's documented newline JSON transport."""
    if request_id < 0 or not method or "\x00" in method or not isinstance(params, dict):
        raise ValueError("invalid app-server request")
    return json.dumps({"id": request_id, "method": method, "params": params},
                      separators=(",", ":"), ensure_ascii=False) + "\n"


def normalize_event(line: str) -> ExecutorEvent | None:
    """Map a Codex app-server notification to a small AWH event allowlist.

    Unknown messages and RPC responses are ignored. Free-form text, command
    output, paths, and raw provider payloads are intentionally not retained.
    """
    try:
        message = json.loads(line)
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(message, dict) or not isinstance(message.get("method"), str):
        return None
    method = message["method"]
    params = message.get("params")
    if not isinstance(params, dict):
        return None

    thread = params.get("thread")
    turn = params.get("turn")
    item = params.get("item")
    thread_id = thread.get("id") if isinstance(thread, dict) else params.get("threadId")
    turn_id = turn.get("id") if isinstance(turn, dict) else params.get("turnId")
    turn_status = turn.get("status") if isinstance(turn, dict) else None
    item_id = item.get("id") if isinstance(item, dict) else None
    item_type = item.get("type") if isinstance(item, dict) else None
    status = item.get("status") if isinstance(item, dict) else None

    identifiers = (thread_id, turn_id, item_id)
    if any(value is not None and (not isinstance(value, str) or not _SAFE_ID.fullmatch(value))
           for value in identifiers):
        return None
    if item_type is not None and (not isinstance(item_type, str) or len(item_type) > 64):
        item_type = None
    if status is not None and (not isinstance(status, str) or len(status) > 64):
        status = None

    kinds = {
        "thread/started": "session.started",
        "thread/resumed": "session.resumed",
        "turn/started": "turn.started",
        "turn/completed": "turn.completed",
        "turn/failed": "turn.failed",
        "turn/cancelled": "turn.cancelled",
        "item/started": "item.started",
        "item/completed": "item.completed",
        "item/agentMessage/delta": "message.delta",
        "serverRequest/resolved": "request.resolved",
    }
    kind = kinds.get(method)
    if method == "turn/completed" and turn_status == "interrupted":
        kind = "turn.cancelled"
    if kind is None:
        return None
    if status is None and isinstance(turn_status, str) and len(turn_status) <= 64:
        status = turn_status
    return ExecutorEvent(kind=kind, session_id=thread_id, turn_id=turn_id,
                         item_id=item_id, item_type=item_type, status=status)
