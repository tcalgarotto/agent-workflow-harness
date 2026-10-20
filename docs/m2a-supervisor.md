# M2a — supervisor isolado e recibos de validação

O supervisor executa comandos sintéticos ou de desenvolvimento em um perfil
Linux/Docker limitado. O coordenador M1 continua dono de tarefas e concessões.
Ainda não há agente de IA ou LangGraph. A integração Git local é um componente
separado: [gateway M2b](m2b-integration.md), com autorização e revalidação próprias.

## Fronteiras e perfil disponível

O código candidato roda como UID/GID 10001, com capabilities removidas,
`no-new-privileges`, seccomp padrão, root filesystem somente para leitura,
namespaces separados, sem rede externa e sem portas publicadas. O workspace é
um volume tmpfs privado gerenciado pelo Docker; `/tmp` também é privado e limitado.
Não há bind de diretórios do host/projeto, socket Docker, credencial M1 ou segredo
de integração dentro do contêiner. O supervisor e seu acesso ao daemon são confiáveis.

O perfil inicial exige **daemon Docker rootful**, Linux e cgroup v2 com limites de
memória, CPU e PIDs. O processo candidato não roda como root. Docker rootless,
macOS, Windows, GPU, rede liberada e imagens arbitrárias não estão homologados;
ausência dos controles causa recusa. Não há fallback para subprocesso no host.
Não é necessário alterar o daemon para executar o perfil disponível. Containers
compartilham o kernel; o perfil não constitui certificação para código hostil de
terceiros em produção. Para isso, considerar também fronteiras de VM e operação
dedicada após avaliação própria.

O exemplo limita cada contêiner a 128 MiB de memória, 0,5 CPU, 32 PIDs,
workspace de 16 MiB, `/tmp` de 16 MiB, 10 segundos por comando e saída de 64 KiB.
O schema impede ultrapassar os tetos do perfil: 512 MiB, 1 CPU, 128 PIDs,
workspace de 64 MiB, 120 segundos e saída de 1 MiB. Há três slots locais por
diretório de supervisor. Use um único diretório configurado por instalação e
capacidade de host compatível com os limites acumulados.

## Instalar e atualizar o M1

Instalação a partir do checkout, com Python 3.11 ou superior:

```sh
.venv/bin/python -m pip install -e '.[coordinator,supervisor]'
docker pull python:3.14-slim-bookworm@sha256:48b13b003dda20b16f9442b8475aa05fe21bf6579a8c881db92ffb4d8fd20f83
```

O supervisor nunca faz pull/build implícito. A imagem Python é fixada por digest.
Comandos do perfil devem começar por `/usr/local/bin/python`; este primeiro perfil
não executa binários compilados no workspace (`noexec`) nem instala dependências.

Para atualizar um M1 existente, pare **todos** os processos antigos da API,
preserve backup e execute a migração com a identidade de migração:

```sh
.venv/bin/awh-coordinator migrate
```

Não misture servidores M1 antigos e novos durante a atualização. O SQL 001
permanece idêntico; 002 acrescenta `awh_m1.executions` e sua restrição de unicidade,
e 003 acrescenta os registros/barreiras do [M2b](m2b-integration.md).
Migrate confere checksums, aplica o sufixo faltante em transação e não apaga dados.
Para um role de serviço existente, conceda como owner da migração:

```sql
GRANT SELECT, INSERT, UPDATE ON awh_m1.executions TO awh_service;
GRANT SELECT ON awh_m1.integration_policies, awh_m1.integrations,
    awh_m1.integration_reviews TO awh_service;
```

Adicione ao arquivo privado `AWH_AUTH_FILE` uma identidade de serviço com
`role: "supervisor"`, projeto e capacidades explícitos, usando digest de um novo
token aleatório. Não reutilize tokens humanos/worker. Reinicie a API atualizada.
O supervisor pode claim/heartbeat/finish seus próprios runs, além de admitir e
registrar a parada de suas execuções. Não pode aceitar tarefas, modificar escopo
ou reconciliar em nome do controller. Não entregue seu token ao código candidato.

## Executar um piloto

Prepare um projeto e tarefa M1 aceitos, seguindo o [guia do coordenador](m1-coordination.md).
A tarefa precisa declarar os recursos `path:` graváveis e capacidades compatíveis.
Use a identidade supervisor para obter um claim com orçamento de pelo menos duas
unidades. Recursos `named:` continuam reservas M1, sem acesso externo implementado.

Escolha um diretório de entrada pequeno e confiável, por exemplo com `src/`.
Copie o [perfil de exemplo](../examples/supervisor/profile.json) para um local
gerenciado pelo operador. O código candidato não deve poder editar esse perfil,
o diretório de estado ou a configuração do supervisor. Os comandos de validação
são uma decisão do projeto, não um campo da resposta do agente.

Defina `AWH_SUPERVISOR_TOKEN` em seu ambiente privado e, se necessário,
`AWH_COORDINATOR_URL` (padrão `http://127.0.0.1:8765`). Somente HTTP loopback é
aceito, sem redirecionamentos ou proxies do ambiente. Crie um diretório de estado
fora do checkout candidato, com modo `0700`, e execute substituindo os placeholders:

```sh
.venv/bin/awh-supervisor --state /absolute/private/supervisor-state run \
  --source /absolute/project-input \
  --profile /absolute/operator-profile.json \
  --project demo --run-id RUN_ID --fence FENCING_TOKEN
```

O primeiro JSON informa o `execution_id`. A saída final contém estado, hashes e
confirmação de parada; não renderiza stdout arbitrário do candidato no terminal.
Um resultado `validated` significa que o comando de validação do perfil retornou
zero sobre o conteúdo exato registrado e que os contêineres foram parados. Não
significa tarefa aceita, merge autorizado ou garantia de correção semântica.
O run M1 permanece ativo; submissão/aceite e integração seguem caminhos próprios.

## Sequência e autoridade

1. Conferir controles do daemon/imagem e criar snapshot limitado das entradas.
2. Ler run e tarefa; registrar manifesto com contrato/revisão, escopo, base,
   perfil e ambiente. Persistir intenção local antes de qualquer criação.
3. Admitir execução no M1 como supervisor. A transação exige concessão atual,
   reserva duas unidades de consumo e impede outra execução não encerrada no run.
4. Conferir autoridade fresca; criar volume/contêiner exclusivos e copiar a entrada.
5. Executar comando worker com escopo de escrita. Monitorar cancelamento,
   concessão, prazo e saída. Renovar lease sem ultrapassar deadline do M1.
6. Congelar todos os processos, capturar candidato com limites e conferir o diff
   de conteúdo contra os caminhos autorizados. Parar/remover worker e volume.
7. Criar outro ambiente com o candidato somente para leitura. Executar o comando
   de validação definido pelo operador, congelar e conferir que o conteúdo coincide.
8. Confirmar parada, autenticar recibo fora do candidato e registrar conclusão no
   M1 com referência ao recibo. Nenhuma credencial de merge é disponibilizada.

As operações adicionais da API são `start_execution` e `end_execution`, exclusivas
do papel supervisor. Ambas incluem run/fence e `execution_id`; start inclui
`manifest_hash`, end inclui `stopped_confirmed`, `outcome` e recibo quando validated.
`GET /v1/projects/{project}/executions/{id}/authority` faz uma verificação fresca,
sem cache/idempotência; `GET .../executions/{id}` lê apenas o registro histórico.
Os eventos e as duas unidades de débito participam da transação do coordenador.
As duas unidades cobrem a admissão worker+validator, mesmo se a tentativa falhar
antes de ambas as etapas. Não medem custo financeiro ou todas as operações Python.

Um recibo histórico de start não renova autoridade. Há verificação fresca antes
do comando, entre etapas e durante a execução. A admissão SQL e o start Docker
não são uma transação distribuída: nomes determinísticos e journal permitem
conciliar falhas sem relançar código. A perda de concessão interrompe o ambiente
quando o plano de controle está acessível; não promete parada instantânea.

## Arquivos e snapshots

Somente arquivos regulares são aceitos. O importador não segue symlinks e rejeita
hardlinks, dispositivos/FIFOs e nomes não canônicos. Exclui `.git`, `.env*`,
`.ssh`, `.aws`, ambientes Python, dependências e caches conhecidos. **O operador
continua responsável por selecionar entradas sem segredos em outros nomes.**
O limite é de 512 arquivos e 8 MiB de conteúdo; o arquivo de transporte tem teto
de 16 MiB. O snapshot identifica paths/conteúdo, sem preservar permissões,
executabilidade, diretórios vazios ou metadados Git. Use uma origem estável; um
scan de filesystem não equivale a uma transação Git sobre arquivos em edição.

Os arquivos/ancestrais fora do escopo pertencem a root e são somente para leitura;
os paths autorizados pertencem ao UID 10001. Um arquivo exato novo é pré-criado
sem liberar o diretório pai. Operações de rename/replace precisam de escopo de
diretório adequado. O kernel impõe a escrita e o supervisor também confere o diff.
Links/arquivos especiais criados como saída invalidam a captura. Archives do
candidato são analisados em memória com limites; nunca extraídos no host.

## Cancelar, observar e recuperar

```sh
.venv/bin/awh-supervisor --state /absolute/private/supervisor-state cancel \
  --execution-id EXECUTION_ID
.venv/bin/awh-supervisor --state /absolute/private/supervisor-state status \
  --execution-id EXECUTION_ID
```

Cancel inicialmente retorna `cancel_requested: true`, não confirmação de parada.
SIGINT/SIGTERM durante run também solicitam cancelamento. Cancelar a tarefa no M1
revoga a autoridade; a monitoração para o contêiner e seus descendentes. Só depois
de observar parada e remover os objetos correspondentes o supervisor envia end.
M1 finish/reconcile recusam uma execução ainda admitted. `stopped_confirmed` vem
do componente supervisor confiável, não da resposta do candidato.

Se o processo supervisor morrer, perder acesso ao daemon/API ou não confirmar a
parada, não libere recursos manualmente como se nada estivesse executando.
Examine o journal privado e rode recuperação com a mesma instalação/identidade:

```sh
.venv/bin/awh-supervisor --state /absolute/private/supervisor-state recover \
  --execution-id EXECUTION_ID --project demo --run-id RUN_ID --fence FENCING_TOKEN
```

Recover confere nomes/labels e manifesto, para objetos órfãos e registra parada;
nunca reexecuta o worker ou cobra nova admissão. Uma operação ainda controlada
por outro processo mantém seu lock e não pode ser recuperada simultaneamente.
Falha em confirmar a parada mantém estado quarantined e a admissão retida. Depois
da recuperação de um lease vencido/cancelado, o controller ainda precisa executar
a reconciliação do M1 antes de liberar tarefa/recursos. Não há failover multi-host
ou daemon automático de recuperação. O operador precisa recuperar órfãos antes
de aumentar a carga e monitorar retenção/espaço dos artefatos persistentes.

Um watchdog no processo de controle do contêiner encerra ambientes não pausados
após o timeout do perfil + 10 segundos, mesmo se o monitor no host morrer.
Um contêiner congelado não executa seu watchdog e exige `recover`; os limites de
cgroup permanecem. Não trate o watchdog como confirmação de parada no M1.

## Recibos e verificação

O diretório privado guarda blobs por SHA-256, journal e chave HMAC de 32 bytes.
Snapshots são publicados completos, verificados na leitura e nunca montados no
worker. Perder a chave impede autenticar recibos antigos; compartilhá-la amplia
quem pode produzir recibos. Não a publique nem a entregue aos executores.

```sh
.venv/bin/awh-supervisor --state /absolute/private/supervisor-state verify \
  --receipt RECEIPT_HASH --candidate CANDIDATE_HASH \
  --profile /absolute/operator-profile.json
```

A verificação exige MAC correto, candidato íntegro e perfil correspondente.
Mudar o candidato/perfil invalida a associação. O recibo liga contrato aceito,
run/fence, entrada, candidato, comandos exatos, imagem, versão do engine,
resultados, hashes de saída e confirmação de parada. A HMAC autentica a origem
dentro desse domínio de confiança; não é assinatura pública entre organizações.

O comando retorna `accepted_for_integration: false`: autenticação não substitui
revisão, critérios adequados nem checagem da base atual. Um teste inadequado ou
um candidato que influencia a lógica de testes exige oráculos/revisão melhores;
um exit code zero, por si, não prova a intenção do produto. O [M2b](m2b-integration.md) verifica a
autorização e a combinação exata na integração. M1 `decide` continua uma atestação
manual de controller e não se torna um gateway automatizado com esta entrega.

## Testar

```sh
.venv/bin/python -m pip install -e '.[dev,coordinator,coordinator-test,supervisor]'
# Defina AWH_TEST_DATABASE_URL para banco descartável chamado awh_test_*.
AWH_REQUIRE_POSTGRES=1 AWH_REQUIRE_DOCKER=1 \
  .venv/bin/python -m unittest discover -s tests -v
.venv/bin/awh check examples/minimal
```

Os testes destroem somente o schema no banco de teste explicitamente configurado
e removem os contêineres/volumes de seus próprios IDs. Na CI, os jobs supervisor
exigem Docker e PostgreSQL reais em Python 3.11/3.14; ausência dos controles falha.
Os jobs de validação estática continuam utilizáveis sem os extras de execução.

Base técnica: [ADR 0007](decisions/0007-m2a-isolated-supervisor.md), documentação de
[limites Docker](https://docs.docker.com/engine/containers/resource_constraints/),
[execução de containers](https://docs.docker.com/engine/containers/run/) e
[distinção de rootless](https://docs.docker.com/engine/security/rootless/).
