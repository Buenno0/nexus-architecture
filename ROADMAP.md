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

## Fase 3 — Cloud Infrastructure  *(validada na AWS e destruida)*

- [x] IAM com privilegio minimo — nenhum curinga aberto em Action ou Resource
- [x] DynamoDB On-Demand com os 4 GSIs, incluindo os esparsos
- [x] SQS + DLQ com `maxReceiveCount = 3`
- [x] Lambda de ingestao via Mangum + API Gateway HTTP API
- [x] Lambda de worker com invocacao explicita (sem event source mapping)
- [x] Cognito User Pool com authorizer JWT
- [x] EventBridge Scheduler como rede de seguranca
- [x] CloudWatch Logs com retencao de 7 dias
- [x] AWS Budget com alertas em US$ 5, US$ 10 e por previsao
- [x] Limites de concorrencia — a cota da conta e o teto efetivo
- [x] Empacotamento cruzado para Linux arm64
- [x] Runbook de deploy e de destruicao
- [x] **Implantado em 07/11/2026** apos autorizacao explicita
- [x] **Validado na nuvem**: saude, autenticacao JWT, ingestao, consumo e resolucao
- [x] **Destruido em 09/11/2026** — conta verificada limpa em 10 categorias
- [ ] Dominio proprio e certificado ACM — Fase 4
- [ ] Medicao sob carga — Fase 7

**Custo real dos tres dias no ar: US$ 0,0001.** Nenhum recurso remanescente.

O deploy real revelou oito defeitos que nenhum teste local pegaria, catalogados em
[docs/testing/phase-3-report.md](docs/testing/phase-3-report.md) — entre eles um budget
que nunca teria disparado e uma recomendacao minha de custo que sairia a US$ 56,94/mes.

**Bloqueio mantido:** nenhum recurso pago sera criado sem apresentacao previa de custo e
autorizacao explicita.

---

## Fase 4 — Nexus Control Center  *(concluida, exceto o deploy)*

- [x] React 19 + TypeScript strict + Vite
- [x] Overview, API, Queue, Worker e Entity Resolution
- [x] **Todo numero declara a origem**: persistido, processo ou sessao
- [x] Metrica sem fonte aparece explicada, nunca inventada
- [x] Carregando nunca e renderizado como vazio
- [x] Falha mostra erro com `correlation_id`, nunca numero velho
- [x] Controles operacionais com teto e confirmacao
- [x] Gerador sintetico no navegador, com variantes realistas
- [x] Fila de revisao com evidencia campo a campo
- [x] CORS no backend, com recusa de `*`
- [x] 96 testes, 80,5% de cobertura
- [ ] Deploy na Vercel — depende de reaplicar a infraestrutura AWS

Ver [docs/testing/phase-4-report.md](docs/testing/phase-4-report.md) e
[ADR-009](docs/adr/ADR-009-control-center.md).

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
