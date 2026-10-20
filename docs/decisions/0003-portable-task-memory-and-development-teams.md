# ADR 0003: portable task memory and development teams

Status: proposed

## Context

Native coding assistants expose different subagent, team, workflow, goal, and
memory primitives. Their task lists, contexts, permissions, and lifecycle behavior
are not a common protocol. A shared transcript cannot safely coordinate writes
or establish accepted engineering knowledge. See the [source review](../research/2026-10-20-coding-teams-and-swarms.md).

## Proposal

- Keep task authority, cumulative budgets, delegation lineage, resource claims,
  and accepted state in the harness rather than in a vendor's conversation.
- Support bounded subtasks, peer collaboration, and scripted graphs behind
  capability-tested adapters. Prefer the smallest topology meeting the task.
- Provide a typed, authorized task memory with immutable evidence and explicit
  proposal/observation/acceptance states. Keep private contexts and global
  project knowledge on their appropriate paths.
- Treat native boards, messages, goal verdicts, and memory as inputs, not grants
  or proof of success. Enforce effects and completion outside model judgment.
- Curate task journals for reuse; integrate code through revision checks,
  trusted validation, and the protected gateway.

## Consequences

See [development teams](../development-teams.md) and [task memory](../task-memory.md).
No schema fields, runtime behavior, or provider certification change in this ADR.
Implementation must version the runtime protocol separately and exercise races,
stale authority, hidden delegation, resume, budget accounting, memory conflicts,
message replay, and integration before advertising these guarantees.

Initial delivery should use a single trusted coordinator, exact task retrieval,
and bounded workers. Add a second different runner to test portability before
larger swarms, semantic retrieval, or more orchestration frameworks. This avoids
mistaking more processes or a larger dependency stack for verified capability.
