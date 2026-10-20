# Proposed task-scoped shared memory

Status: target-runtime design. No database, message service, journal parser, or
retrieval implementation is added by this document. See [memory principles](memory.md).

## A logical workspace for each task

Use one logical namespace per project and task, not a separate physical database
per task or a shared file every worker rewrites. A transactional store holds
operational records; Git and an artifact store hold versioned content. Indexes
are rebuildable, permission-filtered projections.

| Record | Authority and write path |
|---|---|
| Task contract snapshot | Accepted requirements, base revision, scope, criteria, and policy references |
| Decisions | Authorized acceptance with evidence and expected revision |
| Observations | Attributed append-only run records, possibly contradictory or unverified |
| Proposals | Suggested plans, changes, and lessons awaiting applicable acceptance |
| Artifacts | Immutable content hashes and repository/commit references |
| Validation receipts | Authenticated trusted producer, inputs, result, and exact revisions |
| Messages and handoffs | Task-scoped communication; no implicit authorization |
| Journal | Navigable references to actions, results, decisions, failures, and next steps |

All participants see the task information their identity is authorized to access.
Keep project, task, team, and run boundaries distinct. Membership does not imply
access to every project, credential, private note, or hidden evaluator fixture.
Derive identity and ACL filters server-side, including search and cache access.

## Update through typed operations

Proposed operations include reading a snapshot, appending an observation,
submitting a proposal, accepting a decision, and recording a trusted receipt.
These are design concepts, not supported CLI operations or version-1 schema
fields. Accepted mutable records require an expected revision and authorization;
conflicts return competing revisions for reconciliation instead of silently
overwriting another worker's decision. Event delivery may repeat, so operations
also need idempotency keys and durable results.

Store provenance, producer identity, source/evidence references, creation time,
revision, and verification/acceptance status. Keep observation separate from
inference and acceptance. A signed or authenticated producer can still be wrong;
identity establishes attribution, not factual correctness.

## Give each participant a reproducible view

A context manifest binds the task revision, source hashes, authorized artifact
references, index generation, and adapter/procedure/model versions. A handoff
contains the goal, accepted decisions, current candidate, completed checks,
unresolved issues, and exact next action. It is a compact referenced summary,
not an unrestricted transcript dump.

Contract changes must invalidate affected grants and receipts. Update participants
explicitly; do not silently replace the context under an active write. On
restart, reconstruct state from accepted snapshots and events, then obtain fresh
authority before effects. Checkpoints retain progress, not perpetual permissions.

Start retrieval with task IDs, paths, symbols, and exact revisions. Add lexical
and vector discovery only after measuring the baseline. BM25 and optional
embedding/reranking models run behind the same authorization and provenance
rules; ONNX is an optional model execution format/runtime choice. None makes a
stale or unaccepted document authoritative.

## Curate a reusable task journal

Record goal and accepted plan references, commands/tool events and actual results,
concise decisions with evidence, failed attempts and their observed causes,
candidate revisions, validation receipts, and handoff. Do not collect private
chain-of-thought, secrets, or unrestricted terminal logs. Apply access control,
redaction, and retention to sensitive content before indexing or exporting it.

Native agent memory and generated notebook summaries enter as attributed
proposals. Promote reusable project knowledge through its Git review path;
completing one task must not automatically rewrite global rules. A maintainer
can curate a concise index of accepted procedures and examples so later workers
discover relevant work without loading every journal. Check cited artifacts for
continued availability and mark revoked or superseded knowledge.

Retention, deletion, backups, and restore must cover source records, derived
indexes, caches, and artifact references. Operational history must distinguish
redacted/deleted content from a missing event. Keep enough durable metadata to
reconcile effects without retaining unnecessary private data.
