# M3 task-scoped Codex boundary (prototype)

This document records the first security primitives for the M3 executor. They
are not yet a production process runner and do not mean that a live agent is
enabled. The managed Codex lifecycle still refuses to start without an
independently supplied and verified `AgentProcessBoundary`.

## Intended run shape

```text
M1 authority check + task fence
        |
        v
private per-run CODEX_HOME ---- selected local OAuth file reference
        |                          (no copy, no credential logging)
        v
Codex app-server in task container ---- only task network
        |                                      |
        |                                       +-- HTTPS CONNECT --> AWH allowlist proxy --> public provider domains
        |                                                               (no TLS termination)
        v
private candidate workspace --> M2a no-network build/test --> M2b reviewed Git effect
```

M2a remains the runner for candidate code, builds and tests. The agent's
network-capable process is a separate boundary. It gets one task network; that
network has no external gateway, and the proxy is the only service connected to
both the task network and the egress network. The proxy allows HTTPS CONNECT to
explicit DNS suffixes, resolves destinations itself, rejects non-public or
mixed private/public DNS answers, and connects to the validated address. TLS
remains end-to-end. Provider domains must be configured by the operator; no
default list silently grants broad internet access.

`prepare_codex_home` creates a private run home, writes a mode-0600 Codex
configuration that selects the named `awh-task` permissions profile, permits
writes under the task workspace, denies the run home and selected source
profile, and disables Codex network access for shell commands. The selected
profile's `auth.json` is referenced by symlink rather than copied. The outer
container boundary must mount only that selected profile at the same absolute
path and expose the run home as `/run/awh/codex-home`; the exact OAuth file must
remain available for the CLI's normal authentication and refresh behavior.
This design reduces credential duplication; it does not make the selected CLI
process itself unable to access its own credential.

The app-server protocol now uses the runtime workspace path attested by the
boundary receipt and does not send a request-level `externalSandbox` override.
The selected Codex permissions profile therefore comes from the isolated
`CODEX_HOME`; the independent outer container remains the security boundary.
The manager still checks current authority before start/resume, validates the
receipt against the host workspace, complete task binding and profile, and
requires confirmed termination before treating a process as stopped.

## Current evidence and limits

- Unit tests cover allowlist parsing, DNS rebinding/private-address rejection,
  task-network topology, per-run Codex home permissions, receipt binding and
  runtime workspace validation.
- In the development environment, Docker's internal isolated-gateway network
  blocked direct external TCP and DNS. The agent could reach an explicitly
  allowlisted HTTPS site through the proxy while a non-allowlisted site was
  denied. This was a manual local infrastructure check, not a CI conformance
  test or provider authentication test.
- The proxy image is pinned by base-image digest and is not pulled implicitly.
- There is not yet a production `AgentProcessBoundary` that creates the task
  workspace, binds the selected profile, starts and streams app-server stdio,
  supervises/reaps the container, records independently measured receipts, or
  cleans up/reconciles crashes. Therefore no managed headless Codex run is
  enabled by this change.
- The outer process runtime must still be reviewed for mount allowlists,
  read-only root filesystem, dropped capabilities, seccomp/AppArmor, cgroups,
  process termination, Docker-daemon trust, and safe cleanup. A proxy policy
  alone is not sufficient isolation.
- Antigravity and Claude adapters, CLI-version conformance, task-specific
  output delivery, and automated live smoke tests remain open.

## Local validation

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m agent_workflow_harness check examples/minimal
```

Optional PostgreSQL and Docker suites are separate and require disposable
infrastructure. Do not run a real provider-authenticated smoke test until the
production boundary is implemented and the run is explicitly bounded.
