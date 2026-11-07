# Nexus Architecture

> Engineering distributed systems, one component at a time.

Plataforma experimental de engenharia de sistemas distribuidos. Demonstra como dados
provenientes de multiplas fontes podem ser recebidos, validados, normalizados,
processados de forma assincrona, correlacionados e monitorados.

**Todos os dados sao sinteticos.** Nenhum dado pessoal real e utilizado em qualquer etapa.

---

## Estado atual

| Modulo | Fase | Situacao |
|---|---|---|
| Nexus Ingestion | 1 | Implementado |
| Nexus Queue Engine | 2 | Implementado — fila, retry, DLQ, redrive |
| Cloud Infrastructure | 3 | Nao iniciado |
| Nexus Control Center | 4 | Nao iniciado |
| Nexus Entity Resolution | 5 | Nao iniciado |
| Nexus Observability | 6 | Parcial (logging estruturado) |
| Performance Engineering | 7 | Nao iniciado |

Nenhum recurso de nuvem foi provisionado. O projeto roda inteiramente na maquina local.

---

## Requisitos

- Python 3.13 (gerenciado por [uv](https://docs.astral.sh/uv/))
- Docker + Docker Compose
- make

## Execucao

```bash
cp .env.example .env     # ajuste se necessario
make up                  # sobe DynamoDB Local + API
make test                # suite completa de testes
make lint                # ruff + mypy strict
```

A API fica disponivel em `http://localhost:8080`.
Documentacao interativa (OpenAPI) em `http://localhost:8080/docs`.

## Endpoints (Fase 1)

| Metodo | Rota | Descricao |
|---|---|---|
| POST | `/v1/records/person` | Ingestao de registro de pessoa |
| POST | `/v1/records/organization` | Ingestao de registro de organizacao |
| GET | `/v1/records/{record_id}` | Consulta de registro |
| GET | `/v1/records` | Listagem paginada |
| GET | `/health` | Verificacao de saude |
| GET | `/metrics` | Metricas operacionais |

## Endpoints operacionais (Fase 2)

Nada processa sozinho: todo o modelo de custo depende de execucao sob demanda.

| Metodo | Rota | Descricao |
|---|---|---|
| POST | `/v1/ops/dispatch` | Publica eventos pendentes do outbox na fila |
| POST | `/v1/ops/process` | Consome um lote da fila |
| GET | `/v1/ops/queue` | Pendentes, em voo, DLQ e backlog do outbox |
| POST | `/v1/ops/redrive` | Devolve mensagens da DLQ para a fila |

```bash
make dispatch && make drain && make queue-stats
```

```bash
make fail-test RATE=0.5
```

### Header `Idempotency-Key` e obrigatorio nos POST

```bash
curl -X POST localhost:8080/v1/records/person \
  -H 'Content-Type: application/json' \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{
        "source": "demo",
        "full_name": "Maria Aparecida Souza",
        "email": "MARIA.SOUZA@Example.com ",
        "document": "123.456.789-09",
        "phone": "(11) 98765-4321"
      }'
```

| Situacao | Resposta |
|---|---|
| Header ausente | `400` |
| Corpo invalido | `422` |
| Mesma chave, mesmo corpo | `200` com a resposta armazenada |
| Mesma chave, corpo diferente | `409` |
| Mesmo conteudo ja observado | `200`, `status="duplicate"` |
| Observacao nova | `202`, `status="accepted"` |

Os tres conceitos de identidade (`idempotency_key`, `record_fingerprint` e entity
resolution) sao distintos por design — ver
[ADR-002](docs/adr/ADR-002-identidade-e-idempotencia.md).

## Dados sinteticos

```bash
make generate N=1000     # gera e envia 1000 registros sinteticos
```

## Documentacao

- [ARCHITECTURE.md](ARCHITECTURE.md) — desenho da plataforma
- [ROADMAP.md](ROADMAP.md) — fases de desenvolvimento
- [NEXT-PHASES.md](NEXT-PHASES.md) — planejamento das Fases 3 a 8
- [COSTS.md](COSTS.md) — estimativas e armadilhas de custo AWS
- [SECURITY.md](SECURITY.md) — postura de seguranca
- [CHANGELOG.md](CHANGELOG.md) — historico de mudancas
- [docs/architecture/access-patterns.md](docs/architecture/access-patterns.md) — modelagem DynamoDB
- [docs/testing/phase-1-report.md](docs/testing/phase-1-report.md) — testes da Fase 1
- [docs/testing/phase-2-report.md](docs/testing/phase-2-report.md) — testes da Fase 2
- [docs/performance/](docs/performance/) — medicoes
- [docs/adr/](docs/adr/) — registros de decisao arquitetural
  - [ADR-001](docs/adr/ADR-001-dynamodb-local.md) — DynamoDB Local em vez de PostgreSQL
  - [ADR-002](docs/adr/ADR-002-identidade-e-idempotencia.md) — Operacao, conteudo e entidade
  - [ADR-003](docs/adr/ADR-003-transactional-outbox.md) — Transactional outbox com GSI esparso
  - [ADR-004](docs/adr/ADR-004-fila-local-sqlite.md) — Fila local sobre SQLite
  - [ADR-005](docs/adr/ADR-005-idempotencia-no-consumo.md) — Idempotencia no consumo

## Limitacoes conhecidas

- **Nao ha autenticacao.** A API e aberta no ambiente local. Requisito da Fase 3.
- **A fila so pode ser acessada de dentro do container** — SQLite em WAL nao
  atravessa a fronteira host/VM no macOS. Ver [ADR-004](docs/adr/ADR-004-fila-local-sqlite.md).
- **Os endpoints `/v1/ops/*` nao tem autenticacao.** Fase 3.
- **Nao ha Entity Resolution.** O worker executa mecanica de pipeline e declara isso no
  proprio resultado. Fase 5.
- **Deduplicacao por conteudo e best-effort sob concorrencia** — o indice consultado e
  eventualmente consistente. A resolucao autoritativa de identidade e da Fase 5.
- **Metricas sao do processo**: zeram no reinicio e nao agregam entre replicas.
- Nenhum recurso de nuvem foi provisionado; nenhuma medicao local vale como previsao
  de desempenho ou custo na AWS.

Lista completa em [docs/testing/phase-2-report.md](docs/testing/phase-2-report.md).

Este projeto e experimental e **nao** deve ser tratado como sistema de producao.
