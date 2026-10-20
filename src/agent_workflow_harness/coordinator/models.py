# SPDX-License-Identifier: Apache-2.0
"""M1 wire contracts; independent of the static v1 bundle schemas."""
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from ..validation import contains, overlaps, safe_path

Identifier = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,63}$")]
CommandID = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_-]{8,128}$")]
Text = Annotated[str, StringConstraints(min_length=1, max_length=2000)]
Count = Annotated[int, Field(ge=1, le=1_000_000)]
Revision = Annotated[int, Field(ge=1)]


def resource_valid(resource: str) -> bool:
    kind, _, name = resource.partition(":")
    if kind == "path":
        return safe_path(name)
    if kind == "named":
        import re
        return re.fullmatch(r"[a-z][a-z0-9-]{0,127}", name) is not None
    return False


def resource_contains(parent: str, child: str) -> bool:
    return (parent == child or (parent.startswith("path:") and child.startswith("path:")
                               and contains(parent[5:], child[5:])))


def resource_overlaps(first: str, second: str) -> bool:
    return (first == second or (first.startswith("path:") and second.startswith("path:")
                               and overlaps(first[5:], second[5:])))


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ResourceModel(Model):
    resources: list[Annotated[str, Field(max_length=2000)]] = Field(max_length=64)

    @field_validator("resources")
    @classmethod
    def valid_resources(cls, value):
        if len(value) != len(set(value)) or not all(map(resource_valid, value)):
            raise ValueError("resources must be unique canonical path: or named: scopes")
        return value


class Project(ResourceModel):
    protocol: Literal["m1"]
    project_id: Identifier
    max_active_runs: int = Field(ge=1, le=32)
    budget_limit: Count
    max_lease_seconds: int = Field(ge=10, le=300)
    max_run_seconds: int = Field(ge=300, le=86400)


class Task(ResourceModel):
    protocol: Literal["m1"]
    task_id: Identifier
    objective: Text
    acceptance_criteria: list[Text] = Field(min_length=1, max_length=100)
    dependencies: list[Identifier] = Field(max_length=100)
    required_capabilities: list[Identifier] = Field(max_length=64)
    priority: int = Field(ge=0, le=100)
    budget_limit: Count

    @field_validator("dependencies", "required_capabilities", "acceptance_criteria")
    @classmethod
    def unique(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("duplicate values")
        return value


class Command(Model):
    command_id: CommandID


class Submit(Command):
    operation: Literal["submit"]
    task: Task


class TaskCommand(Command):
    task_id: Identifier
    expected_revision: Revision


class Accept(TaskCommand):
    operation: Literal["accept"]


class Revise(TaskCommand):
    operation: Literal["revise"]
    task: Task


class Cancel(TaskCommand):
    operation: Literal["cancel"]


class Decide(TaskCommand):
    operation: Literal["decide"]
    outcome: Literal["complete", "retry"]
    evidence_ref: Text


class Claim(Command):
    operation: Literal["claim"]
    budget: Count
    lease_seconds: int = Field(ge=10, le=300)


class RunCommand(Command):
    run_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
    fencing_token: Revision


class Heartbeat(RunCommand):
    operation: Literal["heartbeat"]
    lease_seconds: int = Field(ge=10, le=300)


class Charge(RunCommand):
    operation: Literal["charge"]
    units: Count


class Finish(RunCommand):
    operation: Literal["finish"]
    artifact_ref: Text


class Reconcile(RunCommand):
    operation: Literal["reconcile"]
    evidence_ref: Text


class Sweep(Command):
    operation: Literal["sweep"]


class StartExecution(RunCommand):
    operation: Literal["start_execution"]
    execution_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
    manifest_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class EndExecution(RunCommand):
    operation: Literal["end_execution"]
    execution_id: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}$")]
    stopped_confirmed: bool
    outcome: Literal["validated", "failed", "cancelled", "timed_out", "authority_lost", "recovered"]
    receipt_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] | None = None


CommandBody = Annotated[Union[Submit, Accept, Revise, Cancel, Decide, Claim,
                             Heartbeat, Charge, Finish, Reconcile, Sweep,
                             StartExecution, EndExecution],
                        Field(discriminator="operation")]
