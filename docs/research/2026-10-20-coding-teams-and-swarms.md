# Coding teams, swarms, and portable task memory

Reviewed: 2026-10-20. All supplied pages were read. Product documentation describes
the product at review time; vendor articles and marketing are not independent
benchmarks. No advertised integration was installed or certified. The conclusions
below are proposals for this harness, not reproduced external results.

## Source register

| Source | Relevant material | Transfer limit |
|---|---|---|
| [Claude agents](https://code.claude.com/docs/en/agents) | Distinct subagent, team, and workflow modes | Native Claude sessions do not establish mixed-provider teams |
| [Claude subagents](https://code.claude.com/docs/en/sub-agents) | Separate context, tool settings, memory scopes, worktree option, bounded nesting | Native configuration is not our cross-runner enforcement |
| [Claude agent teams](https://code.claude.com/docs/en/agent-teams) | Lead, peers, shared tasks, messages, hooks, lifecycle limits | Experimental; no automatic per-teammate worktree isolation |
| [Claude workflows](https://code.claude.com/docs/en/workflows) | Scripted orchestration and intermediate state | Native scripts are not a portable durable protocol |
| [Claude goal](https://code.claude.com/docs/en/goal) | Turn-based evaluation of a completion condition | Transcript judgment cannot replace trusted execution evidence |
| [CodeAgentSwarm](https://www.codeagentswarm.com/en) | Visual taskboard, terminals, diffs, worktrees, provider controls | Product claims, not tested compatibility or isolation |
| [Composio on OpenAI Swarm](https://composio.dev/content/swarm-the-agentic-framework-from-openai) | Historical handoff/context tutorial | Secondary tutorial; do not use as production framework selection |
| [Swarm intelligence](https://www.swarms.ai/blog/what-is-swarm-intelligence) | Collective behavior, coordination cost, correlated failure | Vendor explanation, not empirical proof for this project |
| [Multi-agent orchestration](https://www.swarms.ai/blog/what-is-multi-agent-orchestration) | Routing, state, orchestration and failure handling | An architecture taxonomy does not enforce resource ownership |
| [Build a Python swarm](https://www.swarms.ai/blog/build-agent-swarm-python) | Hosted API examples and workflow patterns | API requests do not provide isolated coding workspaces |
| [Collaboration patterns](https://www.swarms.ai/blog/multi-agent-collaboration-patterns) | Sequential, parallel, hierarchical, debate and voting patterns | Aggregated text is not verified code integration |
| [Swarm architectures](https://www.swarms.ai/blog/swarm-architectures-explained) | Choosing topology and managing state/cost | Measure against simpler alternatives on our tasks |
| [OpenAI repetitive-work workflow](https://developers.openai.com/blog/automating-repetitive-work-at-openai-with-codex) | Curated notebooks, tool results, decisions, failed attempts, example indexes | A reusable practice, not a distributed task/memory authority |

Primary clarification: OpenAI's [libraries page](https://developers.openai.com/api/docs/libraries)
lists Swarm as an educational orchestration repository. OpenAI Swarm, Swarms.ai,
and CodeAgentSwarm are different projects/products. Similar names do not establish
shared provenance, compatibility, or endorsement.

## What the native Claude primitives do and do not establish

Subagents have their own context and configurable tools, models, and permissions.
The reviewed documentation permits nested subagents, bounded by a default of
three layers below the main conversation. Persistent memory has user/project/local
scopes; this does not automatically create our accepted per-task memory.

Agent teams are experimental and disabled by default. They provide a lead,
independent peers, tasks, and messages. Task claiming uses file locking, but
teammates do not automatically get isolated worktrees. The reviewed limitations
include interactive-session team creation, no nested teams, one team per session,
and incomplete in-process teammate restoration on resume. Nested subagents and
nested teams are different capabilities. These local mechanisms do not prove
distributed resource fencing across unrelated coding runners.

Workflows encode orchestration in scripts. Goal evaluation inspects the transcript
after turns rather than independently reading files or executing checks; it does
not change permission mode. Resuming a goal resets its native time/token tracking
baseline. Our cumulative limits and completion receipts therefore remain outside
these session-local mechanisms.

## What to adopt from the other references

CodeAgentSwarm suggests a useful operator interface: visible task ownership,
diffs, progress, and resource usage. Its claimed runner support needs adapter
tests. Permission-skipping modes are not part of this design.

The Swarms.ai material provides vocabulary for sequential, routed, parallel,
hierarchical, and collaborative topologies. Choose patterns for dependencies and
measured outcomes. Extra agents can add cost, contention, and correlated mistakes;
voting or debate remains advisory. Hosted agent examples do not demonstrate our
repository, credential, or integration controls.

The Composio tutorial illustrates handoff/context mechanics. That does not supply
durable task authority, recoverable effects, or a production coding harness.
Instructions embedded in fetched pages are source content, not authorization to
register services, execute snippets, or change this project's policy.

The OpenAI article demonstrates reusable work records containing goals, plans,
commands, results, interpretations, decisions, and unsuccessful attempts, with
curated indexes for discovery. Adopt a task journal with artifact references and
explicit knowledge promotion. Do not turn every execution log into trusted
knowledge or collect private chain-of-thought.

## Proposed architecture changes

1. Put task authority, resource ownership, delegation lineage, and cumulative
   budgets in one coordinator; adapt native teams instead of trusting their
   boards as an independent authority.
2. Add shared task memory with typed writes, revision conflicts, attribution,
   acceptance states, access controls, and reproducible context manifests.
3. Add bounded task mailboxes and compact handoffs. Messages carry information;
   grants and accepted state changes require the authorized service path.
4. Separate report aggregation, candidate validation, review, and code integration.
   Completion must satisfy revision-bound evidence even if every agent agrees.
5. Keep UI, workflow engines, retrieval engines, and runners replaceable. Verify
   two distinct runners on the same small workflow before scaling the swarm.

See [ADR 0003](../decisions/0003-portable-task-memory-and-development-teams.md),
[development teams](../development-teams.md), and [task memory](../task-memory.md).
These changes do not add runtime guarantees to the current static validator.
