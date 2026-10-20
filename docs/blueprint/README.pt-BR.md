# Arquitetura operacional do Agent Workflow Harness

Versão de projeto: 20/10/2026. Status: proposta para revisão, antes da implementação
do runtime. A arquitetura consolida os estudos anteriores; não promete ausência
de alucinações nem isolamento já implementado.

O sistema recebe uma demanda, transforma seu objetivo em tarefas verificáveis,
distribui trabalho compatível entre executores isolados e integra somente
candidatos com evidências válidas. O núcleo mantém a autoridade sobre tarefas,
recursos, orçamento e conhecimento aceito. Modelos propõem soluções dentro dela.

Hoje existem contratos JSON v1, validador local, exemplos, testes e CI. Não existem
os servidores, bancos, sandboxes ou adaptadores desenhados abaixo. Os contratos de
execução descritos neste documento precisarão de uma versão própria; não são
campos adicionais que a CLI v1 já aceite.

## 1. Como ler os mapas

Os diagramas foram produzidos com Archify 3.2.0. São interativos, com fontes JSON
editáveis. Conteúdo em português; os controles fixos do visualizador estão em
inglês. Setas representam caminhos planejados, não tráfego observado. O exemplo
com funcionários é ilustrativo e não apresenta durações medidas.

| Vista | Pergunta que responde |
|---|---|
| [Componentes](01-sistema.html) | Quem coordena, executa, guarda dados e aceita entregas? |
| [Entrega](02-entrega.html) | Qual caminho uma demanda percorre até concluir? |
| [Memória](03-memoria.html) | O que cada agente consulta e como o conhecimento muda? |
| [Recuperação](04-recuperacao.html) | O que ocorre com falhas, esperas, retries e cancelamentos? |
| [Três funcionários](05-tres-funcionarios.html) | Como distribuir uma feature e integrar mudanças concorrentes? |

As caixas são responsabilidades lógicas. O início será um monólito modular com
processos de execução separados; não precisamos implantar um microserviço para
cada caixa. Fronteiras de confiança continuam reais, mesmo com menos serviços.

## 2. Composição inicial e pontos substituíveis

| Peça | Escolha planejada | Responsabilidade |
|---|---|---|
| Núcleo | Serviço Python autenticado, com CLI cliente | Transições, política efetiva, concessões e aceitação |
| API | HTTP/JSON tipado; framework web definido na implementação | Interface única para CLI, IDE, painel e integrações |
| Coordenação | PostgreSQL, transações curtas e outbox | Fila, recursos, leases, consumo e efeitos |
| Engine | Primeiro adaptador LangGraph | Executar etapas, ramificar e retomar progresso |
| Componentes de IA | LangChain selecionado | Modelos, ferramentas, saída estruturada e recuperação |
| Workers | Adaptadores de runners; Deep Agents opcional | Executar cada tarefa dentro de capacidades verificadas |
| Isolamento | Supervisor Linux e containers sem root, sujeitos a teste | Arquivos, processos, rede, credenciais e quotas |
| Memória | API autorizada sobre registros e fontes versionadas | Separar aceito, observado, proposto e temporário |
| Busca | Exata e textual; pgvector após avaliação | Descobrir fontes sem substituir sua autoridade |
| Artefatos | Armazenamento por hash, inicialmente local restrito | Snapshots, diffs, saídas sanitizadas e recibos |
| Integração | Serviço separado com acesso ao Git protegido | Verificar base, gates e registrar resultado do merge |
| Telemetria | Um exporter inicial, Langfuse ou LangSmith | Traces e avaliação conforme política de dados |

MCP expõe ferramentas; A2A pode transportar comunicação. Nenhum protocolo fornece
sozinho autorização, reservas ou sandbox. ADK fica como alternativa de engine;
MongoDB como possível adaptador de recuperação. IBM inspira catálogos, releases,
pools e recuperação, sem obrigar a contratar seu produto. Não executar dois
schedulers independentes sobre as mesmas tarefas.

## 3. Preparação de um projeto

1. Registrar `project_id`, repositório, responsáveis, classe de dados e ambientes.
2. Criar o pacote de projeto: requisitos, decisões, contratos, mapa do código,
   ownership, procedimentos e critérios de entrega. Material privado permanece
   no escopo autorizado do projeto, fora do repositório público deste harness.
3. Selecionar perfil de stack: ferramentas, comandos aceitos, dependências,
   recursos compartilhados, política de rede e validações relevantes.
4. Selecionar adaptadores e pools homologados. Registrar versões, ferramentas,
   observabilidade de filhos, cancelamento, isolamento e limitações reais.
5. Publicar uma release imutável do conjunto de workflow, regras, contratos,
   perfis e procedimentos. Fixar essa release por execução.
6. Indexar fontes permitidas com hashes e revisões, e executar o teste de entrada
   do projeto antes de liberar trabalho com escrita.

O relatório inicial de produto é uma entrada do pacote de domínio, com origem e
revisão; não vira automaticamente política global. Reutilizar a arquitetura em
outro projeto significa trocar o pacote de domínio, stack e conexões, mantendo
o mesmo protocolo e os testes comuns de conformidade.

## 4. Caminho principal: demanda até entrega

| Etapa | Operação | Evidência ou saída exigida |
|---|---|---|
| Entrada | Autenticar pessoa/integração, identificar projeto e mandato | Demanda identificada, sem segredo no prompt |
| Investigação | Ler código, requisitos, decisões e estado externo relevante | Fontes citadas, revisões e dúvidas explícitas |
| Planejamento | Agente propõe tarefas pequenas e dependências | Objetivo, invariantes, recursos e critérios verificáveis |
| Aceite do contrato | Serviço valida; decisão humana somente se necessária | Revisão aceita e política aplicável |
| Preflight | Conferir contratos, capacidade, ambiente, orçamento e gates disponíveis | Resultado impeditivo ou elegibilidade |
| Reserva | Conceder tarefa e recursos em transação atômica | Run, lease, fencing e orçamento reservado |
| Preparação | Criar snapshot/workspace e manifesto de contexto | Base, release, hashes e ferramentas permitidas |
| Execução | Implementar, consultar memória, publicar observações e candidatos | Commit/diff, artefatos e eventos atribuídos |
| Validação | Rodar verificações confiáveis no candidato imutável | Recibo ligado ao código, ambiente e critérios |
| Revisão | Examinar intenção, completude, contratos e limites | Parecer independente quando exigido |
| Integração | Verificar base atual e integrar combinação validada | Identidade do efeito e recibo do Git |
| Fechamento | Aceitar entrega, liberar recursos e registrar aprendizado | Estado final, links e proposta de conhecimento |

Documentação simples segue controles proporcionais. Mudanças de autorização,
dados persistentes e contratos compartilhados exigem os gates correspondentes.
Nenhum executor enfraquece seus próprios testes, escopo ou critérios para passar.

## 5. Fila, dependências e enxames

O PostgreSQL mantém a fila oficial. Antes de ordenar, o scheduler elimina tarefas
sem contrato aceito, dependências concluídas, capacidade compatível ou autorização.
A prioridade efetiva é calculada por regras do projeto, com aging limitado pela
política, e desempate estável por criação e ID. O agente pode propor prioridade,
mas não conceder a si mesmo precedência ou recursos.

Depois da seleção, uma transação confere conflitos, orçamento e revisão novamente.
Somente o claim bem-sucedido inicia o run. Uma lista de tarefas nativa de IDE é
uma visão ou origem de propostas, nunca uma segunda fila com autoridade própria.

Limite inicial proposto: três slots de trabalho de agente por projeto, configuráveis
após medição. Uma revisão que usa LLM também ocupa slot. Testes e builds têm quota
computacional própria e limitada, sem multiplicar processos livremente. Aumentar
workers exige medir fila de revisão, memória, CPU, custos e limites dos provedores.

Regras de colaboração:

- Usar um agente para uma mudança pequena; fan-out somente para subtarefas úteis.
- Contratos compartilhados entram antes das implementações dependentes.
- Um proprietário ativo por recurso de escrita conflitante. Reservar também
  bancos de teste, portas, caches, artefatos e daemons quando compartilhados.
- Toda delegação registra pai, filho, revisão, ferramentas, recursos e orçamento.
  Começar com profundidade de delegação de um nível; ampliar só com conformidade.
- Os limites do filho são subconjunto dos limites do pai. Retomadas e retries
  preservam o consumo acumulado da tarefa e dos ancestrais.
- Mensagens têm remetente autenticado, destinatário permitido, ID, correlação e
  referências. Deduplicar; não presumir ordem global nem broadcast ilimitado.
- Mensagens e votos não aprovam entregas, ampliam escopo ou alteram permissões.

## 6. Três funcionários na prática

Uma feature ilustrativa precisa de contrato, API e interface:

1. A prepara o contrato; C revisa e as verificações aplicáveis produzem recibos.
   O gateway publica a revisão aceita antes das tarefas dependentes começarem.
2. A implementa a API em seu run; B implementa a interface em outro. Ambos recebem
   o mesmo contrato aceito, com recursos de escrita distintos.
3. C examina plano, evidências e mudanças; o pool confiável executa testes em uma
   combinação isolada. C não recebe a credencial de integração por ser revisor.
4. O integrador incorpora a primeira alteração válida. A segunda é atualizada e
   revalidada na nova base antes de integrar; conflitos retornam com diagnóstico.
5. A tarefa termina com os recibos aceitos. Aprendizados reutilizáveis entram
   como propostas e seguem o caminho de revisão do conhecimento.

São três identidades próprias, não três contas compartilhadas. O adaptador pode
usar uma sessão nativa autorizada ou API conforme o runner suportar. Login de
assinatura não é tratado como chave genérica de API. Não copiar caches de login
entre pessoas, serviços ou modelos. Papéis podem rodar entre funcionários,
preservando a independência exigida pela política.

## 7. Isolamento e efeitos

O supervisor entrega ao worker um ambiente limitado por tarefa, sem escrita no
checkout principal, sem socket Docker do host e sem credencial de merge. Worktrees
ajudam a organizar branches; não bastam como fronteira de segurança. Metadados
Git comuns também não podem ser montados com escrita que permita alterar outros
runs. Usar snapshot/clone privado ou gestão de Git fora do alcance do executor.
O primeiro perfil será Linux, com containers sem root e mounts mínimos. Outros
sistemas operacionais exigem perfil e conformidade próprios; a portabilidade dos
contratos não comprova portabilidade automática do isolamento.

O worker pode editar e testar seu candidato dentro do escopo. Ações compartilhadas
passam por gateway tipado, que valida identidade, lease, fencing, revisão, destino
e argumentos. O broker usa segredos com escopo mínimo; o worker recebe capacidade
restrita e de curta duração quando necessário, sem segredos persistidos em
checkpoints, memória ou traces. Administrar uma conexão é diferente de usá-la.

O validador também executa código candidato não confiável em sandbox, sem segredos
de integração. O serviço confiável registra e autentica os recibos fora do alcance
desse código. Comandos e oráculos são aceitos pelo projeto; o implementador não
escolhe outro comando apenas para produzir uma saída de sucesso.

Capacidades não comprovadas impedem execução que dependa delas. Um runner que só
permita inspeção da entrega pode servir a tarefas compatíveis, mas não será
anunciado como isolamento de execução. Filhos nativos não observáveis precisam
ser desabilitados em runs que exijam delegação controlada.

## 8. Memória e caminhos de leitura/escrita

| Categoria | Exemplo | Como muda |
|---|---|---|
| Conhecimento normativo | Requisito e contrato aceito | Revisão autorizada no Git |
| Estado operacional | Prioridade, run, lease, orçamento | Transação no core |
| Memória aceita da tarefa | Decisão, fonte e handoff vigentes | API com revisão esperada |
| Observações | Resultado de investigação ou teste relatado | Registro atribuído, ainda verificável |
| Propostas | Novo plano, correção ou aprendizado | Aceite explícito no caminho aplicável |
| Evidências | Snapshot, diff e recibo | Artefato imutável e referência por hash |
| Contexto temporário | Conversa, resumo e checkpoint | Escopo do run; sem autoridade permanente |

O namespace inclui projeto, tarefa, run e status de aceitação. A identidade
autenticada determina o acesso no servidor; o modelo não escolhe livremente outro
namespace. Dois agentes podem acrescentar observações, mas não sobrescrever uma
decisão aceita pela regra do último escritor. Conflitos de revisão exigem conciliação.

Consulta: ID/path/símbolo/revisão exatos → busca textual → vetores opcionais →
fusão/reranking se medidos → rechecagem de acesso e validade → manifesto citado.
PostgreSQL FTS não é BM25; BM25 requer implementação própria. ONNX Runtime apenas
executa modelos compatíveis. Scores e concordância entre agentes não provam fatos.

Escrita: observação/proposta → validação tipada e autoria → decisão autorizada →
nova revisão aceita → evento durável → atualização idempotente do índice. Registrar
watermark e geração; descartar jobs atrasados. Revogar acesso antes de depender da
limpeza do índice. Um resultado antigo não pode reaparecer no contexto do modelo.

Chunks retêm origem, revisão, status, escopo, hash e configuração de embedding.
Não misturar embeddings incompatíveis. Mudança de modelo/chunker cria outra geração
avaliada antes da troca. Fontes originais, derivados e backups entram na política
de retenção e exclusão. Não enviar material privado a embeddings ou traces externos
sem autorização de dados para aquele destino.

## 9. Contratos de execução e interfaces planejadas

Os nomes seguintes são propostas de protocolo, não endpoints implementados:

| Operação | Entrada relevante | Saída/condição |
|---|---|---|
| `tasks.submit` | Projeto, mandato, objetivo, critérios e dependências | Tarefa/revisão candidata |
| `tasks.accept` | Revisão esperada, identidade e decisão autorizada | Contrato aceito ou conflito |
| `runs.claim` | Capacidade, recursos e orçamento requerido | Lease, fencing, run e manifesto |
| `runs.heartbeat` | Identidade do run e concessão atual | Renovação válida ou revogação |
| `memory.read` | Referências e consulta autorizada | Fontes e manifesto de contexto |
| `memory.propose` | Autoria, evidências e revisão-base | Proposta sem promoção automática |
| `memory.accept` | Decisor autorizado, fontes e revisão esperada | Nova decisão aceita ou conflito |
| `effects.request` | Operação lógica, argumentos, destino e concessão | Recibo ou estado incerto explícito |
| `effects.reconcile` | Identidade da operação e observação do destino | Resultado comprovado ou recuperação pendente |
| `deliveries.submit` | Commit/base, artefatos e critérios | Candidato aguardando gates |
| `validation.record` | Produtor confiável e entradas exatas | Recibo autenticado e revisões |
| `integration.request` | Candidato, base atual e recibos exigidos | Merge comprovado ou revalidação |

Todas as mutações relevantes têm schema, autorização, revisão e idempotência.
Modelos, editores e protocolos diferentes usam as mesmas operações. Atualizar uma
mensagem de chat ou um checkpoint não executa uma transição oficial por si só.

Modelo de dados conceitual: `projects`, `workflow_releases`, `tasks`,
`task_dependencies`, `runs`, `resource_reservations`, `budget_ledger`,
`effect_intents`, `effect_receipts`, `decisions`, `observations`, `proposals`,
`artifacts`, `validation_receipts`, `messages`, `outbox` e `index_generations`.
Não é uma migração SQL pronta. Revisar unicidade, relacionamentos, isolamento e
conflitos hierárquicos de recursos antes de implementar as tabelas.

## 10. Caminhos de falha e retomada

| Situação | Caminho planejado |
|---|---|
| Contrato incompleto ou fonte contraditória | Investigar sem escrita; solicitar apenas a decisão não coberta pelo mandato |
| Dependência, capacidade ou recurso indisponível | Espera com motivo; sem claim ativo desnecessário |
| Limite temporário do provedor | Backoff limitado, respeitando orçamento e política de fallback |
| Teste ou revisão reprovada | Diagnóstico para nova tentativa dentro do contrato |
| Arquivo fora do escopo | Bloquear escrita; rejeitar candidato incompatível na entrega |
| Lease expirado ou worker desconectado | Revogar efeitos; preservar histórico e conciliar antes da retomada |
| Crash depois de um efeito | Consultar ledger/destino pela mesma identidade; não repetir às cegas |
| Base mudou antes do merge | Atualizar candidato e revalidar evidências afetadas |
| Busca vazia, indisponível ou atrasada | Leitura exata autorizada ou evidência insuficiente |
| Traces indisponíveis | Preservar ledger obrigatório; seguir política explícita de auditoria |
| Cancelamento | Revogar concessões, pedir parada e registrar confirmação ou limitação |
| Limite de recuperação atingido | Fila de recuperação com responsável e condição de continuidade |

O fluxo normal é pronta → reservada → executando → verificando → integrando →
concluída. Há esperas, ajustes, reconciliação, cancelamento e falha final. Retomar
checkpoint não renova orçamento ou permissões; restaurar workflow não desfaz
efeitos anteriores. Compensação ou reversão é outra operação autorizada e verificada.

## 11. Operação e implantação por etapas

Primeiro, um coordenador confiável no ambiente local, PostgreSQL, armazenamento
restrito de artefatos e supervisor de execução. Workers e validadores são processos
separados com fronteiras de permissão, mesmo no mesmo host. Comunicação por API
autenticada; identidades dos serviços não são credenciais humanas compartilhadas.

A evolução multi-host acrescenta workers autenticados, concessões verificadas,
limites de transporte e recuperação de partições. Não depende de um provedor de
cloud específico. Backup/restore deve alinhar registros, artefatos, revisões e
gerações de índice antes de permitir novas escritas. Modo de manutenção suspende
novos claims, drena ou revoga runs e concilia efeitos pendentes.

O painel mostrará tarefa, dono, dependências, orçamento, lease, candidato, gates,
diff e recuperação. Formulários gerados continuam sujeitos ao mesmo servidor.
O núcleo permanece utilizável sem painel. LangSmith ou Langfuse observam; nenhum
tracer é o ledger oficial. O envio externo é opt-in, sanitizado e testado.

A avaliação mantém dois vereditos: cumprimento das invariantes operacionais e
resultado da tarefa. Um judge semântico não supera uma violação obrigatória.
Quando usado, deve ser calibrado com casos rotulados, incluindo falsos aceites,
e avaliado em casos reservados fora do ajuste de prompts. Registrar ações,
resultados e decisões concisas; não solicitar raciocínio privado dos modelos.

## 12. Ordem de construção e critérios de saída

| Marco | Construir | Demonstrar antes de avançar |
|---|---|---|
| M0 — base existente | Contratos v1, validador e CI | Limites do protótipo explícitos |
| M1 — coordenação | API, PostgreSQL, claims, recursos, orçamento e outbox | Dois claims conflitantes não obtêm autoridade; revisão obsoleta é rejeitada |
| M2 — contenção | Supervisor, gateway de efeitos, validador e integração | Escape de workspace falha; efeito com fencing antigo é recusado |
| M3 — execução pequena | Um runner real e adaptador LangGraph limitado | Crash/replay não duplica efeito aceito nem renova orçamento |
| M4 — memória mínima | API tipada, fontes por hash, busca exata/textual | Conflito de decisão e vazamento entre projetos são rejeitados |
| M5 — interoperabilidade | Segundo runner diferente e três slots controlados | Mesmo workflow e gates em ambos; integração concorrente sem sobrescrita |
| M6 — avaliação e escala | Telemetria, fixtures, pgvector opcional e capacidade | Ganho medido sem relaxar invariantes; restauração testada |

M1–M4 podem ter incrementos intercalados: o primeiro runner recebe contexto exato
do Git antes de haver busca completa. O primeiro piloto termina em candidato
reviewável; merge automático só é habilitado após os controles do gateway terem
evidência e autorização do projeto. A aprovação desta arquitetura não instala
serviços nem autoriza deploy, gastos ou merge de implementações futuras.

## 13. Como os estudos entram no projeto

| Origem | Aplicação no desenho | Limite preservado |
|---|---|---|
| Relatório de domínio inicial | Pacote de projeto, requisitos e fontes privadas | Não publicar seu conteúdo no harness genérico |
| IBM Concert Workflows | Catálogo de ações, conexões, pools, releases e recuperação | Não pressupor integração pronta com runners |
| DoorDash | Tarefa delimitada, estado real, validação e avaliação de manutenção | Não transferir números de produtividade |
| AWS RAG | Separar recuperação, geração, avaliação e observabilidade | Judge não substitui gate nem sandbox |
| ADK | Alternativa atrás do contrato de engine | Sem scheduler concorrente sobre a mesma tarefa |
| Claude e referências de times | Subtarefas, peers, mensagens, goals e limites nativos | Memória nativa e consenso não são autoridade |
| OpenAI e registros reutilizáveis | Diário, resultados, decisões, falhas e índice curado | Não guardar raciocínio privado nem promover logs automaticamente |
| LangChain/LangGraph/Deep Agents | Camadas de execução e componentes substituíveis | Não confundir contexto isolado com isolamento de processos |
| MongoDB/PostgreSQL/RAG | Persistência por papel e recuperação avaliada | ACID e relevância não resolvem todo o protocolo |
| Swarms, tutoriais e Thesys | Padrões de colaboração e visibilidade para operadores | Demos e marketing não certificam capacidades |

Detalhes e fontes verificadas estão em [arquitetura](../architecture.md),
[times](../development-teams.md), [memória](../task-memory.md),
[LangChain](../langchain-integration.md), [armazenamento](../storage-and-retrieval.md)
e [avaliação](../evaluation.md), com os registros de pesquisa em `docs/research/`.
Os diagramas são documentação do plano; sua validação verifica o artefato visual,
não comprova as propriedades de segurança do futuro runtime.

Registros de fontes: [DoorDash, AWS e ADK](../research/2026-10-20-doordash-adk-aws.md),
[times e enxames](../research/2026-10-20-coding-teams-and-swarms.md),
[LangChain](../research/2026-10-20-langchain-ecosystem.md) e
[bancos e tutoriais](../research/2026-10-20-mongodb-postgresql-and-swarms.md).
Para a inspiração enterprise, consultar [IBM Concert Workflows](https://www.ibm.com/br-pt/products/concert/workflows),
[versionamento](https://www.ibm.com/docs/en/concert/3.0.x?topic=workflows-workflow-version-control)
e [workers remotos](https://www.ibm.com/docs/en/SSQNYH_3.0.x/administering/remote-workers.html).

## 14. Editar e reproduzir os mapas

Cada HTML tem uma fonte JSON do mesmo prefixo. Usar a skill Archify 3.2.0,
commit `208acba8d412335185b2056fedf54b3405df43fb`. Definir `ARCHIFY_DIR` como a
pasta da skill instalada e executar, nesta pasta, por exemplo:

```sh
node "$ARCHIFY_DIR/bin/archify.mjs" finalize architecture 01-sistema.architecture.json 01-sistema.html --quality showcase --out-dir reviews/local-01 --json
```

Para os demais arquivos, os modos são `workflow`, `dataflow`, `lifecycle` e
`sequence`. Preservar fonte e significado; usar outra pasta de evidências após
alterar um artefato já verificado. O índice de leitura precisa acompanhar este
Markdown quando o texto mudar. Recibos locais do Archify podem conter caminhos
da máquina; não publicá-los sem sanitização. O manifesto de proveniência incluído
registra versão e hashes sem esses caminhos.

Os visualizadores carregam código do Archify sob MIT e fontes sob OFL; consultar
`ARCHIFY-LICENSE.txt`, `THIRD_PARTY_NOTICES.md` e `JetBrainsMono-OFL.txt`.
Fontes dos diagramas e documentação própria seguem a licença do projeto.
