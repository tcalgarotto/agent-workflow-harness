# ADR 0004: prioritize a LangGraph engine adapter

Status: proposed

## Context

The project intends to use the LangChain ecosystem while preserving portable
contracts and enforcement outside model behavior. Native handoffs, graph
execution, worker loops, shared knowledge and observability solve different
problems. See the [source review](../research/2026-10-20-langchain-ecosystem.md).

## Proposal

- Prioritize LangGraph for the first engine experiment after the coordinator's
  authority and effect boundaries exist. Use explicit control flow and bounded
  parallelism; retain the replaceable engine interface.
- Use selected LangChain components where needed. Evaluate Deep Agents as an
  optional constrained worker, not another authority for task acceptance.
- Reserve `langgraph-swarm` for measured handoff needs. Do not equate a library
  named swarm with safe concurrent development.
- Keep checkpointer state, cross-thread memory, authoritative operational records,
  reviewed Git content and telemetry distinct.
- Keep LangSmith optional behind the observability/evaluation boundary. Compare
  it with the existing Langfuse candidate before choosing an initial exporter.

## Consequences

The [integration design](../langchain-integration.md) specifies recovery,
delegation, memory, sandbox, privacy and acceptance requirements. No dependencies
are added and no engine, memory service, adapter or hosting platform is selected
for production by this ADR. ADK remains a possible alternative through the same
engine contract; two engines must not independently schedule the same authority.

Promotion requires synthetic crash/replay/concurrency tests followed by a small
real-runner pilot. Use pinned versions and project-specific measurements. Source
benchmarks are evidence about their workloads, not our expected productivity or
security. This proposal does not change the existing version-1 schemas.
