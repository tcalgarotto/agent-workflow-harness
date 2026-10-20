# M2b — integração Git local protegida

O gateway transforma um candidato M2a em um commit aceito em **um repositório
bare privado e local**. Exige concessão atual, contrato aceito, escopo, recibo
autenticado e registrado no coordenador, perfil aprovado e validação da combinação
exata com a base atual. Só então autoriza o efeito no Git. Workers não recebem
repositório, credencial SQL, chave de recibos ou token do integrador.

Este piloto não publica branches no GitHub nem substitui suas proteções de PR/CI.
Não executa IA, LangGraph, builds com dependências/rede ou efeitos externos gerais.
O comando e o oráculo de validação são responsabilidade do operador: controles de
integridade não provam correção semântica nem ausência de alucinações.

## Instalação e migração

Use Python 3.11+, Git 2.43+ com transações `update-ref --stdin` (testado também no Git
dos runners Ubuntu 24.04), PostgreSQL e o perfil Linux/rootful-Docker do
[M2a](m2a-supervisor.md). A imagem fixada precisa estar em cache. Instale:

```sh
.venv/bin/python -m pip install -e '.[coordinator,coordinator-test,supervisor]'
```

Pare **todos** os processos antigos da API, supervisor e gateway antes de migrar.
Preserve backup do banco, repositório e estado privado. Com `AWH_DATABASE_URL`
configurado no ambiente do migrador, execute `awh-coordinator migrate`. O SQL 003
é aditivo: políticas, integrações e revisões; checksums 001/002 são preservados.
O serviço M1 precisa SELECT nas três tabelas novas para aplicar os bloqueios; o
gateway precisa SELECT/INSERT/UPDATE nelas e nas tabelas M1 de estado, orçamento,
reservas e outbox, com acesso à sequence de eventos/ledger. Use identidades SQL
operacionais próprias e não distribua nenhuma delas aos candidatos. Não misture
processos antigos, que desconhecem a barreira de integração, com o schema novo.

Acrescente uma credencial `role: "integrator"` ao `AWH_AUTH_FILE`, com subject
próprio, digest de token aleatório e projetos explícitos. O gateway consulta esse
registro para conferir também o grant/capacidades do supervisor e do revisor.
Grants são configuração de startup; substitua o arquivo e reinicie os serviços
de forma coordenada ao revogar/rotacionar acessos. Não há hot reload distribuído.
O papel integrator não pode claim, executar candidatos, aceitar contratos ou
aprovar sua própria mudança de política. O controller registra a configuração e
aprova mudanças protegidas; somente o integrator efetiva e reconcilia o Git.

O CLI usa `AWH_DATABASE_URL`, `AWH_AUTH_FILE` e `AWH_INTEGRATION_TOKEN`. São
segredos/configurações do host confiável; não são argumentos do worker. Não há
endpoint remoto de integração. O API disponibiliza somente leitura autenticada
em `GET /v1/projects/{project}/integrations/{id}`.

## Preparar um projeto

1. Crie o projeto M1, tarefas aceitas e grant supervisor conforme os guias M1/M2a.
2. Crie uma cópia bare de uma origem confiável, fora dos checkouts candidatos:

   ```sh
   git clone --bare --no-hardlinks /absolute/trusted/project /absolute/private/accepted.git
   chmod 700 /absolute/private/accepted.git
   ```

3. Copie [policy.json](../examples/integration/policy.json) para configuração
   gerenciada pelo operador. Ajuste projeto, caminhos absolutos, branch direta
   existente e perfil. `supervisor_state` deve ser o mesmo diretório privado M2a,
   contendo chave e blobs dos recibos. Use um único estado configurado por instalação.
   O perfil deve coincidir exatamente com o utilizado no M2a. Para o M2b, o
   validator é Python `-I -S -c` com código definido pelo operador: ignora imports
   automáticos do diretório e site packages. Não carregue configuração de checks
   de caminhos que o candidato possa alterar sem revisão.
4. Com token **controller**, registre explicitamente a política:

   ```sh
   awh-integrate --policy /absolute/operator/policy.json register
   ```

A política registrada é imutável neste piloto. Mudar perfil, caminhos protegidos,
diretório de estado ou destino requer futura migração administrativa explícita;
`register` não sobrescreve uma política diferente. Uma combinação repository/branch
só pode pertencer a um projeto. Não crie aliases de filesystem para contornar isso.
O proprietário do host/DB/Git continua confiável; workers não têm shell nesse host.

**Projetos registrados passam a exigir o gateway para concluir tarefas.** M1
`finish` e `decide complete` não podem contornar a integração. Projetos sem
política preservam a atestação manual M1. Cancelamento e reconciliação continuam
disponíveis, respeitando as barreiras de parada e efeito pendente.

## Caminho normal

Use sempre um OID Git completo e imutável, não `HEAD`, nome de branch ou hash
abreviado. Exporte uma revisão ancestral da branch aceita para um diretório novo:

```sh
awh-integrate --policy /absolute/operator/policy.json export \
  --base FULL_COMMIT_ID --destination /absolute/new-input
```

O export não faz checkout nem executa hooks/filtros. Registra hash de conteúdo,
sem `.git`. Faça claim com a identidade **supervisor**, com ao menos três unidades
livres: duas para admissão M2a e uma por tentativa admitida de revalidação M2b.
Execute M2a sobre esse export e o `profile` exato da política. Não envie `finish`.
Conserve o run ativo e renove sua lease até iniciar o gateway. O CLI M2b usa o
token **integrator**:

```sh
awh-integrate --policy /absolute/operator/policy.json inspect \
  --receipt RECEIPT_HASH --candidate CANDIDATE_HASH --base FULL_COMMIT_ID

awh-integrate --policy /absolute/operator/policy.json integrate \
  --receipt RECEIPT_HASH --candidate CANDIDATE_HASH --base FULL_COMMIT_ID
```

`inspect` mostra hashes, caminhos e fingerprint de revisão; não concede autoridade
nem executa checks. `integrate` imprime primeiro um `integration_id` para recuperação
e depois o resultado. Retorna zero somente para `committed`. O caminho é:

1. Autenticar recibo HMAC, blobs de entrada/saída, manifesto e comandos. Conferir
   projeto, run/fence, contrato/revisão, capacidades e execução encerrada como
   validated com o mesmo recibo no PostgreSQL. Recibos anteriores ao identificador
   `m2a-receipt-1` devem ser reemitidos por uma execução atualizada.
2. Conferir que a entrada M2a é exatamente o conteúdo do commit base declarado e
   que ele é ancestral da branch aceita. Calcular alterações reais e conferir
   escopo aceito, incluindo adições e exclusões.
3. Combinar esse delta com a branch atual. Preservar mudanças em arquivos não
   tocados; recusar conflitos no mesmo arquivo, tipo/diretório ou modo. Não há
   resolução textual automática. Se a base avançar durante validação, a tentativa
   é recusada; uma nova tentativa precisa revalidar a nova combinação.
4. Admitir tentativa no banco e consumir uma unidade de operação. Renovar a lease
   durante validação, respeitando deadline e grant. Criar um novo contêiner somente
   para leitura, sem credenciais/rede, usando os limites M2a. Executar o validator
   aprovado sobre a combinação exata, congelar e reconferir conteúdo; confirmar
   parada antes de produzir recibo M2b.
5. Preparar commit com pai igual à base atual e produzir recibo da validação
   combinada. Revalidar autoridade/revisão/recibos/revisão protegida em transação
   SQL. Registrar permissão durável com OIDs exatos e reter tarefa/recursos.
6. Efetivar avanço Git com compare-and-swap do OID antigo e registro auxiliar
   `refs/awh/integrations/{project}/{integration_id}`. Conferir o efeito e atualizar
   estado para committed, tarefa completed e run submitted com OID como artifact_ref.
   Liberar somente o orçamento não consumido e reservas na transação com outbox.

Tentativas recusadas antes da admissão não consomem unidade de validação. Tentativas
admitidas abortadas consomem a unidade; retry cria novo ID e nova validação. O mesmo
run/execução só pode ter uma tentativa não abortada. Repetir um comando não produz
uma segunda integração; use `status`/`recover` para consultar o ID original.

## Proteção dos checks

Sempre protegidos: `tests/`, `.github/`, `AGENTS.md`, `CLAUDE.md`, `pyproject.toml`,
`setup.py`, `setup.cfg`, `pytest.ini`, `tox.ini`, `.harness/`; também qualquer
`conftest.py`, `sitecustomize.py`, `usercustomize.py` ou arquivo `.pth`. A política
acrescenta caminhos específicos do projeto, como scripts de validação e código
do próprio harness. Escopo de escrita amplo **não** autoriza enfraquecer checks.

Mudanças protegidas são recusadas sem revisão explícita de controller distinto
do executor. Depois de examinar o diff/conteúdo e a intenção do check, o revisor
usa o fingerprint retornado por `inspect` e seu token controller:

```sh
awh-integrate --policy /absolute/operator/policy.json approve \
  --receipt RECEIPT_HASH --candidate CANDIDATE_HASH --base FULL_COMMIT_ID \
  --expected-review EXACT_REVIEW_KEY
```

O registro vincula política, recibo, candidato, commit base, base aceita atual e
caminhos exatos. Mudar qualquer um exige nova revisão. Remover o grant do revisor
também invalida sua aprovação. Aprovar não efetiva o Git nem dispensa revalidação.
Não existe detecção universal de enfraquecimento semântico em qualquer código:
o operador deve proteger todas as fontes do oráculo e revisar efeitos indiretos.

## Falha, cancelamento e recuperação

Antes da permissão durável, cancelamento/perda da concessão interrompe validação.
Uma validação sem parada confirmada permanece retida e impede reconciliar/liberar
o run. O journal é escrito antes da admissão/criação Docker. Não ignore `quarantined`.

**A transação `prepared` é o ponto de não retorno da autorização.** Uma lease
vence com o tempo; ela não pode desfazer retroativamente uma permissão já emitida
para um efeito externo. Enquanto essa intenção estiver pendente, M1 recusa
cancelar, renovar, iniciar nova execução ou liberar aquele run; sweep não o expira.
A permissão autoriza somente o OID planejado contra o OID base exato, nunca novos
comandos arbitrários. Uma solicitação de cancelamento posterior precisa aguardar
reconciliação; para desfazer conteúdo aceito, crie tarefa/commit de reversão.

```sh
awh-integrate --policy /absolute/operator/policy.json status --integration-id ID
awh-integrate --policy /absolute/operator/policy.json recover --integration-id ID
```

Recover adquire lock exclusivo do ID, confirma parada dos objetos Docker com
identidade/manifesto correspondentes e consulta SQL/Git. Não executa candidato,
validator ou merge novamente e não cobra outra unidade. Se o commit planejado
foi aceito, conclui a transação M1 mesmo após lease vencida e mesmo se commits
posteriores avançaram a branch. Se não ocorreu, aborta a intenção e permite o
fluxo normal de cancelamento/expiração/reconciliação ou nova tentativa.

Git e PostgreSQL não são uma transação distribuída. `update-ref` bloqueia writers
concorrentes e usa CAS; não se assume que uma queda do host publique simultaneamente
todos os arquivos de ref. O gateway exige fsync de objetos/refs (`core.fsync=all`,
`core.fsyncMethod=fsync`), sem prometer durabilidade além do armazenamento do host.
A recuperação verifica o marcador **ou** a presença do
commit imutável planejado na ancestralidade aceita, além do pai exato. Marcador
incompatível ou commit removido por reescrita administrativa exigem investigação,
sem sobrescrever a branch nem liberar estado como sucesso. Preserve commits,
refs de integração e journal enquanto houver reconciliação pendente.

Não há daemon de recuperação ou failover multi-host. Use o mesmo estado privado,
repositório e configuração no host confiável; monitore IDs retidos e consumo de
disco. Não use `git push --mirror`, force-push, edições manuais de refs ou SQL para
contornar esses controles.

## Limites verificados

O repositório completo precisa caber no perfil M2a: até 512 arquivos e 8 MiB,
nomes canônicos UTF-8, apenas blobs regulares 100644/100755. Symlinks, submódulos,
arquivos especiais e snapshots parciais são recusados. Modos executáveis existentes
são preservados; arquivos novos recebem 100644. Alterações de modo pelo candidato
não são representadas. Arquivos rastreados excluídos pelo snapshot M2a, como `.env`
ou dependências, impedem a igualdade da base; use um projeto/entrada compatível.

O Git é acessado por plumbing sem checkout, hooks, filtros ou configuração global
do usuário; variáveis Git e credenciais do ambiente não são herdadas. O bare repo,
configuração local, banco, daemon, grants e chave HMAC pertencem ao domínio de
confiança do operador. Não há proteção contra administrador malicioso desse domínio.
Uma política JSON por si só não impõe isolamento: a proteção do candidato é o
container M2a, e a proteção do destino exige acesso exclusivo do gateway no host.

A CI executa Git/PostgreSQL/Docker reais em Python 3.11/3.14, com testes de corrida,
escopo, recibos, checks protegidos, base mutável, parada incerta e recuperação após
efeito Git sem confirmação SQL. O [ADR 0008](decisions/0008-m2b-protected-git-integration.md)
registra as decisões e limites.
