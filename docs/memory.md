# Memory and retrieval

Keep four kinds of memory separate:

| Kind | Authority and update path |
|---|---|
| Approved knowledge | Git-reviewed requirements, contracts, and decisions |
| Run history | Attributed observations and validation results |
| Operational state | Transactional task/lease/resource records |
| Temporary context | Run-scoped plan, messages, and checkpoints |

An observation is not automatically an accepted fact. Updates to normative
knowledge require evidence, an expected revision, and the relevant review path.
Do not use last-write-wins for conflicting decisions.

Retrieval starts with exact IDs, paths, and contracts. Lexical/vector search can
discover related material, then rank fusion and optional reranking can improve
context selection. PostgreSQL FTS is not BM25. BM25 requires an actual BM25
implementation. ONNX Runtime optionally executes compatible embedding/reranking
models; it is neither memory nor a search engine.

Each context manifest should record project, permissions, base revision, document
hashes, evidence anchors, index generation, and model version. Filter on authorized
project/revision; isolate caches and unmerged branch overlays. Never promote
another run's proposal to accepted policy through search.

Proposed runtime rule: distinguish discovery context from authoritative state for
an action. A historical document or similarity result does not establish a live
setting. Cache approved maps and procedures by revision, but invalidate affected
context when its sources change. Recheck mutable action preconditions rather
than treating a cached observation or permission as permanent authority. See
[evaluation design](evaluation.md#evidence-before-mutation).

RAG cannot guarantee factual correctness. Require traceable sources, distinguish
proposals from observations, expose contradictions, and return insufficient
evidence when appropriate. Search scores are not truth probabilities. Evaluate
retrieval and supported claims on representative held-out tasks.

Current status: design only. No memory server, embeddings, indexes, or RAG calls
are implemented in this repository.

The proposed [task memory design](task-memory.md) defines the logical shared
workspace, typed updates, context snapshots, journals, and knowledge promotion
for cooperating workers. A native agent's persistent memory is an attributed
input, not automatically an accepted project decision.

In a LangGraph integration, checkpointers hold engine progress and stores can
expose cross-thread memory. Neither replaces the core's accepted task records or
Git-reviewed knowledge. Authorize namespace access and resume at the service
boundary; see the [persistence mapping](langchain-integration.md#persistence-and-shared-memory).

The [storage proposal](storage-and-retrieval.md) prioritizes PostgreSQL operational
records with validated JSONB metadata and staged retrieval, while keeping MongoDB
or other retrievers behind an adapter. It adds freshness, revocation, index
generation and filtered-recall requirements; no database is implemented yet.
