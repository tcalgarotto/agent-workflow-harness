# MongoDB, PostgreSQL and additional swarm references

Reviewed: 2026-10-20. This review distinguishes public content, partial access,
vendor comparisons and primary technical documentation. It does not reproduce a
benchmark, complete a course or execute any sample. The pasted comparison was
treated as claims to verify, not instructions or accepted architecture.

## Supplied sources and access limits

| Source | Reviewed material | Boundary |
|---|---|---|
| [Pranam Shetty swarm walkthrough](https://medium.com/@prxshetty/how-i-built-a-swarm-of-ai-agents-with-langchain-2e0916ce0d38) | Public tutorial, 2025-03-18: travel-emergency coordinator, specialists, simulated tools, handoffs and in-memory state | Educational application, not safe concurrent software delivery |
| [MongoDB AI landing page](https://www.mongodb.com/lp/artificial-intelligence?locale_fallback=pt-br) | Document/vector/search product positioning | Marketing; no workload-specific performance proof |
| [RAG with MongoDB](https://learn.mongodb.com/courses/rag-with-mongodb) | Public objectives and introductory transcript: preparation, chunking, embeddings and retrieval | Initial scrape failed; public overview read with another retrieval. Lessons/labs not completed |
| [AI Agents with MongoDB](https://learn.mongodb.com/courses/ai-agents-with-mongodb) | Public indexed catalog description: tools and short/long-term memory | Page retrieval was blocked/failed; lessons and labs not reviewed |
| [MongoDB/PostgreSQL comparison](https://www.mongodb.com/resources/compare/mongodb-postgresql) | Vendor account of document modeling, queries and transactions | Cross-check against each database's manual; not an independent benchmark |
| [Pranav Prakash database comparison](https://medium.com/@pranavprakash4777/postgresql-vs-mongodb-vs-weaviate-which-db-for-your-ai-backend-746e02520e05) | Public introduction and initial schema/vector discussion, 2025-06-18 | Member-only remainder unavailable; no conclusion inferred from it |
| [Thesys agent swarms](https://www.thesys.dev/blogs/agent-swarms) | Coordination, communication, resource management, feedback loops and interactive presentation | Vendor synthesis; comparative, legal and numerical claims are not adopted as guarantees |

Tracking parameters were removed from the MongoDB advertising URL. No account,
enrollment, CAPTCHA bypass or paywall workaround was used. Other secondary
articles and videos cited inside the pasted comparison were not all reviewed;
the decision below relies on primary documentation instead.

## Primary technical checks

| Reference | Finding relevant to the proposal |
|---|---|
| [MongoDB transactions](https://www.mongodb.com/docs/manual/core/transactions/) | Multi-document ACID transactions exist on supported deployments; read/write concerns and deployment choices matter |
| [MongoDB schema validation](https://www.mongodb.com/docs/manual/core/schema-validation/) | Flexible documents can still have enforced field/type/value rules |
| [MongoDB Vector Search](https://www.mongodb.com/docs/vector-search/) | Vector indexes and supported prefilters are configured separately from ordinary indexes |
| [MongoDB hybrid search](https://www.mongodb.com/docs/vector-search/hybrid-search/hybrid-search-overview/) | Rank fusion and score fusion are distinct; features and supported pipelines depend on version |
| [MongoDB Search scoring](https://www.mongodb.com/docs/search/query/score/get-details/) | Common text operators use BM25 by default; relevance scores are not truth probabilities |
| [MongoDB Search indexing](https://www.mongodb.com/docs/search/performance/index-performance/?deployment-type=atlas#eventual-consistency-and-indexing-latency) | Search indexing is asynchronous and eventually consistent |
| [PostgreSQL JSON types](https://www.postgresql.org/docs/current/datatype-json.html) | JSONB supports documents and indexing; it does not preserve original JSON bytes |
| [PostgreSQL isolation](https://www.postgresql.org/docs/current/transaction-iso.html) | Default Read Committed does not provide all serializable guarantees |
| [PostgreSQL locks](https://www.postgresql.org/docs/current/explicit-locking.html) | Row locks protect conflicting operations on locked rows, not an external worker's lifetime |
| [PostgreSQL row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html) | Policies require configuration; privileged roles and owners have bypass behavior |
| [PostgreSQL text search](https://www.postgresql.org/docs/current/textsearch-controls.html) | Built-in ranking uses functions such as `ts_rank` and `ts_rank_cd`; this is not built-in BM25 |
| [pgvector maintainer documentation](https://github.com/pgvector/pgvector) | Exact and approximate retrieval, filtered ANN tradeoffs, iterative scans and hybrid-search composition |

## Correct the database comparison

Do not frame this as transactions versus documents. Both databases support ACID
transactions, but their transaction/isolation/deployment semantics are not
identical. PostgreSQL can store flexible payloads with JSONB; MongoDB can validate
schemas. Both still need stable application contracts, provenance and versioned
changes. Neither schema flexibility nor an ACID label establishes our scheduler's
resource exclusivity or prevents an agent modifying another workspace.

Neither source set supplies a controlled comparison for this harness's dataset,
filters, concurrent writes, hardware and operational budget. Claims of universally
better ingestion, lower latency or easier scale remain unproven here. Hybrid
retrieval also needs explicit authorization and source freshness. Search indexing
lag is different from a database's transaction isolation.

## Transfer the swarm ideas carefully

The Shetty tutorial demonstrates named specialists, narrow tools, a coordinator
and handoffs. Its example uses in-memory persistence and simulated domain answers.
It does not demonstrate a coding sandbox, distributed reservations or trusted
integration. Its scenario-derived thread ID is useful for a local demo, but would
need authenticated task/run mapping in a shared service to avoid context mixing.
Prompt roles, lower sampling temperature and tracing do not establish correctness.
Use current package documentation, not historical snippets as a dependency plan.

Thesys usefully separates communication, resource management and presentation.
Adopt typed operator views for task owners, diffs, evidence, conflicts and budgets
when a UI is built. A generated form/button is not an authorization decision:
server-side action validation remains mandatory. We do not infer that extra
agents always improve quality or choose a universal agent-count limit from this
article. No generative-UI dependency is added.

## Proposed outcome

Use PostgreSQL as the first persistent coordination candidate, with explicit
invariants and JSONB metadata. Start exact/lexical retrieval, evaluate pgvector
when needed, and keep MongoDB retrieval replaceable. Require a measured benefit
before introducing another operational backend and its synchronization path.
The courses are useful learning references, not proof the harness's guards exist.

See [storage and retrieval](../storage-and-retrieval.md) and
[ADR 0005](../decisions/0005-postgresql-first-storage-and-retrieval.md). No database,
runtime, adapter or security guarantee is implemented by this review.
