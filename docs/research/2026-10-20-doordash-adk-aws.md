# DoorDash, ADK, and AWS: implications for the harness

Reviewed: 2026-10-20. This is a source-based design proposal, not a reproduced
benchmark, implemented adapter, or assurance about another company's systems.
See [ADR 0002](../decisions/0002-evidence-grounding-and-evaluation.md) and the
[proposed evaluation design](../evaluation.md).

## Sources and boundaries

| Reference | Reviewed material | Boundary |
|---|---|---|
| [Mercado de TI](https://mercadodeti.com.br/public/inteligencia-artificial/doordash-usa-agentes-de-ia-limpar-60-mil-feature-flags-gera-prs-138-minutos) | Secondary article and its original source link | Verify claims against the engineering article |
| [DoorDash flag cleanup](https://careersatdoordash.com/blog/automating-feature-flag-cleanup-at-scale-with-a-multi-agent-llm-system/) | Engineering account, 2026-08-24 | Narrow maintenance task and a reported sample |
| [ADK getting started](https://adk.dev/get-started/) and [overview](https://adk.dev/get-started/about/) | Agent/workflow primitives, tools, state, artifacts, evaluation | Framework capabilities do not establish our enforcement guarantees |
| [AWS contact-center case study](https://aws.amazon.com/pt/solutions/case-studies/doordash-bedrock-case-study/) | RAG, response evaluation, and reference diagrams | Customer support, not code integration |
| [DoorDash Portuguese index](https://careersatdoordash.com/pt/?search=data) | Discovery of related engineering posts | Changing index, not a fixed dataset or proof of search scope |
| [Triton auto-tuner](https://careersatdoordash.com/blog/triton-auto-tuner-finding-the-right-triton-configuration-for-hundreds-of-models/) | Serving configuration measurement, 2026-09-21 | CPU inference, not coding-agent throughput |
| [Ask DoorDash evaluation](https://careersatdoordash.com/blog/building-ask-doordash-part-three-evaluation/) | Rubrics, fixtures, execution evidence, judge calibration | An evaluation approach, not an infallible judge |
| [Ask DoorDash platform](https://careersatdoordash.com/blog/building-ask-doordash-part-four-a-platform-for-building_and_evolving_agents/) | Shared services, scoped skills, deterministic tool validation | Transfer principles, not the full stack |
| [Ask DoorDash memory](https://careersatdoordash.com/blog/building-ask-doordash-part-two-intelligence/) | Task-aware access and distinct memory lifetimes | Preferences are not approved engineering requirements |
| [ADK evaluation criteria](https://adk.dev/evaluate/criteria/) | Tool trajectories, response quality, groundedness, efficiency | Exact sequence matching is not universal |

## Interpret the evidence correctly

The flag-cleanup account describes a platform with more than 60,000 flags, not a
completed cleanup of all flags. It reports 45 usable PRs among 50 recent cases,
averaging 13.8 minutes and USD 4.79 per cleanup: 31 first-attempt merges, 14
revisions, and five engineer interventions. The reported absence of observed
regressions in that sample is not a general correctness guarantee. The system
reads current rollout metadata before target behavior is confirmed, then edits
in separate worktrees with validation.

The AWS case reports reference-based semantic evaluation and increased automated
testing capacity. Its diagrams distinguish generation, retrieval, testing, and
asynchronous monitoring. These are useful boundaries, not a requirement to deploy
every pictured service. The supplied reference images were reviewed; none are
reproduced in the repository.

ADK documents deterministic workflow controllers alongside LLM agents, callbacks,
sessions, memory, artifacts, and evaluation. It is an orchestration candidate,
not a replacement for project authorization or OS isolation.

Triton tuning measures complete configurations under controlled workloads and
selects candidates meeting constraints. More allocated compute does not alone
guarantee throughput. Its gains cannot be reused as coding-workflow predictions.

Ask DoorDash's evaluation approach assesses both results and tool behavior,
prepares evidence for rubric items, and calibrates judges using human labels and
fixed-data simulation. Its platform separates common services from domain-owned
behavior, scopes skills, and validates tool operations outside prompts. Its memory
design routes retrieval according to the task and distinguishes durable and
current context. Engineering requirements additionally need an acceptance path.

## Our proposed changes

These are engineering proposals for this project, not additional external results.

1. **Evidence before writes:** identify accepted requirements, source revisions,
   relevant external observations, intended behavior, and unresolved decisions.
   A discovery source is not necessarily an authority for mutation. Revalidate
   the relevant preconditions at the effect boundary.
2. **Two evaluation layers:** verify operating invariants independently of
   semantic success. A plausible diff cannot excuse expired authority; correct
   tool usage cannot excuse the wrong behavior.
3. **Replayable scenarios:** freeze synthetic repository snapshots, tool responses,
   external state, and expected effects. Compare configurations without real
   shared mutations or customer data.
4. **Completeness and hidden shared state:** check required remaining references,
   call sites, and tests. Isolate build daemons, caches, databases, ports, and
   process state beyond the Git checkout.
5. **Scoped procedural context:** load relevant approved procedures and mandatory
   policy. Cache stable maps by revision and invalidate on changes; never treat
   a cached permission as permanent authority.
6. **Measured executor capacity:** evaluate worker count with nested build/test
   parallelism, provider limits, and validation capacity. Add backpressure before
   increasing swarm size.
7. **Engine-neutral comparison:** compare ADK and LangGraph integrations using
   identical run contracts and fixtures. External success is not our conformance
   result, and engine choice must not create another task authority.

Do not copy a case's model choices, coverage threshold, concurrency, timeout, or
thread settings into universal defaults. A worktree is also not a security
boundary for an untrusted process.

## Implementation order

Define evidence and operational/behavior fixtures alongside the coordination and
isolation milestones. Add trace-to-evidence reconstruction and one real runner.
Only then compare providers or engines and tune retrieval/pool configurations.

The current CLI still validates declarations only. No runtime, judge, RAG,
sandbox, or certified framework support is added by this research. No raw scraped
pages, third-party code, customer payloads, or diagrams are committed.
