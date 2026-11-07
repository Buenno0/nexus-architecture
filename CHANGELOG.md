# Changelog

Formato baseado em [Keep a Changelog](https://keepachangelog.com/).

## [Nao lancado]

### Adicionado

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
