# ADR 0007: Linux execution supervisor and authenticated validation receipts

Status: implemented for M2a. Date: 2026-10-20.

## Problem and acceptance

M1 only grants logical authority. A real worker must be unable to edit another
workspace or protected input, inherit host credentials, open the host control
socket, or keep resources silently after cancellation. Validation must run against
an exact content snapshot with its receipt producer outside candidate control.

## Decision

Implement an optional Linux/Docker supervisor, without a model provider or merge
gateway. The CLI calls the authenticated M1 API as a distinct `supervisor`
identity. SQL migration 002 admits at most one unresolved execution per run,
binds its manifest hash and charges two operation units. Worker credentials
cannot start/end executions. M1 finish/reconciliation require confirmed execution
stop; expired authority is checked freshly before work and throughout execution.

Use a pinned Python image, UID/GID 10001, all capabilities dropped, no new
privileges, default seccomp, private PID/IPC/cgroup/network namespaces, no network
egress, no published ports, read-only root filesystem and bounded cgroup limits.
No project/host directory or Docker socket is bind-mounted. A new private
Docker-managed tmpfs volume holds each workspace, bounded separately from /tmp.
Do not reuse a volume across worker/validator or other runs. The supervisor has
trusted Docker access; the candidate does not.

The initial supported profile uses a rootful daemon and unprivileged container
processes. It is not advertised as a rootless daemon. Rootless mode needs another
conformance profile and is currently rejected; local tmpfs volume mounting and
the required limits must not be silently disabled. Do not alter a user's daemon
configuration to make tests pass. Containers share the host kernel; this is not a
VM boundary or production isolation certification.

Import regular files through directory FDs without following links, with explicit
size/count limits and metadata exclusions. Preserve content/path identity, not
Git metadata, executable bits, ownership or empty directories. During preparation,
root-owned read-only inputs and ancestors prevent out-of-scope writes; permitted
files/directories belong to the non-root worker. Exact-file grants do not grant
parent directory writes or atomic rename. Freeze all processes before bounded
archive capture; never extract candidate tar entries onto the host. Stop and
remove the worker before preparing the independent read-only validation snapshot.

The operator supplies bounded worker/check commands in a trusted immutable
profile. Candidate output cannot choose validation or mark success. The supervisor
authenticates receipts using a private HMAC key and binds the candidate content,
accepted M1 contract, profile, actual image/engine, exact commands, results and
bounded output hashes. Receipt authentication is not evidence of business
correctness, current merge authority or a sound arbitrary test oracle.

Persist operation intent before admission/create, deterministic container/volume
names and state after transitions. Cooperative cancel and M1 revocation stop the
container; only observed stopped state permits a completion attestation. A control
failure quarantines the execution. Recovery stops matching orphan objects and
records termination without replaying candidate code. Database admission remains
the task authority; the private local journal records execution/recovery facts.

## Validation and limits

Real PostgreSQL/Docker tests cover separate simultaneous workspaces, shared port
numbers without shared network namespaces, protected files, scope boundaries,
host-secret/socket absence, cgroup limits/forking/OOM, timeout and descendant
termination, cancel/revoke, output floods, untrusted archives, snapshot tampering,
readonly validation, duplicate admission, unconfirmed stop and restart recovery.
An offline migration test upgrades the exact 001 schema without losing a task.
CI runs the supervisor suite on Python 3.11/3.14 and fails when controls are absent.

No automatic Git integration, external-effect gateway, runner/provider conformance,
semantic proof, shared RAG or multi-host supervisor failover is introduced.
M2b must verify current authority, actual candidate/base, scope and required
receipts at integration. See the [M2a guide](../m2a-supervisor.md).
