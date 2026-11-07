# Roadmap — Nexus Architecture

Este documento lista os itens de cada fase. O contexto, as decisoes em aberto e os
criterios de aceite das fases ainda nao iniciadas estao em
[NEXT-PHASES.md](NEXT-PHASES.md).

Uma fase por vez. Uma fase so e concluida quando seus criterios de aceite sao
verificaveis e verificados. Codigo escrito nao e funcionalidade entregue.

---

## Fase 1 — Nexus Ingestion  *(concluida)*

API de entrada com validacao, normalizacao, idempotencia e outbox transacional.

- [x] `POST /v1/records/person` e `/v1/records/organization`
- [x] `GET /v1/records/{id}` e `GET /v1/records` paginado
- [x] `GET /health` e `GET /metrics`
- [x] Header `Idempotency-Key` obrigatorio; replay e `409` implementados
- [x] Normalizacao de nome, email, documento e telefone
- [x] `record_fingerprint` e chave natural
- [x] Transacao atomica: observacao + outbox + idempotencia
- [x] Publicacao inline best-effort com limpeza do `pending_shard`
- [x] Logging estruturado com `correlation_id`
- [x] Gerador de dados sinteticos
- [x] Suite de testes com cobertura >= 85%
- [x] `docker compose up` sobe tudo do zero

**Nao inclui:** nuvem, frontend, entity resolution real.

---

## Fase 2 — Nexus Queue Engine  *(concluida)*

- [x] Fila local sobre SQLite com visibility timeout
- [x] Dispatcher de outbox consumindo o GSI esparso
- [x] Worker com processamento em lotes
- [x] Idempotencia no consumo (marcador de processamento)
- [x] Retentativas com backoff exponencial
- [x] Dead Letter Queue e redrive
- [x] Injecao de falhas para validar recuperacao
- [x] Teste de reentrega da mesma mensagem
- [x] Endpoints operacionais `/v1/ops/*` para a Fase 4

**Nao inclui:** Entity Resolution. O processador executa mecanica de pipeline e declara
`entity_resolution: not_implemented` no proprio resultado.

---

## Fase 3 — Cloud Infrastructure

- [ ] IAM com privilegio minimo
- [ ] DynamoDB On-Demand + GSI esparso
- [ ] SQS + DLQ (`maxReceiveCount = 3`)
- [ ] Lambda de ingestao via Mangum + API Gateway HTTP API
- [ ] Lambda de worker com invocacao explicita (sem event source mapping)
- [ ] CloudWatch Logs com retencao de 7 dias
- [ ] AWS Budget com alerta
- [ ] Limites de concorrencia por funcao

**Bloqueio:** nenhum recurso pago sera criado sem apresentacao previa de custo e
autorizacao explicita.

---

## Fase 4 — Nexus Control Center

- [ ] React + TypeScript + Vite
- [ ] Overview, API, Queue, Worker, Entity Resolution
- [ ] Metricas reais; modulos ausentes exibem `—` com rotulo *not implemented*
- [ ] Controles operacionais com limites rigidos
- [ ] Deploy na Vercel

---

## Fase 5 — Nexus Entity Resolution

- [ ] Blocking para selecao de candidatos
- [ ] Comparadores: exato, Jaro-Winkler, Levenshtein, email, documento
- [ ] Normalizacao de nomes
- [ ] Score ponderado e configuravel
- [ ] Decisao em tres faixas: MATCH / POSSIBLE_MATCH / NO_MATCH
- [ ] `POSSIBLE_MATCH` nunca funde automaticamente
- [ ] Score detalhado persistido para auditoria
- [ ] Analise de falsos positivos e negativos

---

## Fase 6 — Nexus Observability

- [ ] Rastreamento fim a fim por `correlation_id`
- [ ] Metricas de throughput, latencia e falhas
- [ ] Histograma com P50, P95, P99
- [ ] Identificacao de gargalos
- [ ] Historico de execucao

---

## Fase 7 — Performance Engineering

- [ ] Cenarios Locust por volume
- [ ] Medicao de throughput e latencia
- [ ] Testes de concorrencia
- [ ] Relatorio em `docs/performance/`
- [ ] Separacao explicita de cold start nas medicoes AWS

---

## Fase 8 — Finalizacao

- [ ] Documentacao tecnica completa
- [ ] Diagramas de arquitetura
- [ ] README final
- [ ] ADRs consolidados
- [ ] CI/CD
- [ ] Demonstracao funcional
- [ ] Documentacao explicita de limitacoes
