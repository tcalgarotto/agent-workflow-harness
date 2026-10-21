# Roadmap

This is a sequence of evidence-based milestones, not a delivery-date promise.

## Foundation — current prototype

- [x] Provider-independent project/policy/task/adapter/workflow contracts.
- [x] Local schema and cross-contract validation.
- [x] Synthetic example, negative tests, and CI definition.
- [x] Scope, trust boundaries, contribution and architecture documentation.

## Local coordination

- [x] Authenticated local service boundary and durable task state machine (M1).
- [x] Atomic project-local claims, resource conflicts, lease renewal and fencing (M1 API).
- [x] PostgreSQL coordinator with tested transactional resource-overlap admission.
- [x] Concurrency, expiration, transaction failure, restart and controller reconciliation tests.
- [x] Local Git effect gateway rejecting stale authority (M2b; other destinations remain open).
- [x] Exact combined-content evidence and revalidation of the accepted Git base (M2b).
- [ ] Delegation lineage, bounded task mailboxes, and cumulative budgets across resume.

Exit: two workers cannot obtain incompatible active authority; stale tokens cannot
produce shared effects. A database row alone is insufficient.

[M1](m1-coordination.md) implements logical grants and explicit controller
attestations. M2b adds the local Git effect boundary; other effects, governed delegation and bounded mailboxes remain
open; this milestone group is not complete end-to-end.

## Controlled execution

- [x] M2a Linux/Docker command executor and separate content-bound validation runner.
- [x] M2a real containment, cancellation/recovery and authenticated receipt tests.
- [x] M2b revision-bound evidence and protected local Git integration gateway.
- [x] M3 five-profile declaration and safe CLI-version/Codex-home preflight;
      this does not authenticate or launch agents.
- [ ] One real headless CLI executor adapter passing conformance tests.
- [ ] Five separately selectable CLI profiles: three isolated Codex homes, one
      Antigravity CLI, and one Claude Code CLI; no shared or pooled credentials.
- [ ] Network-capable agent execution isolated per task and routed through
      AWH-controlled tools/effects; current no-network M2a candidate runner stays
      separate for code/build/test execution.
- [ ] CLI event normalization, resume binding, delivery, and requested-versus-
      confirmed cancellation semantics.
- [ ] Task-specific completeness checks and isolation of hidden build/test state.

Exit: cross-workspace writes fail and changes after verification invalidate receipts.

## Portable workflows and memory

- [ ] Persistent workflow engine adapter and event reconciliation.
- [ ] LangGraph-first experiment with persistent checkpoints, crash/replay tests and bounded fan-out.
- [ ] Knowledge proposals, immutable source revisions, and context manifests.
- [ ] Task-scoped memory with revision conflicts, curated journals, and explicit promotion.
- [ ] Exact/lexical retrieval baseline before vector/BM25/reranker experiments.
- [ ] Source/index generation, revocation and filtered-recall tests before a second retrieval backend.
- [ ] Instrumented observability and held-out evaluations.
- [ ] Opt-in sanitized exporter; evaluate LangSmith against the existing Langfuse candidate.
- [ ] Versioned tool fixtures and action/outcome evaluation before provider tuning.

## Reuse and remote execution

- [ ] Pilot in two unrelated projects and two different runners.
- [ ] Native delegation, goal, memory, and team conformance where supported.
- [ ] PostgreSQL multi-host coordination and worker pool conformance.
- [ ] Backup/restore tests and versioned upgrade guidance.
- [ ] Capacity benchmarks for worker pools, nested builds, and validation queues.

Do not advertise universal agent compatibility or production isolation before the
corresponding tests and implementations exist.

The [evaluation proposal](evaluation.md) adds acceptance scenarios; they are not
implemented tests yet. Compare optional engine/provider adapters only after the
common controls have evidence. See [ADR 0002](decisions/0002-evidence-grounding-and-evaluation.md).
The [team and memory proposal](decisions/0003-portable-task-memory-and-development-teams.md)
adds portability and recovery acceptance criteria without implementing them yet.
The [LangChain integration proposal](langchain-integration.md) assigns ecosystem
components specific jobs and adds engine/memory/export acceptance criteria. It
does not add dependencies or require managed hosting.
The [storage proposal](storage-and-retrieval.md) specifies the initial backend
candidate and promotion criteria, without claiming a cross-database benchmark.
