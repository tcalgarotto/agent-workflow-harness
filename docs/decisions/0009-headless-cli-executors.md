# ADR 0009: headless CLI executors and isolated identity profiles

- Status: accepted for M3 design; implementation and provider conformance pending.
- Date: 2026-10-20.

## Context

The first real execution adapters must use the authenticated CLIs already
available to the team. The initial operator configuration has five independent
profiles: Codex for employee 1, Codex for employee 2, Codex for employee 3,
Antigravity, and Claude Code. This is a set of executor profiles, not a shared
login, a provider API integration, or a claim that every CLI has identical
features.

The local CLIs expose headless invocation modes, but they differ in command
syntax, session IDs, event streams, auth storage, cancellation, and enforcement.
For example, the installed Codex CLI supports `codex exec --json` and an
explicit `CODEX_HOME`; Claude Code supports `--print` and stream-json output;
the installed Antigravity CLI is `agy` and exposes `--print` and stream-json.
These help/version checks establish local command availability only. They do not
prove successful authentication, account identity, safe isolation, or provider
conformance.

M2a's current Docker profile deliberately has no network access and receives no
credentials. Running a network-dependent CLI in that container cannot work as
configured. Running the CLI directly on the host, or granting it the shared
checkout, would bypass the isolation and effect controls expected by this
project. A Git worktree prevents some path collisions but is not a security
boundary.

## Decision

1. Use a provider-neutral AWH executor contract with provider-specific CLI
   adapters. The contract covers capability discovery, task preparation,
   start/resume, normalized events, candidate delivery, cancellation request,
   and separately confirmed process termination.
2. Represent the initial five choices as five named, independently selectable
   profiles. Each Codex profile has a distinct operator-managed `CODEX_HOME`.
   The selected Claude and Antigravity CLI contexts remain independently
   operator-managed. AWH does not copy, inspect, synchronize, or pool login
   material.
3. Store profile names, executable paths, safe invocation options, and auth
   context *references* in private local configuration. Never put tokens,
   auth files, account email addresses, or local home paths in repository files,
   PostgreSQL, task contracts, checkpoints, event payloads, or logs.
4. The coordinator remains the authority for project/task/run identity,
   capabilities, budgets, leases, and delivery acceptance. A CLI's own session
   state is resumable progress only. Every resume and delivery rechecks current
   AWH authority and is idempotently bound to the run, fence, task contract,
   selected profile, and exact candidate content.
5. Do not enable a code-writing headless CLI on a shared host checkout. Before
   real autonomous runs, implement a task-scoped executor boundary with provider
   egress controls and a tool/effect gateway. The CLI may reach only its approved
   provider endpoints and its scoped task tools; candidate commands/builds run
   in the existing isolated M2a runner. If a CLI cannot be constrained to this
   boundary, report that capability as unsupported and fail closed.
6. Preserve provider-specific enforcement claims. CLI flags such as read-only,
   workspace-write, accept-edits, auto, or sandbox modes are reported as
   capabilities, not treated as AWH enforcement until independent tests show
   the actual boundary. Tool calls that bypass the task executor are a
   conformance failure.

## M3 sequence and acceptance

1. Specify the common executor protocol and private profile format; make
   capability reports include tested CLI version, invocation mode, resume
   support, event format, cancellation semantics, identity reference, and
   isolation level.
2. Implement and test the Codex CLI adapter first, then configure the three
   Codex homes as separate profiles. Validate profile selection without
   printing or reading authentication material.
3. Independently verify and add `agy` and Claude Code adapters. Do not infer
   conformance from a common `--print` flag.
4. Add a task-scoped execution boundary and run the conformance suite against
   each provider/profile: stale authority, cross-project denial, file-scope
   confinement, no host credential access, valid/invalid output handling,
   interrupted run, resume, best-effort cancellation versus confirmed stop,
   and recovery after ambiguous termination.
5. Start with synthetic tests and a bounded, operator-approved smoke task in a
   disposable project. Do not invoke live model sessions during ordinary tests.

The M3 milestone is not complete when all five binaries launch. Each provider
profile must pass the relevant independent conformance tests, and unsupported
features must remain explicit. This ADR does not implement LangGraph, shared
memory/RAG, multi-host dispatch, or remote GitHub publication.

## Consequences

- The same employee can be assigned one task at a time per profile unless
  provider concurrency and account policy are independently established.
- Provider-native resume is an optimization. AWH can always refuse resume when
  the task, authority, profile, or workspace binding is stale.
- The first engineering blocker is the network-capable but task-isolated CLI
  execution boundary; direct host execution is not an acceptable shortcut.
- CLI upgrades require versioned conformance reruns. Version strings alone do
  not establish compatibility.
