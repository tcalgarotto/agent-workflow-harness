# SPDX-License-Identifier: Apache-2.0
"""Codex app-server lifecycle behind an independently enforced task boundary.

There is deliberately no host-process implementation here. Deployments must
provide a boundary that confines the process, mediates its tools/effects, and
limits provider egress. A boundary receipt binds those controls to one run.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Callable, Protocol, TextIO

from .codex_app_server import CodexAppServerClient, app_server_command
from .protocol import ExecutorEvent, PreparedExecution, TerminationResult


class BoundaryUnavailable(RuntimeError):
    """The requested CLI run has no verified task-scoped process boundary."""


class BoundaryViolation(RuntimeError):
    """A boundary failed to bind its receipt to the requested task."""


@dataclass(frozen=True)
class BoundaryReceipt:
    profile_id: str
    workspace: str
    binding_digest: str
    isolation_id: str
    network_policy_digest: str
    tool_gateway_id: str


class ManagedProcess(Protocol):
    stdin: TextIO
    stdout: TextIO

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...


class AgentProcessBoundary(Protocol):
    """Trusted deployment boundary; never implement this with host Popen.

    `prepare` must enforce per-task filesystem isolation, expose only the
    selected OAuth profile to the trusted CLI, mediate agent tools/effects,
    and restrict network egress to approved provider endpoints. Its receipt
    must describe independently measured controls, not requested settings.
    """

    def prepare(self, execution: PreparedExecution, profile_id: str) -> BoundaryReceipt: ...

    def spawn(self, receipt: BoundaryReceipt, command: list[str]) -> ManagedProcess: ...

    def terminate(self, process: ManagedProcess, grace_seconds: float) -> bool: ...


@dataclass
class CodexSession:
    process: ManagedProcess
    client: CodexAppServerClient
    receipt: BoundaryReceipt
    session_id: str
    turn_id: str
    execution: PreparedExecution
    termination_requested: bool = False


class ManagedCodexAppServer:
    """Start and control Codex only through a task-scoped boundary.

    `authorize` must query current AWH authority (including fence and profile)
    on every start/resume. This class does not inspect auth files or persist
    raw provider events.
    """

    def __init__(self, profile_id: str, boundary: AgentProcessBoundary | None,
                 authorize: Callable[[PreparedExecution, str], bool],
                 executable: str = "codex"):
        if profile_id not in {f"codex-cli-{number}" for number in range(1, 5)}:
            raise ValueError("managed Codex adapter requires a Codex profile")
        if boundary is None:
            raise BoundaryUnavailable("verified task-scoped process boundary is required")
        if not callable(authorize):
            raise ValueError("current-authority callback is required")
        self.profile_id = profile_id
        self.boundary = boundary
        self.authorize = authorize
        self.executable = executable

    def start(self, execution: PreparedExecution, prompt: str, *, model: str | None = None) -> CodexSession:
        return self._launch(execution, prompt, resume_id=None, model=model)

    def resume(self, execution: PreparedExecution, session_id: str, prompt: str) -> CodexSession:
        return self._launch(execution, prompt, resume_id=session_id)

    def events(self, session: CodexSession):
        while session.process.poll() is None:
            yield session.client.next_event()

    def request_cancel(self, session: CodexSession) -> TerminationResult:
        if session.process.poll() is not None:
            return TerminationResult(requested=True, confirmed=True,
                                     process_exit_code=session.process.poll())
        session.client.request_cancel(session.session_id, session.turn_id)
        session.termination_requested = True
        # An accepted turn interrupt is not proof that the process stopped.
        return TerminationResult(requested=True, confirmed=False)

    def confirm_termination(self, session: CodexSession, *, grace_seconds: float = 2.0) -> TerminationResult:
        if grace_seconds < 0 or grace_seconds > 30:
            raise ValueError("grace period must be between 0 and 30 seconds")
        if session.process.poll() is None:
            stopped = self.boundary.terminate(session.process, grace_seconds)
            if not stopped:
                return TerminationResult(requested=session.termination_requested, confirmed=False)
        try:
            code = session.process.wait(timeout=0)
        except Exception:
            return TerminationResult(requested=session.termination_requested, confirmed=False)
        return TerminationResult(requested=session.termination_requested, confirmed=True,
                                 process_exit_code=code)

    def _launch(self, execution: PreparedExecution, prompt: str,
                resume_id: str | None, model: str | None = None) -> CodexSession:
        if execution.binding.profile_id != self.profile_id:
            raise BoundaryViolation("task binding selects a different executor profile")
        if not self.authorize(execution, "resume" if resume_id else "start"):
            raise BoundaryViolation("current task authority was not granted")
        receipt = self.boundary.prepare(execution, self.profile_id)
        _validate_receipt(receipt, execution, self.profile_id)
        process = self.boundary.spawn(receipt, app_server_command(self.executable))
        client = CodexAppServerClient(process.stdout, process.stdin)
        try:
            client.initialize()
            if resume_id:
                session_id, turn_id = client.resume(execution, resume_id, prompt)
            else:
                session_id, turn_id = client.start(execution, prompt, model=model)
        except Exception:
            stopped = self.boundary.terminate(process, 0)
            if not stopped or process.poll() is None:
                raise BoundaryViolation("failed app-server startup could not be confirmed stopped") from None
            raise
        return CodexSession(process, client, receipt, session_id, turn_id, execution)


def _validate_receipt(receipt: BoundaryReceipt, execution: PreparedExecution,
                      profile_id: str) -> None:
    if not isinstance(receipt, BoundaryReceipt):
        raise BoundaryViolation("boundary did not return a valid receipt")
    workspace = Path(execution.workspace)
    if not workspace.is_absolute() or not workspace.is_dir():
        raise BoundaryViolation("prepared workspace is unavailable")
    if (not isinstance(receipt, BoundaryReceipt)
            or receipt.profile_id != profile_id
            or receipt.workspace != str(workspace.resolve())
            or receipt.binding_digest != _binding_digest(execution)
            or not receipt.isolation_id
            or not receipt.network_policy_digest
            or not receipt.tool_gateway_id):
        raise BoundaryViolation("boundary receipt does not match the task binding")


def _binding_digest(execution: PreparedExecution) -> str:
    binding = execution.binding
    value = {
        "project_id": binding.project_id,
        "task_id": binding.task_id,
        "run_id": binding.run_id,
        "fence": binding.fence,
        "task_contract_digest": binding.task_contract_digest,
        "profile_id": binding.profile_id,
    }
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
