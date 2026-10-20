# ADR 0008 — Protected local Git integration

Status: implemented for the bounded local M2a profile.

## Problem

A successful candidate check is historical evidence. It does not authorize a
shared change, prove its compatibility with a newer base or safely settle task
state after a partially observed Git effect.

## Decision

Use an operator-configured, project-bound, immutable integration policy and a
separate integrator identity. Authenticate the M2a receipt, compare its manifest
and content with the accepted contract, live grant and coordinator execution row,
and match its full input to an immutable accepted Git ancestor. Merge file deltas
optimistically, preserve unrelated accepted changes and reject conflicts. Run the
operator's isolated validator again on the exact combined content.

Use a private local bare repository, Git plumbing, fixed operator identity and
sanitized environment. Do not checkout candidate code, run hooks/filters, expose
host credentials or push to remote hosting. Preserve existing regular-file modes;
reject Git trees the content snapshot cannot faithfully represent.

Checks/policy paths require a distinct controller's recorded approval bound to
policy, candidate receipt and current base. The fixed validator uses Python
`-I -S -c`; projects must protect all files that influence its oracle. Exact path
protection is enforceable; universal semantic detection of weakened checks is not.

After confirming validator stop, recheck live authority under the project lock
and commit a durable SQL permit containing exact expected/new OIDs. This is the
authorization linearization point. Fence cancellation, expiration and resource
release until the external effect is reconciled. Never perform Git/network work
while holding the SQL transaction. Integrate with Git compare-and-swap; record
the operation ref and settle task, budget, reservations and outbox transactionally.

The Git files backend and SQL do not provide a distributed atomic commit. An
operation ref or the planned immutable commit in accepted ancestry proves a
successful effect, with its exact parent checked. This also covers a host crash
between individual ref publication steps. A marker inconsistent with accepted
ancestry fails closed. Recovery never reruns code or repeats the merge.

## Consequences

Registered projects cannot complete through manual M1 `finish`/`decide complete`.
Non-governed M1 projects retain their attestation path. M1 must be upgraded on
every process before using migration 003; older processes do not know the fence.

The pilot remains single-host, bounded and provider-independent. A prepared permit
is intentionally not instantly revocable: holding ambiguous work is safer than
releasing it while an authorized effect may exist. Operators must recover pending
operations. Remote GitHub publication, multi-host effect enforcement, automated
rollback, richer Git trees, arbitrary builds and real AI adapters remain separate
milestones. See the [operating guide](../m2b-integration.md) for commands and limits.
