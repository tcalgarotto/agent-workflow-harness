# SPDX-License-Identifier: Apache-2.0
"""Provider-neutral executor lifecycle contract; implementations are untrusted."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol


@dataclass(frozen=True)
class ExecutorCapabilities:
    profile_id: str
    provider: str
    cli_version: str
    can_start: bool
    can_resume: bool
    can_stream_events: bool
    can_request_cancel: bool
    can_confirm_process_termination: bool
    isolation_level: str


@dataclass(frozen=True)
class TaskBinding:
    project_id: str
    task_id: str
    run_id: str
    fence: int
    task_contract_digest: str
    profile_id: str


@dataclass(frozen=True)
class PreparedExecution:
    binding: TaskBinding
    workspace: Path
    # Optional path as seen from inside an independently enforced runtime
    # (for example /workspace in a task container). The host workspace above
    # remains the authority and receipt-validation path.
    runtime_workspace: str | None = None


@dataclass(frozen=True)
class ExecutorEvent:
    kind: str
    session_id: str | None = None
    turn_id: str | None = None
    item_id: str | None = None
    item_type: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class CandidateArtifact:
    session_id: str
    task_contract_digest: str
    content_digest: str
    path: Path


@dataclass(frozen=True)
class TerminationResult:
    requested: bool
    confirmed: bool
    process_exit_code: int | None = None


class ExecutorAdapter(Protocol):
    """The coordinator owns authority; adapters only perform provider I/O."""

    def capabilities(self, profile_id: str) -> ExecutorCapabilities: ...

    def prepare(self, binding: TaskBinding, workspace: Path) -> PreparedExecution: ...

    def start(self, execution: PreparedExecution, prompt: str): ...

    def resume(self, execution: PreparedExecution, session_id: str, prompt: str): ...

    def events(self, session) -> Iterable[ExecutorEvent]: ...

    def request_cancel(self, session) -> TerminationResult: ...

    def confirm_termination(self, session) -> TerminationResult: ...

    def deliver(self, execution: PreparedExecution, session) -> CandidateArtifact: ...
