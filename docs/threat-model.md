# Threat model and boundaries

## Current prototype

The local user controls the contracts and input paths. The checker validates their
consistency. It cannot stop that user from changing the policy, bypassing the CLI,
lying about adapter capabilities, or editing another file. Do not expose it as an
authorization endpoint without a separate authenticated service and resource limits.

## Intended runtime controls

| Threat | Required boundary |
|---|---|
| Competing claims or stale worker | Transactional reservations and fenced effect gateways |
| Cross-project memory access | Server-derived authorization and isolated caches/index filters |
| Agent edits another workspace | OS/container write isolation, not prompts alone |
| Malicious instruction in retrieved content | Treat source as data; policy remains outside the LLM |
| Forged test result | Trusted runner receipt bound to immutable code/environment |
| Agent weakens acceptance checks | Protected contracts and independent review |
| Repeated ambiguous side effect | Destination idempotency or explicit reconciliation |
| Secret leakage | Scoped integration services and redacted telemetry |

The runtime must not grant workers host Docker sockets, unrestricted integration
credentials, or direct protected-branch writes while claiming enforced isolation.
No zero-hallucination or universal cancellation guarantee is possible.

## Implemented local effect boundary

[M2b](m2b-integration.md) protects a gateway-owned private bare Git repository.
Its immutable policy, registered authenticated receipts, accepted contract/scope,
current grants, protected-check review and exact combined-content validator are
checked before a durable commit permit. Git CAS prevents a stale candidate from
overwriting an accepted advance. Pending permits retain task/resources until Git
and SQL are reconciled, including a successful Git effect with lost SQL completion.
The permit is a point of no return for authorization; subsequent cancellation
waits for reconciliation. Marker-only inconsistent effects remain quarantined.

The trusted host, Docker daemon, local Git configuration, database credentials,
receipt key and operator validation oracle remain trusted. Administrators can
bypass these controls; candidate containers do not receive that access. Integrity
checks cannot detect every semantic weakening of a test through arbitrary source
changes. Protect all oracle inputs and use independent review. Remote Git hosting,
untrusted host shells, cross-host failover and arbitrary external effects are not
covered by this local boundary.
