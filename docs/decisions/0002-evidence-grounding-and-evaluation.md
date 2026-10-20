# ADR 0002: ground intended behavior and evaluate actions and outcomes

Status: proposed

## Context

Static contracts cannot establish current application state, whether a change
preserves intended behavior, or whether declared validation steps actually ran.
Repository content may omit live facts. A convincing final answer can conceal
unauthorized actions or incomplete work. See the [source review](../research/2026-10-20-doordash-adk-aws.md).

## Proposal

- Separate read-only investigation from authorized mutation. Bind intended
  behavior and relevant evidence to the run before granting write authority.
- Recheck mutable preconditions at effect boundaries. Route unresolved ambiguity
  to its decision maker; reuse prior authorization only within its valid scope.
- Separate operational invariants from semantic rubrics. A favorable model-judge
  score cannot waive a deterministic gate.
- Compare baseline and candidate on versioned fixtures with observable evidence.
  Preserve held-out cases and judge calibration.
- Keep engines, evaluators, providers, and telemetry behind interfaces. Do not
  create another authority for task state or accepted knowledge.

## Consequences

The target runtime needs evidence manifests, fixture services, trusted events,
and revision-bound validation receipts. See [evaluation design](../evaluation.md).
This proposal does not change schema version 1 or extend the current CLI. A real
runtime contract/schema change requires a separate implementation and review.

Acceptance must demonstrate refusal of stale/missing evidence, a verified result
for a known task, and rejection of unsafe operations even if a semantic evaluator
approves the final answer. No engine/model is selected by this ADR.
