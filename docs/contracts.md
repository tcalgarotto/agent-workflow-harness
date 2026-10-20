# Contract semantics

All static bundle documents use schema_version `1`, reject unknown properties, and belong to a
project_id. Schemas are packaged in src/agent_workflow_harness/schemas.

The optional [M1 API](m1-coordination.md) has separate `protocol: "m1"` project/task
documents and typed operation contracts. It does not accept a static bundle as
execution authorization or extend the v1 schemas implicitly.

| Contract | Purpose |
|---|---|
| project | Select policy/workflow and requested concurrency/enforcement |
| policy | Bound tools, paths, budgets, and required gates |
| adapter | Declare a runner's capabilities and enforcement level |
| task | Define objective, acceptance criteria, tools, scope, and requirements |
| workflow | Declare dependency nodes for plan, implementation, validation, review, and integration |

`awh validate KIND FILE` validates one schema only. `awh check DIRECTORY` loads all
five named files and additionally checks cross-contract consistency. A valid
bundle must not be interpreted as runtime authorization.

Enforcement levels are ordered advised < delivery < execution. A declaration must
satisfy the higher minimum of project and policy. This is a consistency check;
future conformance tests must verify whether the runner actually delivers it.

Scopes are POSIX-style, repository-relative files or directories ending in `/`.
No glob patterns, absolute paths, backslashes, parent traversal, control
characters, or noncanonical separators are accepted. Directory containment uses
a slash boundary. A task cannot claim a parent of a protected directory because
that broad scope includes protected content.

Exactly one integrate node is required. Required policy gates must be ancestors
of it, and at least one qualifying gate of each required kind must follow every
implement node. All implement nodes must feed the integration chain. These
structural rules cannot verify independent review, trusted receipts, or immutable
code snapshots; those belong to the planned runtime.
