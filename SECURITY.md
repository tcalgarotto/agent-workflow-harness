# Security

This repository is an early prototype of contracts and local validation, not a
production isolation boundary. Do not use its validation result to grant an agent
privileged access. It does not authenticate callers, acquire leases, isolate
filesystems, execute workflows, or check that declared capabilities are truthful.

Use the repository's private vulnerability reporting feature if it is available.
Do not publish credentials, exploit details involving real systems, or private
project data in an issue. If private reporting is unavailable, open an issue asking
for a private reporting channel without disclosing sensitive details.

Only the current main branch is maintained during this prototype phase.
See docs/threat-model.md for trust boundaries and future enforcement work.
