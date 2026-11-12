# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/).

## [Nao lancado]

### Adicionado

**Fase 8 — Finalizacao**

- **Integracao continua** (`.github/workflows/ci.yml`): ruff, `mypy --strict`, a suite
  Python **inteira** com DynamoDB Local subido pelo mesmo `docker-compose.yml` do
  desenvolvimento, tipos/lint/testes/build do Control Center e `terraform validate` com
  `-backend=false`. Nenhum job recebe credencial da AWS.
  Primeira execucao verde nos quatro jobs em 12/11/2026 ([run 43149734246](https://github.com/Buenno0/nexus-architecture/actions/runs/43149734246)).
- `NEXUS_TEST_REQUIRE_DYNAMO`, que transforma "DynamoDB indisponivel" de teste pulado em
  falha. Sem isso, um banco que nao sobe no CI deixaria a suite de integracao inteira
  pular em silencio e o pipeline verde.
- **Diagramas em Mermaid** (`docs/architecture/diagramas.md`): modulos, fluxo de
  ingestao, indice esparso do outbox, ciclo de vida da mensagem, trilha atravessando
  processos, modelo single-table e infraestrutura AWS. Texto, nao imagem, para que o
  diff mostre qual seta mudou.
- **Indice dos ADRs** (`docs/adr/README.md`) com as decisoes de alcance alterado
  marcadas no proprio cabecalho de cada documento.
- **Demonstracao roteirizada** (`scripts/demo.sh`): onze atos da pilha subindo ate o
  alerta apagando, com asserts que **quebram** quando o estado nao corresponde ao que o
  roteiro narra.
- **Relatorio consolidado** (`docs/testing/README.md`), separando as limitacoes ja
  vencidas das atuais e agrupando as atuais por causa.
- Healthcheck do servico `api` no `docker-compose.yml`.

### Corrigido

- **`docker compose up --wait` devolvia antes de a API aceitar conexao.** O servico
  `api` nao tinha healthcheck, entao `--wait` considerava pronto um container que ainda
  nao abrira a porta; a primeira chamada seguinte levava connection reset de forma
  intermitente. Encontrado ao executar `scripts/demo.sh` pela primeira vez.
- **O caminho de falha do roteiro esperava tempo fixo**, e o backoff exponencial entre
  entregas o ultrapassava: a DLQ ficava vazia e os dois atos seguintes narravam um
  alerta que nunca acendeu. O roteiro agora observa o estado e falha quando ele nao
  corresponde.

### Alterado

- Limitacao vencida removida do README: a tela de revisao de pares existe desde a
  Fase 4, mas a lista ainda dizia "nao ha interface de revisao, apenas endpoints".

**Fase 7 — Performance Engineering**

- **Arnes de carga** (`tools/loadtest.py`) que registra, alem da latencia, o delta dos
  contadores, a profundidade de fila e outbox, os processos uvicorn contados dentro do
  container e a saturacao do proprio gerador.
- **Campanha com isolamento** (`tools/campanha.py`): zera tabela e fila antes de cada
  corrida, porque sem isso a segunda medicao herda o acervo da primeira.
- **Isolamento de cenario no Locust**, removendo a tarefa da lista em vez de faze-la
  retornar cedo — uma tarefa que retorna sem fazer nada continua consumindo o turno do
  usuario e o tempo de espera depois dele.
- **Gargalo identificado com evidencia:** o caminho de escrita da ingestao. Com cada
  caminho isolado, `replay` entrega 571,5 req/s, `duplicata` 247,8 e `novo` 103,8.
- **Decomposicao do caminho de escrita:** nucleo 9 ms (56%), trilha da Fase 6 4 ms
  (25%), publicacao na fila 4 ms (25%).
- **Particao quente do `gsi_recency` fechada com numero:** item de 701 bytes, 1 WCU por
  escrita, saturacao a 1.000 registros/s — com a ressalva de que a folga real sao 32%
  no tamanho do item, nao a distancia entre 104 e 1.000.
- `NEXUS_TRAIL_ENABLED` e `NEXUS_DYNAMO_MAX_POOL_CONNECTIONS`; tetos de CPU e
  `--workers` por servico no `docker-compose.yml`.
- Testes de concorrencia contra o **DynamoDB real**, nao so contra o repositorio falso.
- `docs/performance/metodologia.md`, que documenta o metodo **e os erros que o
  produziram**.

### Corrigido

- `/health` declarava `settings: SettingsDep` e sobrescrevia com `get_settings()` na
  linha seguinte, anulando a injecao; `/metrics` fazia o mesmo com `environment` e
  `list_records` nem declarava a dependencia.
- `tests/unit/test_cors.py` registrava classes como override de dependencia — mesmo
  defeito que a Fase 4 corrigiu em outro arquivo, dormente ate `/health` depender de
  settings.
- A contagem de processos uvicorn devolvia 1 em qualquer configuracao: com
  `--workers N` os trabalhadores nascem de `multiprocessing` e a linha de comando deles
  nao menciona uvicorn.

**Fase 6 — Nexus Observability**

- **Trilha durável atravessando processos**, chaveada por `record_id` na tabela base,
  sem indice novo. Seis marcos — `accepted`, `published`, `consumed`, `resolved`,
  `failed`, `dead_lettered` — com TTL de 7 dias (ADR-010).
- **Toda escrita de observabilidade e best-effort** e nunca derruba a operacao que
  descreve. Dois testes cobrem exatamente isso.
- `ProcessingResult.end_to_end_ms`: separa "o processamento esta lento" de "a fila esta
  acumulando". Delta negativo vira `None`, nao zero — relogios discordantes sao medicao
  invalida, nao latencia pequena.
- **Janela deslizante persistida** com amostragem oportunista e escrita condicional por
  balde. Oito observadores simultaneos produzem uma amostra, nao oito.
- **Seis alertas derivados do estado real**, nunca configurados a mao. Backlog grande e
  backlog parado sao condicoes separadas.
- Rotas `GET /v1/observability/trail/{record_id}`, `/series`, `/alerts` e
  `POST /v1/ops/sample`.
- Tela **Trail** com a linha do tempo e o delta entre marcos, faixa de alertas visivel
  em todas as telas, e graficos de profundidade lendo a serie persistida — fecha a
  limitacao que o ADR-009 registrou.
- ADR-010 e `docs/testing/phase-6-report.md`.

### Corrigido

- O marco `resolved` lia `summary["decision"]`, chave que o processador de resolucao
  nunca produziu. Substituida por `candidates_compared` e pelo sinal de truncamento.
- O grafico da serie desenhava baldes nao medidos como passos regulares, desmentindo a
  propria legenda. Eixo temporal e quebra de linha nos buracos.
- `modules.observability` deixou de ser `"partial"` e passou a ser derivado.
- O relatorio da Fase 4 dizia que o bundle inicial caiu "de 869 kB para 238 kB". Os
  238 kB sao o chunk do Cognito que **saiu**; o bundle inicial e de 712 kB. Numero
  publicado sem verificacao, corrigido no proprio relatorio.
- A Fase 5 seguia marcada como pendente no ROADMAP apesar de concluida antes da Fase 3.
- `correlation_id` de 32 caracteres transbordava o card no dashboard.
- `control-center/tsconfig.tsbuildinfo` deixou de ser versionado.

**Fase 4 — Nexus Control Center**

- Dashboard em React 19 + TypeScript strict + Vite, com cinco telas: Overview, API,
  Queue, Worker e Entity Resolution.
- **Todo numero declara a origem** — `persistido`, `processo` ou `sessao` — porque as
  tres tem garantias diferentes e misturar seria enganoso (ADR-009).
- Metrica sem fonte real aparece explicada em vez de inventada; "workers em execucao"
  diz que a execucao e sob demanda.
- Series temporais acumuladas no navegador, com contador que diminui sendo descartado
  em vez de virar taxa negativa.
- Fila de revisao com evidencia campo a campo, confirmando ou recusando fusoes.
- Controles operacionais com teto e confirmacao; gerador sintetico no navegador com
  variantes realistas.
- Autenticacao Cognito implementada e desativada por configuracao; token em memoria,
  nunca em `localStorage`.
- `CORSMiddleware` no backend, com recusa de `*` na propria configuracao.
- 96 testes de frontend (80,5% de cobertura) e 13 de CORS no backend.
- ADR-009 e `docs/testing/phase-4-report.md`.

**Fase 3 — Cloud Infrastructure (construida, nao implantada)**

- Adaptador `SqsQueue` implementando o mesmo `QueueClient` da fila local.
- **Bateria de contrato compartilhada**: a mesma verificacao roda contra `SqliteQueue`
  e `SqsQueue`, e quebra se as duas divergirem.
- Handlers Lambda: `api` (FastAPI via Mangum), `dispatcher` e `worker`, separados para
  que o IAM de cada um seja minimo.
- Terraform completo: DynamoDB com 4 GSIs, SQS + DLQ, 3 Lambdas em arm64, API Gateway
  HTTP com authorizer JWT, Cognito, EventBridge Scheduler, AWS Budgets.
- IAM com privilegio minimo: nenhum `*` em `Action` ou `Resource`.
- Guard rails: concorrencia reservada, retencao de logs de 7 dias, throttling no stage,
  `dynamodb_billing_mode` parametrizavel.
- `scripts/build_lambda.sh` com compilacao cruzada para Linux arm64.
- `docs/runbook-deploy.md` com deploy **e destruicao**.
- ADR-008 documentando a arquitetura serverless.
- 84 testes novos (486 no total).

**Nenhum recurso AWS foi criado. Custo da fase: US$ 0,00.**

**Fase 5 — Nexus Entity Resolution**

- Blocking com chaves proprias (documento, e-mail, nome, telefone), teto de candidatos
  e sinalizacao explicita de truncagem.
- Comparadores com piso de similaridade: Jaro-Winkler, Levenshtein, subconjunto de
  tokens para nomes, e-mail separando parte local e dominio, telefone por sufixo.
- Pontuacao ponderada sobre campos presentes nos dois registros, com guarda de campos
  minimos e excecao para identificadores fortes.
- Tres faixas de decisao; `POSSIBLE_MATCH` nunca funde sozinho.
- Fecho transitivo auditavel: cada vinculo guarda o par e a evidencia; cada fusao gera
  evento com a entidade de origem; teto de cluster recusa e sinaliza.
- Concorrencia otimista por versao de entidade, reaproveitando a retentativa da Fase 2.
- Fila de revisao com indice esparso, confirmacao e recusa.
- Versionamento do processador no marcador e `POST /v1/ops/reprocess`.
- `ensure_table` aditivo: cria indices faltantes em tabelas existentes.
- Gabarito sintetico (`--manifest`) e `tools/evaluate_resolution.py` com precisao,
  recall e F1.
- 135 testes novos (402 no total), 97% de cobertura no pacote de resolucao.
- ADR-006 (blocking, pontuacao e clusterizacao) e ADR-007 (versionamento do processador).

**Fase 2 — Nexus Queue Engine**

- Fila local sobre SQLite com publicacao idempotente, reivindicacao atomica
  (`BEGIN IMMEDIATE`), visibility timeout, backoff exponencial, Dead Letter Queue e
  redrive.
- Dispatcher do outbox consumindo o indice esparso; recupera tudo que a publicacao
  inline nao entregou.
- Worker de consumo sob demanda, com processamento em lotes e idempotencia garantida
  por escrita condicional.
- `ProcessingResult`: o resultado do processamento **e** o marcador de ja processado,
  num unico item.
- Processador injetavel; `FailureInjectingProcessor` exercita retentativa e DLQ sem
  adulterar os dados de entrada.
- Endpoints operacionais `/v1/ops/dispatch`, `/v1/ops/process`, `/v1/ops/queue` e
  `/v1/ops/redrive`, com teto de lote.
- `/metrics` passa a expor a profundidade da fila, que vem do armazenamento e nao de
  contadores em memoria.
- Alvos `make dispatch`, `process`, `drain`, `queue-stats`, `redrive`, `fail-test`.
- `nexus.shared.clock`: fonte de tempo unica, extraida da camada de persistencia.
- 96 testes novos (265 no total), cobertura de 90%.
- ADR-004 (fila local sobre SQLite) e ADR-005 (idempotencia no consumo).
- `docs/testing/phase-2-report.md`.

**Fase 1 — Nexus Ingestion**

- API FastAPI com `POST /v1/records/person`, `POST /v1/records/organization`,
  `GET /v1/records/{id}`, `GET /v1/records` paginado, `GET /health` e `GET /metrics`.
- Header `Idempotency-Key` obrigatorio, com replay, `409` em reuso indevido e TTL.
- Normalizacao conservadora de nome, e-mail, documento e telefone.
- `record_fingerprint` e chave natural de agrupamento.
- Transactional outbox com indice esparso e publicacao inline best-effort.
- Persistencia single-table em DynamoDB, identica no local e na AWS.
- Logging estruturado em JSON com `correlation_id` propagado por `contextvars`.
- Metricas em processo com P50, P95 e P99.
- Gerador de dados sinteticos com taxas de duplicidade e de variante controladas.
- Suite com 169 testes (unitarios e integracao), 91% de cobertura.
- `docker compose` com DynamoDB Local, criacao idempotente de tabela e API.
- Documentacao: README, ARCHITECTURE, ROADMAP, COSTS, SECURITY, padroes de acesso,
  relatorio de testes e nota de performance.
- ADR-001 (DynamoDB Local), ADR-002 (identidade e idempotencia), ADR-003 (outbox).

### Corrigido

**Fase 4**

- **A API negava uma capacidade que tinha.** `/metrics` declarava
  `entity_resolution: not_implemented`, fixo no codigo desde a Fase 2; a Fase 5
  implementou a resolucao e nao atualizou o campo. Passou tres fases sem ser notado
  porque ninguem le aquele campo num `curl` — bastou exibi-lo num card. Agora e
  derivado do processador configurado, com teste de regressao.
- **Carregando era renderizado como vazio.** A fila de revisao dizia "nenhum par
  aguardando" enquanto o contador ao lado dizia 1. Um operador leria "nada a decidir"
  e seguiria em frente.
- **Bundle carregava o SDK do Cognito sem uso.** Importacao dinamica derrubou o bundle
  inicial de 869 kB para 238 kB.

**Fase 3**

- **O ADR-003 rejeitava event source mapping pelo motivo errado.** Alegava
  "long-polling continuo: custo com fila vazia". O calculo desmente: 1 a 5 pollers com
  long poll de 20s geram 130 mil a 650 mil requisicoes/mes, dentro da franquia
  permanente de 1 milhao do SQS. O motivo real e que ele processa sozinho, desfazendo
  a execucao sob demanda. Decisao mantida, justificativa corrigida.
- **O COSTS.md subestimava o DynamoDB.** Dizia "~US$ 0" para On-Demand. A franquia
  cobre 25 GB e 25 WCU/RCU **provisionados**, nao requisicoes On-Demand. Custo real:
  ~US$ 0,15 por 10 mil registros, linear no volume — o que muda a conversa nos testes
  de carga.
- **O pacote Lambda levava o servidor Uvicorn.** `uvloop` sozinho pesava 16 MB e a
  Lambda nao usa nenhum deles: o Mangum fala ASGI direto. Pacote caiu de 11 MB para
  6,1 MB.

**Fase 5**

- **O marcador de processamento impedia melhoria.** Com `PROCESSED#<record_id>` sem
  versao, trocar o processador nao reprocessaria nada: o marcador antigo existe e a
  escrita condicional recusaria. O acervo ficaria fora da resolucao em silencio,
  contado como `ja_processado`. Corrigido pelo ADR-007.
- **Nome do meio omitido pontuava zero.** "Enzo Cunha" contra "Enzo Gabriel da Cunha"
  dava 0,000: Jaro-Winkler e `token_sort_ratio` ficam abaixo do piso. Um par com
  documento, e-mail e telefone identicos caia para revisao. Corrigido com criterio de
  subconjunto de tokens, elevando o recall de 0,982 para 1,000 sem introduzir falso
  positivo.
- **O gerador produzia variantes triviais.** Alterar apenas o telefone tornava a
  avaliacao inutil. Agora varia nome, e-mail, documento e campos ausentes.

**Fase 2**

- **Recibo de fila era por lote, nao por mensagem.** `DELETE WHERE receipt = ?` apagava
  todas as mensagens do lote ao confirmar a primeira: um worker que caisse no meio
  perderia as restantes sem processa-las, e uma unica falha mandaria o lote inteiro para
  a DLQ.
- **SQLite em WAL sobre bind mount do macOS** produzia reentregas espurias (167 entregas
  para 157 mensagens) quando host e container acessavam o mesmo arquivo. A fila passou
  para volume nomeado, com acesso exclusivo pelo container. As reentregas nao causaram
  efeito duplicado — a escrita condicional do ADR-005 as absorveu.
- **Volume nomeado nascia pertencente a root**, impedindo o processo sem privilegios de
  abrir o banco. O `chown` passou para o Dockerfile.
- **`executescript` dentro de transacao explicita** falhava ao confirmar.
- **`journal_mode=WAL` antes de `busy_timeout`** falhava com "database is locked" sob
  abertura concorrente de conexoes.

**Fase 1**

- **Desenho de idempotencia revisto antes da implementacao.** A proposta original
  derivava a chave de idempotencia da chave natural do registro, o que descartaria
  silenciosamente atualizacoes legitimas da mesma entidade. Substituida pela separacao
  de tres conceitos do ADR-002.
- `Decimal` devolvido pelo DynamoDB quebrava a serializacao da resposta de replay.
- `ExpressionAttributeNames` vazio e recusado pelo DynamoDB, quebrando a retentativa
  do outbox.
- Servico e repositorio liam `outbox_shards` separadamente; valores divergentes
  deixariam eventos orfaos. A configuracao passou a ser injetada uma unica vez.
- Gerador produzia e-mails invalidos a partir de nomes com acentos e espacos.

### Seguranca

- Credenciais locais explicitas e falsas impedem que o ambiente de desenvolvimento
  alcance a AWS real por configuracao equivocada.
- Respostas de erro nao expoem stack traces, nomes de tabela ou ARNs.
- `extra="forbid"` nos contratos de entrada: campo desconhecido e recusado, nao ignorado.
