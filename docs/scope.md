# Scope and current guarantees

The current executable validates local JSON documents and their declared
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

No vendor integration has been certified. No deployment, retrieval quality, or
hallucination-rate guarantee is provided.
