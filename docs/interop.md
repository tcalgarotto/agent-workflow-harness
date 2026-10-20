# Interoperability and conformance

Models, runners, IDEs, and accounts are different resources. Compatibility belongs
to a runner/version/provider/configuration combination, not a brand name.

Use a short AGENTS.md entry point where supported. Generate or reference native
instruction surfaces only where the selected runner supports them. Cursor rules,
Claude Code instructions, Gemini CLI context, and Codex instructions do not imply
identical hooks or enforcement guarantees. Procedure packs may use Agent Skills
for compatible consumers. MCP can expose tools but does not provide the business
authorization, sandbox, or scheduler by itself.

Proposed adapter operations: describe capabilities, prepare, start/resume, stream
events, request cancellation, collect delivery, and report health. Declare whether
cancellation is confirmed or best-effort; revoking shared-effect authority is a
separate operation.

Conformance must test schema output, effective policy versions, cross-project
access, file isolation, expired reservations, recovery, review separation, and
truthful capability reporting. A model-generated assertion is not a certificate.

Codex, Cursor, Claude, Gemini, Grok, Mistral, and Qwen are possible integration
targets. No adapters for them are implemented or certified here. The example
runner is intentionally synthetic. Do not copy personal login caches, pool
accounts, or assume subscription access is a generic API credential.

## Workflow engines are a separate adapter category

Google ADK documents LLM agents and deterministic workflow controllers with tools,
sessions, artifacts, and evaluation. ADK and LangGraph are candidate orchestration
integrations; neither is implemented here. Compare them using the same project
contracts, permissions, fixtures, and observable outcomes before selecting an
engine. Do not run competing schedulers over the same task authority. A supported
model interface is not equivalent to controlling an authenticated coding runner.
See the [source review](research/2026-10-20-doordash-adk-aws.md).

The [ecosystem integration proposal](langchain-integration.md) prioritizes one
LangGraph engine experiment without removing the engine interface. It separates
LangChain model/tool components, optional Deep Agents worker loops, conversational
swarm handoffs, and LangSmith telemetry. None certifies another layer's authority
or isolation. See the [LangChain source review](research/2026-10-20-langchain-ecosystem.md).

## Native teams and goals are optional capabilities

Report child-spawning visibility, inherited enforcement, message delivery,
native memory scopes, checkpoint semantics, and interactive/headless limitations
for the exact adapter version. Disable ungoverned spawning for controlled writes.
Import native task events and completion verdicts as proposals; preserve the
harness task authority and cumulative budgets across session restarts.

The [team design](development-teams.md) and
[coding-team source review](research/2026-10-20-coding-teams-and-swarms.md) distinguish
Claude's native primitives from a cross-platform protocol. No native feature or
commercial compatibility claim is certified by documenting it here.

References: [AGENTS.md](https://agents.md/),
[Agent Skills](https://agentskills.io/specification),
[MCP](https://modelcontextprotocol.io/specification/2026-07-28),
[Cursor rules](https://cursor.com/docs/rules),
[Claude Code memory](https://code.claude.com/docs/en/memory), and
[Gemini CLI context](https://geminicli.com/docs/cli/gemini-md/).

Engine references: [ADK overview](https://adk.dev/get-started/about/) and
[ADK evaluation criteria](https://adk.dev/evaluate/criteria/).
