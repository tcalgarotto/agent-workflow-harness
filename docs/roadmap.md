# Roadmap

This is a sequence of evidence-based milestones, not a delivery-date promise.

## Foundation — current prototype

- [x] Provider-independent project/policy/task/adapter/workflow contracts.
- [x] Local schema and cross-contract validation.
- [x] Synthetic example, negative tests, and CI definition.
- [x] Scope, trust boundaries, contribution and architecture documentation.

## Local coordination

- [ ] Authenticated service boundary and durable task state machine.
- [ ] Atomic claims, resource conflicts, lease renewal and fencing.
- [ ] Concurrency, expiration, crash, and reconciliation tests.

Exit: two workers cannot obtain incompatible active authority; stale tokens cannot
produce shared effects. A database row alone is insufficient.

## Controlled execution

- [ ] Isolated executor and trusted validation runner.
- [ ] Revision-bound evidence and protected integration gateway.
- [ ] One real adapter passing conformance tests.

Exit: cross-workspace writes fail and changes after verification invalidate receipts.

## Portable workflows and memory

- [ ] Persistent workflow engine adapter and event reconciliation.
- [ ] Knowledge proposals, immutable source revisions, and context manifests.
- [ ] Exact/lexical retrieval baseline before vector/BM25/reranker experiments.
- [ ] Instrumented observability and held-out evaluations.

## Reuse and remote execution

- [ ] Pilot in two unrelated projects and two different runners.
- [ ] PostgreSQL multi-host coordination and worker pool conformance.
- [ ] Backup/restore tests and versioned upgrade guidance.

Do not advertise universal agent compatibility or production isolation before the
corresponding tests and implementations exist.
