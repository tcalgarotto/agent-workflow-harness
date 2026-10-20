# Scope and current guarantees

The `awh` executable validates local JSON documents and their declared
relationships. It performs no model, subprocess, Git, network, database, or
credential operations. CLI paths are supplied by the caller; the validator is not
a file access authorization service.

The checks cover schemas, project/contract references, budgets, declared adapter
capabilities, canonical lexical path scopes, dependency cycles, and the position
of required gates before integration.

Path checks operate on declarations, not a filesystem or Git diff. They do not
resolve symlinks, enforce permissions, prevent renames, or stop an agent editing
another directory. The workflow graph is a static DAG; retries, checkpoints,
dynamic delegation, and live execution are future work. A gate node in JSON is
not proof the gate ran or that its result was accepted.

The Python validator loads packaged schemas without external references. Input
documents are limited to 1 MB and duplicate JSON keys/non-finite numbers are
rejected. The local CLI is not designed as an unauthenticated remote service.

The optional `awh-coordinator` implements the [M1 boundary](m1-coordination.md):
authenticated loopback API, PostgreSQL state, atomic project-local reservations,
database-clock leases and fencing, cumulative operation-unit budgets, revision
checks and transactional outbox. It uses network/database operations explicitly.
Controller decisions are attestations, not verified evidence. The API does not
execute agents, stop processes, enforce filesystem permissions, intercept model
calls or provide a shared-effect gateway. Stale grants are rejected by M1
mutations, not by external systems that have not yet integrated enforcement.

The optional [M2a supervisor](m2a-supervisor.md) runs commands in a tested
Linux/rootful-Docker profile with non-root candidate processes, no host bind
mounts/credentials/control sockets, project-local write scopes, memory/CPU/PID,
time and output bounds, confirmed stop/recovery and private content snapshots.
A separate read-only container runs the operator's validation command. The host
supervisor authenticates exact-input receipts; this does not prove a correct test
oracle or grant integration permission. Rootless/other OS profiles, AI runners
and the external-effect/merge gateway remain unimplemented. No VM boundary or
production isolation certification is claimed.

No vendor integration has been certified. No deployment, retrieval quality, or
hallucination-rate guarantee is provided.
