# Target architecture

This describes the intended end-to-end runtime. The project implements static
contract validation and the optional [M1 coordinator](m1-coordination.md).
Agent execution, sandboxing, retrieval and protected integration remain planned.

Start with the [operational blueprint and interactive maps](blueprint/index.html)
for the end-to-end plan, three-worker example, recovery paths and implementation
milestones. Its [Portuguese source](blueprint/README.pt-BR.md) is a dated design
snapshot; the [M1 guide](m1-coordination.md) records current implementation status.

## Reusable layers

1. Core: task state, authorization, resource reservations, events, and evidence.
2. Project pack: domain, accepted requirements, decisions, contracts, and ownership.
3. Stack profile: runtime, tools, test commands, and compatibility constraints.
4. Procedure pack: investigation, implementation, review, and recovery workflows.
5. Executor adapter: a particular runner/version/provider combination.

Workflow engines and observability exporters sit behind interfaces. LangGraph can
provide durable orchestration, Langfuse can receive instrumented traces, and
LangChain can supply retrieval/tool components. None is the authority for all
project data. See interop.md and memory.md.

The [LangChain integration proposal](langchain-integration.md) prioritizes LangGraph
for the first engine experiment, selected LangChain components, optional Deep
Agents workers, and a replaceable telemetry exporter. See
[ADR 0004](decisions/0004-langgraph-first-engine-adapter.md). No library dependency
or runtime capability is added by that proposal.

The [storage proposal](storage-and-retrieval.md) prioritizes PostgreSQL for the
first persistent coordinator and treats lexical/vector retrieval as replaceable
projections. Database transactions, checkpoint storage and search freshness have
separate semantics. See [ADR 0005](decisions/0005-postgresql-first-storage-and-retrieval.md).

## Authorities

- Accepted requirements, decisions, and code: versioned Git revisions.
- Task state, leases, resource locks, and accepted deliveries: coordination service.
- Working change: isolated run and candidate revision.
- Retrieval indexes: rebuildable projections of authorized source revisions.
- Telemetry: observations, not permission to act or proof of task completion.

## Execution path

Intake -> investigate -> task contract -> deterministic eligibility -> atomic
reservation -> isolated run -> trusted validation -> independent review where
required -> protected integration -> knowledge update -> reconciliation.

The scheduler grants resources; an LLM may propose a plan but cannot grant its
own permissions. Lease renewal and monotonic fencing tokens must protect every
shared-effect gateway. Expiration does not terminate a disconnected process.
Recovery must reconcile ambiguous effects before retrying them.

Code, acceptance criteria, policy, and validation receipts must be bound to exact
revisions. Updating a graph checkpoint does not atomically update an external
service. Use transactions, idempotency, durable events, and reconciliation at the
appropriate boundaries.

Proposed extension: bind intended behavior to source evidence before mutation and
revalidate mutable preconditions at the effect boundary. Add an evaluation plane
that measures actions and outcomes independently of permission checks. See
[ADR 0002](decisions/0002-evidence-grounding-and-evaluation.md) and
[evaluation design](evaluation.md). These are target-runtime proposals, not
additional guarantees of the current validator.

Proposed collaboration layer: [development teams](development-teams.md) use a
single task authority, bounded delegation, addressed messages, and controlled
integration. [Task-scoped memory](task-memory.md) supplies accepted context,
attributed observations, proposals, and reusable journals. Native team boards and
goal verdicts do not become a second authority. See
[ADR 0003](decisions/0003-portable-task-memory-and-development-teams.md).

## Change discipline

Use proportional tracks: lightweight documentation checks; standard behavior
tests and review; higher scrutiny for authorization, persistent data, and shared
contracts. An executor cannot waive its own required gates or silently expand
scope. Small tasks should not incur artificial paperwork or meaningless tests.

Start with one trusted local coordinator. Add multi-host PostgreSQL coordination
only after race, recovery, and isolation tests. Worktrees organize files but are
not security sandboxes. A controlled runner needs real OS/container permissions
and scoped credentials, without host-level escape hatches.
