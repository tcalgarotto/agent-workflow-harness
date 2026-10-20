# ADR 0001: establish portable contracts before agent orchestration

Status: accepted for the initial prototype

The project spans orchestration, model providers, memory, and enforcement. Building
all integrations first would obscure the contracts and encourage unsupported
compatibility/security claims.

Start with strict JSON Schemas, a local validator, synthetic examples, and negative
tests. Keep provider/framework integrations behind adapters. This makes the first
release independently reviewable without credentials or external infrastructure.

Consequence: the initial release is not a working swarm runtime. Concurrency,
isolation, memory, and integration guarantees require later implementations and
their own acceptance tests.
