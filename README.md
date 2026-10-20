# Agent Workflow Harness

Portable contracts and preflight checks for AI-assisted software development.

[Português](README.pt-BR.md) · [Architecture](docs/architecture.md) · [Roadmap](docs/roadmap.md) · [Contributing](CONTRIBUTING.md)

[Explore the planned workflow](docs/blueprint/index.html): five interactive
Archify maps and a Portuguese operational blueprint. These visualize the target
design, not a running orchestration service.

Build development workflows around explicit tasks, versioned knowledge, scoped
execution, independent verification, and controlled integration. Keep those
contracts when changing projects, models, or agent tools.

## Status: early prototype

**Implemented:** JSON Schemas, a local validation CLI, cross-contract checks, an
example bundle, and automated tests. The optional [M1 coordinator](docs/m1-coordination.md)
adds a loopback authenticated API, PostgreSQL task state, atomic logical resource
claims, leases/fencing, cumulative operation budgets and transactional outbox.

**Not implemented:** agent execution,
filesystem sandboxing, a LangGraph runtime, RAG, MCP endpoints, provider adapters,
or a merge gateway. Validating a declaration does not prove that a runner enforces
it. This is not production security software and does not promise zero hallucinations.

M1 records trusted controller decisions; it does not validate submitted evidence
or stop worker processes. See its [operational limits and setup](docs/m1-coordination.md).

## Try the validator

Python 3.11 or newer is required. Installation is from source; this repository is
not yet published to PyPI.

```sh
git clone https://github.com/tcalgarotto/agent-workflow-harness.git
cd agent-workflow-harness
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/awh check examples/minimal
.venv/bin/awh validate task examples/minimal/task.json
.venv/bin/python -m unittest discover -s tests -v
```

On Windows, use `.venv\Scripts\python.exe` and `.venv\Scripts\awh.exe`.
Validation prints JSON and returns exit code 0 for success or 1 for invalid input.

## What the example demonstrates

A bundle contains `project.json`, `policy.json`, `adapter.json`, `task.json`, and
`workflow.json`. The checker rejects cross-project references, unauthorized tool
declarations, excessive budgets, incompatible declared capabilities, unsafe path
scopes, dependency cycles, and integration paths that bypass required gates.

Scopes use repository-relative files or directories ending in `/`; glob patterns
are intentionally unsupported. The example adapter is a declaration, not an
implemented agent connection. See [contract semantics](docs/contracts.md).

## Design

```mermaid
flowchart TD
  P[Project and stack profile] --> C[Versioned contracts and policy]
  C --> O[Coordinator and scheduler]
  K[Versioned knowledge] --> O
  O --> A[Capability-checked executor adapters]
  A --> S[Isolated execution environments]
  S --> V[Trusted validation and review]
  V --> G[Protected integration]
  G --> K
```

The diagram is the target architecture, not a list of completed features.
LangGraph, Langfuse, LangChain, search engines, and model providers are replaceable
integration points. MCP exposes tools; it does not replace authorization or a sandbox.

Proposed next steps: [evidence and evaluation design](docs/evaluation.md), informed
by a [source review of DoorDash, ADK, and AWS](docs/research/2026-10-20-doordash-adk-aws.md).
These documents do not expand the prototype's implemented capabilities.

Further proposals cover [development teams](docs/development-teams.md),
[task-scoped shared memory](docs/task-memory.md), and their
[coding-team source review](docs/research/2026-10-20-coding-teams-and-swarms.md).
They keep native teams, task journals, and cross-runner collaboration behind
explicit authority and conformance boundaries.

The [LangChain ecosystem proposal](docs/langchain-integration.md) prioritizes a
LangGraph engine experiment, selected LangChain components, optional Deep Agents
workers, and replaceable observability. Its [source review](docs/research/2026-10-20-langchain-ecosystem.md)
distinguishes handoffs from parallel coding and checkpoints from accepted state.

The [storage proposal](docs/storage-and-retrieval.md) prioritizes PostgreSQL for
coordination, staged retrieval and optional backend adapters. The
[database and swarm review](docs/research/2026-10-20-mongodb-postgresql-and-swarms.md)
records technical corrections, access limits and evaluation requirements.

## Contribute

Start with [scope](docs/scope.md), [roadmap](docs/roadmap.md), and
[AGENTS.md](AGENTS.md). Propose a small change with observable acceptance criteria.
Do not claim provider compatibility until an adapter passes conformance tests.

Apache-2.0 licensed. Independent project; no affiliation with or endorsement by
the vendors referenced in the documentation.
