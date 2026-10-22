# Local CLI profiles and executor status

The operator currently configures six local CLI profiles: four independent
Codex CLI profiles, one Antigravity CLI (`agy`), and one Claude Code CLI. A
profile identifies an invocation context, not a person or a unique provider
account. Multiple Codex profiles may use the same person's account; each still
has a separate `CODEX_HOME` so local CLI state does not collide.

The checked-in [example](../examples/executors/profiles.example.json) contains
profile IDs, executable names, and environment-variable *names*. Copy it to a
private operator-managed file before adding machine-specific settings. Never
commit CLI auth files, account metadata, or personal home-directory paths.
Authentication remains managed by each CLI through its own local OAuth login.
AWH neither reads nor copies login material and does not claim that profile IDs
prove account identity.

Set four distinct, existing, absolute `CODEX_HOME` paths before checking the
profiles:

```sh
export AWH_CODEX_HOME_1="/private/path/to/codex-home-1"
export AWH_CODEX_HOME_2="/private/path/to/codex-home-2"
export AWH_CODEX_HOME_3="/private/path/to/codex-home-3"
export AWH_CODEX_HOME_4="/private/path/to/codex-home-4"
awh profiles check --config /private/path/to/cli-profiles.json
```

The checker invokes each configured executable with `--version` only. It checks
that all four Codex home paths exist and resolve to different directories. It
does **not** open auth files, verify login state, start an agent, or send a
provider request. The JSON result deliberately omits local paths. A passing
preflight confirms only that the six executables report recognizable versions
and the four Codex home directories are configured distinctly.

## Executor implementation status

The provider-neutral lifecycle contract covers capability discovery,
preparation, start/resume, normalized events, candidate delivery, cancellation
request, and separately confirmed process termination. The Codex adapter
prototype now serializes local stdio JSON-RPC requests and normalizes a limited
event allowlist. It uses Codex app-server methods for long-lived threads, turns,
resume, events, and interruption. `codex exec --json` remains suitable for
bounded one-shot jobs, but does not by itself fulfill AWH's full lifecycle
contract. The protocol helpers are not yet connected to a managed process, and
do not launch a live session. The integration will preserve the
operator-selected `CODEX_HOME` and will not substitute API keys for OAuth login.
OpenAI describes app-server as the client protocol for threads, turns, streamed
events, and approvals; its current CLI labels the command experimental. AWH
therefore pins the exact CLI build and treats every protocol capability as
unverified until that build passes conformance ([app-server reference](https://developers.openai.com/codex/app-server),
[non-interactive CLI reference](https://developers.openai.com/codex/non-interactive-mode)).

The adapter may start only through a task-scoped `AgentProcessBoundary` that
provides independently enforced filesystem and process isolation, provider
egress policy, and a constrained tool/effect gateway. No such network-capable
boundary is implemented yet. The current M2a Docker runner has no provider
network access or credentials and remains the trusted route for candidate
builds/tests. Therefore no code-writing Codex session can be launched by AWH
yet. Local profiles and CLI sandbox flags alone are not an AWH security
boundary. The Codex app-server is version-sensitive; the deployed version must
be pinned and pass conformance before its capabilities are advertised. See
[ADR 0009](decisions/0009-headless-cli-executors.md).

The managed Codex lifecycle manager now requires a task-scoped
`AgentProcessBoundary` receipt bound to the complete run and selected profile.
It rechecks AWH authority before start/resume, rejects mismatched receipts, and
distinguishes an interrupt request from confirmed process termination. Its
tests use a fake boundary; there is no production boundary implementation and
no live session is launched. A conforming boundary must independently enforce
filesystem/process isolation, provider egress controls, and a constrained
tool/effect gateway.
