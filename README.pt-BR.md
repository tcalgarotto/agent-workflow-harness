# Agent Workflow Harness

Contratos portáteis e validação prévia para desenvolvimento assistido por IA.

O objetivo é reutilizar tarefas, políticas, memória versionada e critérios de
entrega entre projetos e ferramentas, com isolamento e verificação fora dos prompts.

## Estado atual

Este primeiro protótipo contém contratos JSON, um validador executável, exemplos e
testes. Ainda não executa agentes, não oferece sandbox, servidor de tarefas, RAG ou
integrações com fornecedores. As declarações de capacidade são verificadas quanto
à consistência; seu cumprimento real ainda depende de testes futuros dos runners.

## Executar

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/awh check examples/minimal
.venv/bin/python -m unittest discover -s tests -v
```

Consulte o [README principal](README.md), a [arquitetura](docs/architecture.md), o
[roadmap](docs/roadmap.md) e as [regras de contribuição](CONTRIBUTING.md).

As propostas de evolução incluem [times de desenvolvimento](docs/development-teams.md),
[memória compartilhada por tarefa](docs/task-memory.md) e
[evidências e avaliação](docs/evaluation.md). O
[estudo sobre times e enxames](docs/research/2026-10-20-coding-teams-and-swarms.md)
registra as fontes e seus limites. São propostas; o protótipo ainda não executa
esses mecanismos.

A [proposta para o ecossistema LangChain](docs/langchain-integration.md) prioriza
um experimento com LangGraph, componentes selecionados de LangChain, trabalhadores
Deep Agents opcionais e observabilidade substituível. O
[estudo das fontes](docs/research/2026-10-20-langchain-ecosystem.md) registra as
responsabilidades, limitações e critérios antes da implementação.

A [proposta de armazenamento e busca](docs/storage-and-retrieval.md) prioriza
PostgreSQL para coordenação, recuperação por etapas e adaptadores opcionais.
O [estudo de bancos e enxames](docs/research/2026-10-20-mongodb-postgresql-and-swarms.md)
registra correções técnicas, limites de acesso às fontes e critérios de avaliação.

Licença Apache-2.0. Nenhuma ferramenta elimina todos os erros de modelos;
permissões, evidências e validações precisam existir fora do LLM.
