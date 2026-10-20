# ADR 0005: PostgreSQL-first storage with replaceable retrieval

Status: proposed

## Context

The harness needs transactional coordination and evidence-backed task memory.
Document storage, vector similarity and task authority have different correctness
requirements. The submitted database comparison overstates both MongoDB's
transaction limitations and PostgreSQL's restriction to structured tables. See
the [source review](../research/2026-10-20-mongodb-postgresql-and-swarms.md).

## Proposal

- Prioritize PostgreSQL for the first persistent coordinator, with explicit
  invariant fields and validated JSONB metadata. Test the actual isolation,
  resource-conflict, revision and recovery protocol.
- Start with exact and lexical retrieval. Add pgvector and fusion/reranking only
  after task-specific measurements justify them.
- Keep accepted source records, engine checkpoints, artifacts and search indexes
  distinct. Revalidate authorization and freshness independent of search scores.
- Keep a retrieval adapter boundary for MongoDB or another backend. Add another
  operational system only for a demonstrated project need or measured benefit.
- Treat the MongoDB coordination backend as a separate conformance effort if ever
  selected; do not infer it from a model/vector/checkpointer integration.

## Consequences

See the [storage design](../storage-and-retrieval.md). The proposal reduces initial
operational surface but does not guarantee best retrieval performance or prevent
errors by itself. Query tuning and workload separation may still be needed.
Neither database eliminates schema contracts, migration planning or scoped access.

No database, migration, extension, benchmark, adapter or new schema field is added
by this ADR. Production selection requires concurrency, isolation, retrieval,
failure and restore evidence on pinned versions. This does not change the current
validator's guarantees.
