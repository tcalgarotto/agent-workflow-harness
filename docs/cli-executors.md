# Headless CLI profiles (M3 in progress)

M3 uses five local CLI profiles: three separately authenticated Codex CLI
profiles, one Antigravity CLI (`agy`), and one Claude Code CLI. The checked-in
[example](../examples/executors/profiles.example.json) contains profile IDs and
executable names only. Copy it to an operator-managed private file before
adding machine-specific settings. Never commit CLI auth files, account metadata,
or personal home-directory paths.

The three Codex processes must use distinct `CODEX_HOME` directories. Set the
following environment variables to the already-authenticated directories before
running the profile check:

```sh
export AWH_CODEX_HOME_EMPLOYEE_1="/private/path/to/codex-home-1"
export AWH_CODEX_HOME_EMPLOYEE_2="/private/path/to/codex-home-2"
export AWH_CODEX_HOME_EMPLOYEE_3="/private/path/to/codex-home-3"
awh profiles check --config /private/path/to/cli-profiles.json
```

The checker invokes each configured executable with `--version` only. It checks
that the three Codex home paths exist and resolve to different directories. It
does **not** open auth files, verify login state, start an agent, or send a
provider request. The JSON result deliberately omits local paths. A green result
means only that the five local executables respond with recognizable versions
and the three Codex home directories are configured distinctly.

The current headless entry points differ: Codex provides `codex exec` (with JSONL
events), Claude Code provides `claude --print` (with stream-json output), and
Antigravity's installed CLI is `agy --print` (also with stream-json output).
Their event formats, resume IDs, tool permissions, cancellation behavior, and
auth selection are not interchangeable. AWH has not yet implemented these
launchers or verified authenticated sessions.

Do not use a CLI profile to edit the shared checkout. The M2a container does not
have provider network access or credentials, and the current CLI profile check
does not provide a runner. Before code-writing sessions, M3 must add a
task-scoped CLI execution boundary with constrained provider egress and route
candidate commands/builds/tests through M2a. All resulting changes still need
trusted validation and M2b protected integration. See
[ADR 0009](decisions/0009-headless-cli-executors.md).
