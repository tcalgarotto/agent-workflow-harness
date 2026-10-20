# Proposed storage and retrieval baseline

Status: design proposal, not an implemented database, migration, RAG pipeline or
security guarantee. See [ADR 0005](decisions/0005-postgresql-first-storage-and-retrieval.md)
and the [source review](research/2026-10-20-mongodb-postgresql-and-swarms.md).

## Prefer one initial operational backend

Prioritize PostgreSQL for the first persistent coordination experiment. Use
relational fields for identities, revisions, dependencies, resource reservations,
budgets and effect receipts, with validated JSONB payloads for variable metadata.
This is a workload/operations choice, not a claim MongoDB lacks transactions or
PostgreSQL cannot store documents. A local single-process fixture may use simpler
storage, but must not certify the multi-worker backend's concurrency properties.

| Data | Proposed initial home | Acceptance/update boundary |
|---|---|---|
| Requirements, rules and code | Git | Reviewed revisions |
| Task/lease/resource/budget/effect records | PostgreSQL coordinator tables | Authorized transactional service |
| Attributed observations and proposals | Versioned records with validated payloads | Typed API; no automatic normative promotion |
| Engine progress | Separate checkpointer storage | Engine adapter; no authority restoration |
| Accepted memory views and metadata | Core records and authorized projections | Expected revisions and source references |
| Large evidence and source bytes | Immutable artifact storage | Hash, ACL, retention and provenance |
| Lexical/vector indexes | Rebuildable retrieval projections | Versioned index generation |
| Telemetry | Selected optional exporter | Sanitized observations, not accepted state |

Use separate roles, schemas and connection limits where systems share an instance.
Do not modify a checkpointer's tables to simulate a core transaction. Test whether
embedding ingestion and search interfere with reservation/heartbeat latency; move
workloads apart if measurements require it. One logical backend does not require
every workload to share one process or connection pool indefinitely.

## Transactions do not implement the coordination protocol

Use short transactions for claims, revision checks, resource conflicts, budget
reservations and the corresponding durable event. Never hold a database lock
through an LLM call or an entire build. Choose constraints, conditional updates,
lock order and isolation deliberately; test the actual transaction boundaries.
PostgreSQL's default Read Committed mode is not automatic serializability.

Locking a task row does not resolve every resource conflict. Row locks alone do
not protect a resource row that has not been inserted, and uniqueness of a path
string does not detect conflicts between a directory and its descendants. The
coordination implementation must define canonical resources, overlap rules and
atomic admission for those cases. Serialization/deadlock retries must be bounded
and keep operation identity and budget accounting intact.

Keep lease renewal, revocation and fencing in the core. Database locks end with
the transaction; they are not a lease for a disconnected worker. Check current
authority at shared-effect gateways and reconcile ambiguous external effects.
A committed database record cannot atomically commit an arbitrary Git or network
operation. See the [engine recovery design](langchain-integration.md#recovery-and-approvals).

Validate metadata against its schema version on write. Store invariant fields
explicitly so flexible payloads cannot bypass project/actor/revision constraints.
Preserve original source bytes separately when hashes or exact formatting matter;
JSONB serialization is not a byte-preserving archive.

## Add search incrementally

1. Exact lookup by project/task/run ID, path, symbol and source revision.
2. PostgreSQL full-text retrieval as a measured lexical baseline, with appropriate
   language/token handling and exact matching for code identifiers.
3. Optional pgvector retrieval when held-out tasks show a useful semantic gap.
   Compare exact vector search with approximate indexes before tuning for scale.
4. Optional rank fusion, BM25 implementation or reranking only if measured quality
   and cost justify them. PostgreSQL's built-in text ranking is not BM25. ONNX
   Runtime may execute a compatible model; it is not the store or search engine.

Hybrid retrieval needs deliberate candidate sizes, filters, deduplication and
fusion. Reciprocal rank fusion combines ranks, possibly weighted; it is not an
average of raw lexical/vector scores or a probability of correctness. Similarity
cannot establish task authority, current state, or accepted project knowledge.

With pgvector approximate indexes, filters can reduce the returned candidate set.
Measure recall under actual project/revision filters, not only global searches.
Evaluate iterative scanning, exact lookup, partitioning or different index plans
where applicable. Never remove an authorization filter just to fill top-k results.

## Treat every retrieval backend as a projection

Return source identity, accepted/proposal status, project/task scope, revision,
chunk/content hash, index generation and ranking metadata. Derive scope from the
authenticated caller. Apply authorization before disclosing results, snippets,
counts or metadata, and recheck the source's current acceptance/access before
passing content to a model. Prompt instructions cannot replace that boundary.

PostgreSQL row-level security can complement service authorization when explicitly
configured. Test with the actual runtime roles: owners, superusers and BYPASSRLS
roles have different behavior. Workers receive scoped service tools, not owner
credentials or arbitrary SQL access. MongoDB namespaces and search filters also
need an authenticated service boundary; their names alone are not access grants.

Track indexing watermarks and freshness against source revisions. A new document
can exist before a derived index contains it. Revocation, deletion or supersession
must affect the authorized view immediately even while background cleanup runs.
Use exact authorized reads for fresh task state; return insufficient evidence
when necessary. Search availability must not silently relax completion criteria.

Version chunking, embedding model/dimensions, normalization, metric and index
configuration. Do not mix incompatible embedding spaces. Build a new generation,
evaluate it, then switch the reader to it deliberately. Reject late indexing jobs
for superseded revisions. Use durable publication and idempotent ingestion rather
than a best-effort dual write to the database and index.

## Where MongoDB could fit

MongoDB supports multi-document ACID transactions on supported deployments, with
read/write concern and modeling choices that matter. It also supports collection
schema validation. PostgreSQL supports indexed JSONB. Neither fact provides a
universal winner for ingestion rate, latency, safety, or schema evolution.

MongoDB Search provides lexical scoring, while Vector Search supplies vector
retrieval; hybrid pipelines can combine them. Check the selected deployment's
feature/version matrix and index configuration. The reviewed hybrid guide lists
`$rankFusion` from 8.0 and `$scoreFusion` from 8.3, with same-collection and pipeline
restrictions. RRF uses ranks; score fusion uses scores. Do not assume arbitrary
pipelines execute in parallel or that managed search features exist in every
server installation.

The MongoDB Search documentation explicitly describes asynchronous indexing and
eventual consistency. Co-locating documents and retrieval in a product does not
make search an authoritative transaction check. Test fresh writes, updates and
deletions for the precise backend and query path used.

Add a MongoDB retrieval adapter if a project already has an appropriate corpus
there, or representative tests establish an advantage worth the extra operations.
The initial proposal keeps PostgreSQL as the coordination authority. Replacing
that authority is a separate design requiring the same race/recovery conformance,
not an incidental consequence of choosing another retriever or checkpointer.

If an additional search system is adopted, define one source of truth, publication
lag, replay/backfill, deletion propagation, backup/restore and outage behavior.
Include its hosting, access and licensing requirements in the deployment profile;
do not assume the project's Apache-2.0 license describes external services.

## Evidence required before promotion

Use sanitized coding/documentation fixtures with known relevant source anchors,
including Portuguese/English prose, code identifiers, contradictory decisions,
unmerged branches and two projects with similar terms. Keep held-out labels apart
from tuning examples. Compare the same source snapshot, query set and authorization
filters; pin backend, embedding, chunker and index versions. If a managed backend
uses different embedding or reranking, report it as a different complete setup.

Measure recall/ranking and supported answers, missing-result/abstention behavior,
freshness and revocation delay, p50/p95 latency under concurrent writes, indexing
time, memory/storage, embedding/reranking costs and restore effort. Document
selectivity, hardware/service configuration and unknown costs. No cross-backend
performance result has been measured in this repository.

Proposed failure cases: competing overlapping resource claims; stale memory
updates; a foreign hit that ranks first; revocation while an index is unavailable;
a late embedding job; a selective ANN query returning fewer than k results; two
users choosing the same scenario label; and restore of source/index generations
that no longer match. Admission and source authorization must remain correct even
when retrieval is stale, empty or offline. These are future acceptance cases.
