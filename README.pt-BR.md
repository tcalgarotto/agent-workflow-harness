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

Licença Apache-2.0. Nenhuma ferramenta elimina todos os erros de modelos;
permissões, evidências e validações precisam existir fora do LLM.
