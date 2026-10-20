# ADR 0006: local PostgreSQL coordination before agent execution

Status: implemented for M1, subject to review. Date: 2026-10-20.

## Problem and behavior

The static v1 validator cannot grant live task ownership. Two processes may race
for overlapping resources, retry a lost response or resume after a worker dies.
M1 must admit at most one incompatible owner, reject stale revisions/leases and
retain cumulative budgets across runs. It does not execute the worker or effects.

## Decision

Add optional FastAPI/Pydantic and Psycopg dependencies, a versioned `awh_m1`
schema and a separate CLI. Keep v1 bundle validation and installation independent.
Use explicit migrations with transaction-scoped migration locking and checksum
verification. The server never auto-migrates.

An operator assigns token digests, subjects, roles, project grants and declared
capabilities at startup. Only loopback bind is supported by the CLI. This is an
initial local deployment boundary; no SaaS identity provider is implied.

Serialize short mutations with the project row lock under READ COMMITTED. Read
current rows after acquiring the lock, including hierarchical resource overlaps,
queue eligibility, slot and budget admission. This trades per-project throughput
for a small, reviewable consistency model; work itself stays outside transactions.

Accepted contracts are immutable and hashed. Distinguish state CAS revision from
accepted contract revision. Project-monotonic fences and database-clock leases
bound coordinator authority. Expiration/cancel retain reservations and slots
until an explicit controller reconciliation; uncertainty is not absence of work.

Reserve integer operation units at claim; charge before a permitted operation;
release unused units on graceful submission and conservatively burn unused units
after lost authority. Store cumulative task/project totals plus attributed ledger
entries. No implication of enforcing external model charges or child budgets.

Persist idempotency receipt, state changes and outbox together. Identical retries
return historical receipts, not renewed grants. Outbox polling is cursor-based
and requires consumer deduplication; no exactly-once broker claim.

Allow trusted controller attestations for acceptance, reconciliation and final
task disposition in this pilot. These are not validated receipts or automated
integration gates. The worker cannot complete its own task. M2 must implement
actual isolation, trusted validation and integration before governed execution.

## Validation and limits

Real PostgreSQL tests race independent processes and connections, verify failure
rollback, stale revisions/fences, identity/role/project checks, scope boundaries,
expiration quarantine, conservative settlement, retry/restart budgets and event
cursor recovery. CI requires the PostgreSQL suite and both supported Python
versions. No SQLite replacement, in-memory authority or synthetic sandbox claim.

No global cross-project resource locks, delegation/mailboxes, RAG, LangGraph,
runner, external effect permits or production security certification are added.
The older blueprint remains a dated target design; this ADR and the
[M1 guide](../m1-coordination.md) describe what now executes.
