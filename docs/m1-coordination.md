# M1 — coordenação local com PostgreSQL

M1 implementa uma API de coordenação. Ela registra tarefas, concede autoridade
temporária, reserva recursos e orçamento e mantém eventos na mesma transação.
Ainda não executa agentes, comandos, Git, testes candidatos ou efeitos externos.
O validador estático v1 continua independente; `protocol: "m1"` é outro contrato.

Extensão atual: o [supervisor M2a](m2a-supervisor.md) usa esta API para executar
comandos em contêineres próprios e registrar parada/recibos. Atualize a API com a
migração 002 antes de habilitá-lo; o schema 001 e os contratos v1 não são alterados.

## Executar

Instale a partir do checkout, com Python 3.11 ou superior:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[coordinator]'
```

Prepare um PostgreSQL dedicado (testado na versão 18). Defina
`AWH_DATABASE_URL` no ambiente por seu gerenciador de segredos ou shell local,
sem versionar DSNs. O comando de migração precisa criar o schema `awh_m1`.
Migrações são explícitas, transacionais e verificam versão e checksum:

```sh
.venv/bin/awh-coordinator migrate
```

Crie fora do repositório um arquivo JSON de credenciais, com permissão `0600`.
Cada entrada contém `subject`, `role`, `projects`, `capabilities` e
`token_sha256`. Os papéis básicos são `controller`, `worker` e `reader`; o
[M2a](m2a-supervisor.md) acrescenta `supervisor` para o serviço de execução confiável.
Gere um token aleatório independente por identidade, com pelo menos 32 bytes
aleatórios, usando seu gerenciador de segredos ou `secrets.token_urlsafe(32)`.
Armazene no arquivo somente seu digest hexadecimal SHA-256; entregue o token ao
cliente autorizado por canal privado. Não use senhas ou sessões de fornecedores.

Formato ilustrativo (substitua o digest; o exemplo não é uma credencial válida):

```json
[
  {
    "subject": "operator",
    "role": "controller",
    "projects": ["demo"],
    "capabilities": [],
    "token_sha256": "REPLACE_WITH_64_HEXADECIMAL_CHARACTERS"
  },
  {
    "subject": "worker-a",
    "role": "worker",
    "projects": ["demo"],
    "capabilities": ["python"],
    "token_sha256": "REPLACE_WITH_ANOTHER_TOKEN_DIGEST"
  }
]
```

Defina `AWH_AUTH_FILE` como o caminho absoluto desse arquivo e inicie:

```sh
.venv/bin/awh-coordinator serve --port 8765
```

O servidor aceita bind somente em `127.0.0.1` ou `::1`, sem TLS próprio. Não o
publique em rede por proxy/túnel como se fosse um serviço de produção. A
configuração é carregada no início: para revogar/rotacionar tokens, substitua a
entrada e reinicie **todos** os processos do serviço antes de considerar a
revogação efetiva. Capacidades são concessões do operador, não conformance de um
runner. Não há SSO, expiração automática de token ou emissão pública de contas.

O startup confere a migração e não cria tabelas. A documentação OpenAPI está em
`http://127.0.0.1:8765/docs`, com o schema em `/openapi.json`. As rotas de dados
exigem `Authorization: Bearer <token>`; não há CORS habilitado. Cabeçalhos de
autorização e DSNs não são incluídos em eventos. Requisições POST têm limite de
1 MB e rejeitam chaves JSON duplicadas, valores não finitos e campos inesperados.

Use uma identidade de banco distinta da identidade de migração. Depois de criar
um role de serviço `awh_service`, conceda apenas o necessário, como owner da
migração (a criação do role e sua autenticação são tarefas do operador):

```sql
GRANT USAGE ON SCHEMA awh_m1 TO awh_service;
GRANT SELECT ON ALL TABLES IN SCHEMA awh_m1 TO awh_service;
GRANT INSERT, UPDATE ON awh_m1.projects, awh_m1.tasks, awh_m1.runs TO awh_service;
GRANT INSERT, DELETE ON awh_m1.dependencies, awh_m1.reservations TO awh_service;
GRANT INSERT ON awh_m1.commands, awh_m1.budget_ledger, awh_m1.outbox TO awh_service;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA awh_m1 TO awh_service;
```

O serviço e o banco são componentes confiáveis. Não entregar suas credenciais
a agentes. Não há RLS: isolamento por projeto é aplicado pela API. O ledger é
append-only pela API, mas não é um log inviolável contra o administrador do banco.

## API e caminhos

| Método e rota | Função |
|---|---|
| `POST /v1/projects` | Controller registra configuração imutável de projeto |
| `POST /v1/projects/{project}/commands` | Executa uma das operações tipadas abaixo |
| `GET /v1/projects/{project}` | Configuração e totais de orçamento |
| `GET /v1/projects/{project}/tasks` | Tarefas por ID; `after_task` e `limit` para paginação |
| `GET /v1/projects/{project}/tasks/{task}` | Documento, estado, revisão e consumo |
| `GET /v1/projects/{project}/runs/{run}` | Run, fence e validade temporal do lease |
| `GET /v1/projects/{project}/events` | Outbox ordenada, com cursor `after` e `limit` |

Identidades só enxergam os projetos concedidos na configuração do servidor.
Worker não pode se promover a controller, aceitar tarefas ou reconciliar runs.
Controller não pode usar rotas de worker em nome de outra pessoa. Reader só lê.

Cada comando inclui `operation` e `command_id` único (8–128 caracteres
alfanuméricos, `_` ou `-`). O ID é deduplicado por projeto e identidade,
**independentemente da operação**. Repetir o mesmo ID e corpo devolve o recibo
original; outro corpo é conflito. Comandos rejeitados não são persistidos.
Uma resposta antiga não renova lease, não reexecuta charge e não concede
autoridade atual. Depois de uma perda de conexão, repita exatamente o comando;
para uma nova tentativa lógica, use outro ID. Um claim vazio também tem recibo.

| Operação | Papel | Campos adicionais |
|---|---|---|
| `submit` | controller | `task` (proposta M1) |
| `revise` | controller | `task_id`, `expected_revision`, `task`; somente proposta |
| `accept` | controller | `task_id`, `expected_revision` |
| `cancel` | controller | `task_id`, `expected_revision` |
| `decide` | controller | `task_id`, `expected_revision`, `outcome` complete/retry, `evidence_ref` |
| `claim` | worker | `budget`, `lease_seconds` |
| `heartbeat` | worker | `run_id`, `fencing_token`, `lease_seconds` |
| `charge` | worker | `run_id`, `fencing_token`, `units` |
| `finish` | worker | `run_id`, `fencing_token`, `artifact_ref` |
| `sweep` | controller | Sem campos adicionais |
| `reconcile` | controller | `run_id`, `fencing_token`, `evidence_ref` |

Os exemplos de projeto e proposta estão em
[examples/coordinator](../examples/coordinator/project.json). Depois de criar o
projeto, siga a sequência (cada chamada com a identidade apropriada):

1. `submit` → proposta em revisão 1.
2. `accept` com revisão 1 → tarefa pronta com contrato aceito em revisão 2.
3. `claim` → scheduler escolhe uma tarefa elegível, devolvendo run e contrato.
4. `charge` **antes** de usar uma unidade de trabalho autorizada; heartbeat dentro
   do prazo. O cliente transporta os campos `run_id` e `fence` recebidos como
   `run_id` e `fencing_token` nas chamadas seguintes.
5. `finish` com referência do candidato → estado submitted, libera a parcela não
   usada do orçamento e os recursos. A referência ainda não é uma evidência validada.
6. O controller analisa o candidato fora do M1 e registra `decide`, com a revisão
   atual lida na API. `complete` libera dependentes; `retry` mantém o consumo e
   volta à fila. A decisão é uma atestação explícita do controller, sem merge ou
   verificação automatizada de gates. Não usar esse atalho como gateway de produção.

`revision` avança em transições para controle otimista. `accepted_revision` e
`contract_hash` identificam o conteúdo aceito, mantido entre retries. Conteúdo
aceito não pode ser alterado no M1; mudanças de escopo precisam de outra tarefa.
Dependências precisam existir no mesmo projeto; ciclos e autorreferência são
recusados. Uma dependência cancelada continua impedindo o claim do dependente.

## Concorrência, leases e recursos

Cada mutação usa transação READ COMMITTED e bloqueio `FOR UPDATE` na linha do
projeto. Depois de adquirir o lock, as decisões usam estado confirmado e horário
do PostgreSQL. Isso coordena diferentes processos/hosts sem mutex em memória.
Não manter transações abertas durante trabalho de IA ou chamadas externas.

A elegibilidade exige tarefa aceita/pronta, dependências completed, capacidades
concedidas ao worker, slot disponível, recursos livres e orçamento suficiente.
A ordenação usa prioridade 0–100 + aging de uma unidade/hora limitado a 20,
com desempate por criação e ID. Contratos e configuração não são definidos pelo
worker no pedido de claim. Os limites de concorrência incluem runs incertos.

Recursos são exclusivos e **locais ao projeto**:

- `path:src/` conflita com `path:src/api.py`, mas não com `path:src2/`.
- Um path sem `/` final significa um arquivo exato.
- `named:test-db` conflita apenas com o mesmo nome nesse projeto.
- Somente subescopos da lista de recursos do projeto podem entrar em tarefas.

Não compartilhar entre projetos um banco de teste, checkout ou recurso físico
protegido apenas pelo mesmo nome M1: não há lock global entre projetos. Isole o
recurso por projeto até existir um protocolo global homologado. Esses escopos são
reservas lógicas; não resolvem symlinks nem impõem permissões de filesystem.

Cada grant recebe fence monotonicamente crescente no projeto. Renovação, charge
e finish conferem proprietário, fence, estado, contrato e lease pelo relógio do
banco. Renovação é limitada pela política do projeto e pelo deadline absoluto do
run (não muda em heartbeats). Fence não é segredo; a identidade também é exigida.

Ao expirar, o run entra em expired e a tarefa em reconciling. Cancelar revoga a
autoridade. Em ambos os casos, recursos e orçamento continuam retidos. Comandos
`claim` e `reconcile` fazem sweep de expirações; o controller também pode executar
`sweep` explicitamente. As demais operações conferem prazo quando necessário,
sem alterar silenciosamente a revisão esperada de uma tarefa.
Não há daemon de limpeza. Uma leitura pode mostrar `state: active` antes do sweep,
mas `lease_current: false` indica o prazo vencido. Essa leitura não é um permit
para efeito externo, pois está sujeita à mudança logo após a resposta.

O controller só deve executar `reconcile` depois de confirmar parada do executor
anterior e resolver efeitos incertos. Esse comando registra a referência da
atestação, consome conservadoramente o saldo reservado, libera recursos e volta
à fila (ou mantém cancelled). Não interpreta a referência nem para processos.
Restaurar backups/recriar bancos pode afetar monotonicidade de fences; não reabrir
autoridade após restore sem reconciliação e protocolo adicional no M2.

## Orçamento, outbox e falhas

A unidade M1 é uma autorização de chamada/operação, inteira, sem moeda ou tokens
de modelo. O claim reserva uma parcela do limite cumulativo da tarefa e projeto.
`charge` move unidades de reservado para consumido atomicamente; nunca pode
ultrapassar a alocação. Finish libera unidades não usadas. Perda/cancelamento
seguido de reconciliação consome o saldo incerto. Retry, reinício do serviço e
novo run não zeram consumo. O cliente deve reservar uma parcela menor quando
restarem menos unidades; o servidor não aumenta limites automaticamente.

M1 protege o ledger e os permits da API; ainda não intercepta chamadas reais de
um agente. A ligação entre charge e efeito externo, custos monetários, quotas de
processos, delegação e orçamento dos ancestrais pertencem a M2/M3. Não declarar
um limite de gasto externo garantido a partir deste contador.

Comando, mudanças, ledger e evento são confirmados juntos. Falha antes do commit
reverte todos; commit com resposta perdida é recuperável pelo mesmo command_id.
A outbox é uma fonte durável para polling, sem broker/exporter implementado.
O consumidor persiste seu cursor **depois** de processar o evento e deduplica
pelo ID; não presumir entrega exactly-once. IDs podem ter lacunas. Eventos são
ordenados por projeto e incluem autoria, pedido e resultado, sem raciocínio
privado. Não enviar segredos em objective, artifact_ref ou evidence_ref: esses
campos e os documentos podem aparecer no ledger/eventos consultáveis do projeto.

Conflitos retornam 409; escopo/papel recusado, 403; autenticação ausente/inválida,
401; documento inválido, 422; JSON inválido, 400; corpo grande, 413. Erros de banco
retornam 503 sem DSN ou SQL. Em timeout/falha ambígua, repita o mesmo command_id.
Não há retries de efeito externo, scheduler em background, memória RAG, sandbox,
runner real, LangGraph ou merge. O serviço não substitui os controles do M2.

## Verificação

Use somente banco descartável cujo nome começa com `awh_test_`. A suíte trunca
as tabelas M1 desse banco, preservando sua migração:

```sh
.venv/bin/python -m pip install -e '.[dev,coordinator,coordinator-test]'
# Defina AWH_TEST_DATABASE_URL no ambiente para o banco descartável.
AWH_REQUIRE_POSTGRES=1 .venv/bin/python -m unittest discover -s tests -v
.venv/bin/awh check examples/minimal
```

Sem extras/DSN, os testes opcionais de PostgreSQL são marcados skip. O job
obrigatório `coordinator` da CI exige ambos e falha em vez de pular a suíte.
Testes usam conexões e processos independentes, incluindo disputa por escopo
pai/filho, retry após commit, rollback, revisão obsoleta, tokens vencidos,
cancelamento, capacidade removida, reconciliação e orçamento após reinício.

Decisões técnicas: [ADR 0006](decisions/0006-m1-local-coordination.md). As
semânticas de transação e locks seguem a documentação oficial de
[PostgreSQL](https://www.postgresql.org/docs/18/explicit-locking.html) e
[Psycopg](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).
