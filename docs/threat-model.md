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
