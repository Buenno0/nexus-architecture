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
| Cloud Infrastructure | 3 | **Implantado na AWS** — ~US$ 0,10/mes |
| Nexus Control Center | 4 | Nao iniciado |
| Nexus Entity Resolution | 5 | Implementado — precisao 1,000 / recall 1,000 em dados sinteticos |
| Nexus Observability | 6 | Parcial (logging estruturado) |
| Performance Engineering | 7 | Nao iniciado |

A plataforma roda localmente em Docker **e** na AWS, implantada em 07/11/2026 na
conta 541099637415 com 48 recursos e custo estimado de ~US$ 0,10/mes. A hosted zone do
Route 53 — unico custo fixo — nao foi criada. Ver
[docs/runbook-deploy.md](docs/runbook-deploy.md) e [COSTS.md](COSTS.md).

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

## Entity Resolution (Fase 5)

| Metodo | Rota | Descricao |
|---|---|---|
| GET | `/v1/resolution/entities/{id}` | Entidade, vinculos e evidencia de cada fusao |
| GET | `/v1/resolution/reviews` | Pares em duvida aguardando decisao |
| POST | `/v1/resolution/reviews/{pair_id}` | `confirm` funde, `reject` registra a recusa |
| GET | `/v1/resolution/stats` | Contadores duraveis de resolucao |
| POST | `/v1/ops/reprocess` | Reenfileira o acervo sob a versao corrente |

Tres faixas de decisao: `MATCH` funde, `POSSIBLE_MATCH` vai para revisao humana e
**nunca funde sozinho**, `NO_MATCH` nao faz nada.

```bash
make reprocess && make drain && make resolution
```

```bash
make reviews
```

## AWS (Fase 3) — implantada

```bash
make lambda
```

```bash
make tf-validate
```

Para destruir tudo:

```bash
cd infra/terraform && terraform destroy
```

Procedimento completo, incluindo criacao de operador no Cognito, em
[docs/runbook-deploy.md](docs/runbook-deploy.md).

### Medir a qualidade da resolucao

```bash
.venv/bin/python tools/generator.py --count 500 --duplicate-rate 0.15 --variant-rate 0.25 --post --seed 2026 --manifest gabarito.json
```

```bash
.venv/bin/python tools/evaluate_resolution.py --manifest gabarito.json
```

O gabarito liga cada registro a entidade verdadeira que o originou. Sem ele nao da para
afirmar que a resolucao funciona — apenas que ela roda.

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
- [docs/testing/phase-5-report.md](docs/testing/phase-5-report.md) — testes e qualidade da Fase 5
- [docs/performance/](docs/performance/) — medicoes
- [docs/adr/](docs/adr/) — registros de decisao arquitetural
  - [ADR-001](docs/adr/ADR-001-dynamodb-local.md) — DynamoDB Local em vez de PostgreSQL
  - [ADR-002](docs/adr/ADR-002-identidade-e-idempotencia.md) — Operacao, conteudo e entidade
  - [ADR-003](docs/adr/ADR-003-transactional-outbox.md) — Transactional outbox com GSI esparso
  - [ADR-004](docs/adr/ADR-004-fila-local-sqlite.md) — Fila local sobre SQLite
  - [ADR-005](docs/adr/ADR-005-idempotencia-no-consumo.md) — Idempotencia no consumo
  - [ADR-006](docs/adr/ADR-006-entity-resolution.md) — Blocking, pontuacao e clusterizacao
  - [ADR-007](docs/adr/ADR-007-versionamento-do-processador.md) — Versionamento do processador
  - [ADR-008](docs/adr/ADR-008-arquitetura-serverless.md) — Arquitetura serverless na AWS
- [docs/runbook-deploy.md](docs/runbook-deploy.md) — procedimento de deploy e destruicao

## Limitacoes conhecidas

- **Nao ha autenticacao.** A API e aberta no ambiente local. Requisito da Fase 3.
- **A fila so pode ser acessada de dentro do container** — SQLite em WAL nao
  atravessa a fronteira host/VM no macOS. Ver [ADR-004](docs/adr/ADR-004-fila-local-sqlite.md).
- **Os endpoints `/v1/ops/*` nao tem autenticacao.** Fase 3.
- **As metricas de qualidade da resolucao valem para dados sinteticos.** Dados reais
  trazem sujeira que o gerador nao imita.
- **Pesos e limiares de correspondencia sao parametros calibrados**, nao verdades.
- **Nao ha interface de revisao**, apenas endpoints. A tela e escopo da Fase 4.
- **Nao ha operacao de desfazer fusao.** A evidencia permite localizar a aresta
  culpada, mas reverte-la e manual.
- **O comportamento sob carga na AWS nao foi medido** — latencia, throttling e cold
  start no P99 sao escopo da Fase 7.
- **Nenhum dominio proprio configurado**: a API responde pelo endereco da AWS.
- **Deduplicacao por conteudo e best-effort sob concorrencia** — o indice consultado e
  eventualmente consistente. A resolucao autoritativa de identidade e da Fase 5.
- **Metricas sao do processo**: zeram no reinicio e nao agregam entre replicas.
- Nenhum recurso de nuvem foi provisionado; nenhuma medicao local vale como previsao
  de desempenho ou custo na AWS.

Lista completa em [docs/testing/phase-5-report.md](docs/testing/phase-5-report.md).

Este projeto e experimental e **nao** deve ser tratado como sistema de producao.
