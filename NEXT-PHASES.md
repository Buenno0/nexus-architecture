# Fases restantes — Nexus Architecture

Documento de planejamento das Fases 3 a 8. Complementa o [ROADMAP.md](ROADMAP.md), que
lista os itens; aqui estao o contexto, as decisoes ja tomadas que delimitam cada fase,
as decisoes ainda em aberto e os criterios de aceite.

Ultima atualizacao: 2026-11-06, ao concluir a Fase 5.

> A Fase 5 foi concluida fora da ordem numerica, por nao depender da nuvem. Seu
> planejamento permanece abaixo como registro; o resultado esta em
> [docs/testing/phase-5-report.md](docs/testing/phase-5-report.md).

---

## Onde estamos

| Fase | Modulo | Situacao |
|---|---|---|
| 1 | Nexus Ingestion | **Concluida** |
| 2 | Nexus Queue Engine | **Concluida** |
| 3 | Cloud Infrastructure | Nao iniciada |
| 4 | Nexus Control Center | Nao iniciada |
| 5 | Nexus Entity Resolution | **Concluida** |
| 6 | Nexus Observability | Parcial |
| 7 | Performance Engineering | Nao iniciada |
| 8 | Finalizacao | Nao iniciada |

**Entregue ate aqui:** API de ingestao com validacao, normalizacao e idempotencia por
operacao; transactional outbox com indice esparso; fila local com visibility timeout,
retentativa, DLQ e redrive; worker idempotente sob demanda; endpoints operacionais;
267 testes com 93% de cobertura.

**Nenhum recurso de nuvem foi provisionado. Custo acumulado: US$ 0,00.**

### O que ja esta pronto e reduz o escopo das fases seguintes

Estas decisoes foram tomadas cedo justamente para que as fases seguintes fossem
mudanca de configuracao, nao reescrita:

- **`QueueClient` e `RecordRepository` sao abstratos.** A Fase 3 troca as
  implementacoes; a logica de negocio nao muda.
- **`NEXUS_ENV` e `NEXUS_QUEUE_BACKEND` decidem o ambiente num unico ponto.** Nao ha
  `if` de ambiente espalhado pelo codigo.
- **DynamoDB Local usa a mesma API do gerenciado**, incluindo `TransactWriteItems` e
  indices esparsos ([ADR-001](docs/adr/ADR-001-dynamodb-local.md)).
- **`RecordProcessor` e injetavel.** A Fase 5 substitui o processador sem tocar no
  motor de filas.
- **`correlation_id` ja atravessa API, outbox, fila e worker.** A Fase 6 passa a
  agrega-lo, nao a implementa-lo.
- **Os endpoints `/v1/ops/*` ja existem.** A Fase 4 tem o que chamar.

---

## Fase 3 — Cloud Infrastructure

### Objetivo

Executar a mesma plataforma na AWS, sob demanda, sem servidor permanentemente ligado.

### O que construir

| Componente | Decisao |
|---|---|
| IAM | Uma role por funcao, privilegio minimo: acesso apenas a tabela e fila que usa |
| DynamoDB | On-Demand, single-table, com os tres GSI de `docs/architecture/access-patterns.md` |
| SQS | Fila principal + DLQ com `maxReceiveCount = 3` |
| Lambda ingestao | FastAPI adaptado por Mangum — o mesmo codigo que roda local |
| Lambda worker | Invocacao explicita, **sem** event source mapping |
| API Gateway | HTTP API, rate limiting, CORS restrito a origem do dashboard |
| CloudWatch | Retencao de logs de 7 dias |
| Budget | Alerta em US$ 5 |

Novas implementacoes: `queue/sqs.py` (`SqsQueue`) e o empacotamento das Lambdas.
Nenhuma mudanca em `ingestion/`, `persistence/models.py` ou `queue/worker.py`.

### Decisoes ja tomadas

- **Sem VPC privada.** Isolamento por IAM, nao por rede — NAT Gateway custaria ~US$ 32/mes
  parado ([COSTS.md](COSTS.md)).
- **Sem event source mapping SQS -> Lambda.** Faz long-polling continuo: custo com fila
  vazia ([ADR-003](docs/adr/ADR-003-transactional-outbox.md)).
- **DynamoDB On-Demand, nunca Provisioned.** Provisioned cobra capacidade reservada.
- **A restricao de ambiente unico da fila desaparece aqui.** SQS e servico de rede, sem
  arquivo compartilhado ([ADR-004](docs/adr/ADR-004-fila-local-sqlite.md)).

### Decisoes em aberto

1. **Quem aciona a Lambda do worker?** Sem event source mapping, alguem precisa chamar.
   Se for apenas o Control Center, uma mensagem que falha quando ninguem esta olhando o
   dashboard fica parada indefinidamente. A garantia de retentativa da Fase 2 depende de
   **alguem consumir de novo** — sem consumidor, a mensagem apenas espera.
   Opcoes: invocacao manual; EventBridge Scheduler de baixa frequencia (contraria
   parcialmente o modelo sob demanda, mas com custo previsivel); event source mapping
   com concorrencia reservada minima.

2. **Autenticacao.** Bloqueante: os endpoints `/v1/ops/*` disparam trabalho e hoje sao
   abertos. Opcoes: chave de API no API Gateway; Cognito; assinatura em header.

3. **Infraestrutura como codigo.** Terraform, AWS SAM, CDK ou AWS CLI versionado em
   script. Rejeitado na Fase 1 por ser cerimonia sem infraestrutura; agora faz sentido.

4. **Empacotamento das Lambdas.** Zip com dependencias ou imagem de container. Zip tem
   cold start menor; container acomoda dependencias maiores.

### Criterios de aceite

- [ ] `POST` em `api.nexus.mateus-bueno.dev` responde `202` com registro persistido no DynamoDB
- [ ] Mensagem chega ao SQS e o worker a consome quando invocado
- [ ] Reentrega continua produzindo um unico `ProcessingResult`
- [ ] Mensagem envenenada vai para a DLQ apos 3 tentativas
- [ ] Nenhuma Lambda executa sem invocacao explicita
- [ ] Budget configurado e alerta testado
- [ ] Retencao de logs em 7 dias confirmada
- [ ] Custo observado por 7 dias dentro da estimativa
- [ ] IAM sem `*` em `Action` ou `Resource`

### Riscos

| Risco | Impacto | Mitigacao |
|---|---|---|
| Custo inesperado | Alto | Apresentar custo e obter autorizacao antes de criar qualquer recurso |
| Concorrencia descontrolada | Alto | `ReservedConcurrentExecutions` por funcao |
| Cold start distorce medicoes | Medio | Medir e reportar separadamente (Fase 7) |
| Divergencia local/nuvem | Medio | Mesma suite de testes contra ambos os ambientes |
| Credencial exposta | **Critico** | IAM Roles, nunca chaves estaticas ([SECURITY.md](SECURITY.md)) |

### Custo

Estimativa: **US$ 0,50 a US$ 2,00/mes**, sendo a hosted zone do Route 53 (US$ 0,50) o
unico custo fixo. Detalhamento em [COSTS.md](COSTS.md).

**Nenhum recurso sera criado sem apresentacao previa de custo e autorizacao explicita.**

---

## Fase 4 — Nexus Control Center

### Objetivo

Interface que mostra o comportamento real da infraestrutura e permite opera-la sob demanda.

### O que construir

React 19 + TypeScript + Vite + TanStack Query + Recharts, hospedado na Vercel em
`nexus.mateus-bueno.dev`.

Cinco telas: **Overview**, **API Monitoring**, **Queue Monitoring**, **Worker
Monitoring**, **Entity Resolution**.

Controles operacionais, todos ligados a endpoints que ja existem:

| Controle | Endpoint |
|---|---|
| Gerar 100 / 1.000 / 10.000 registros | `POST /v1/records/*` (teto rigido de 10.000) |
| Despachar outbox | `POST /v1/ops/dispatch` |
| Processar fila | `POST /v1/ops/process` |
| Simular falhas | `NEXUS_FAILURE_INJECTION_RATE` |
| Devolver da DLQ | `POST /v1/ops/redrive` |

### Decisoes ja tomadas

- **Toda metrica vem de endpoint real.** Modulo inexistente mostra `—` com rotulo
  *not implemented*. **Nunca um numero inventado.** Dados de demonstracao, se existirem,
  levam banner `DEMO DATA`.
- **Estetica de painel de engenharia:** tema escuro, monoespacada para numeros,
  densidade alta, sem ilustracao decorativa.
- **Nenhuma logica de negocio no frontend.** E cliente da API, nada mais.
- **Toda operacao cara pede confirmacao** e tem teto embutido.

### Decisoes em aberto

1. **Distinguir metricas autoritativas das efemeras.** `/v1/ops/queue` vem do
   armazenamento; `/metrics` sao contadores em processo que zeram no reinicio. A
   interface precisa deixar isso visivel, nao misturar.
2. **Atualizacao automatica.** Polling com intervalo configuravel e o mais simples e
   coerente com o modelo sob demanda; WebSocket exigiria conexao permanente.
3. **Geracao de registros.** No navegador ou por endpoint que chama o gerador no backend.

### Criterios de aceite

- [ ] Cinco telas exibindo apenas dados reais
- [ ] Modulos nao implementados claramente marcados
- [ ] Controles operacionais funcionando com teto aplicado
- [ ] Deploy na Vercel com dominio configurado
- [ ] CORS restrito a origem do dashboard
- [ ] Interface utilizavel sem conhecimento previo do backend

### Risco principal

Dashboard que **parece** mostrar metricas de plataforma quando mostra contadores de um
processo. Mitigacao: rotular a origem de cada numero na propria interface.

---

## Fase 5 — Nexus Entity Resolution

### Objetivo

Determinar quais observacoes representam a mesma entidade do mundo real, com pontuacao
auditavel.

### O que construir

Substituir `DefaultProcessor` por um resolvedor. **Worker, fila e persistencia nao
mudam** — o contrato `RecordProcessor` ja existe para isso.

| Modulo | Responsabilidade |
|---|---|
| `resolution/blocking.py` | Selecionar candidatos sem varrer a base |
| `resolution/comparators.py` | Exato, Jaro-Winkler, Levenshtein, e-mail, documento |
| `resolution/scoring.py` | Pesos configuraveis, score 0–1 |
| `resolution/engine.py` | Decisao em tres faixas e persistencia do vinculo |

### Decisoes ja tomadas

- **Tres faixas, nunca duas:** `MATCH`, `POSSIBLE_MATCH`, `NO_MATCH`.
  **`POSSIBLE_MATCH` nunca funde automaticamente.**
- **A normalizacao da ingestao e conservadora de proposito.** Acentos e caixa de nomes
  foram preservados porque sao sinal para o resolvedor, nao ruido
  ([ADR-002](docs/adr/ADR-002-identidade-e-idempotencia.md)).
- **`natural_key` ja existe como chave de agrupamento**, nao de unicidade — e o ponto de
  partida do blocking.
- **Observacoes sao imutaveis.** O resolvedor cria vinculos, nunca sobrescreve registros.
- **Blocking e obrigatorio antes de comparar.** Comparacao O(n²) e inviavel.
- **RapidFuzz** para similaridade: C++ sob o capo, ordens de magnitude mais rapido.

### Decisoes em aberto

1. **Modelagem da entidade canonica no DynamoDB.** Item proprio com vinculos, ou vinculos
   como itens filhos sob a observacao? Exige novos padroes de acesso e ADR.
2. **Pesos iniciais do score.** Documento identico deve bastar para `MATCH`? E-mail
   identico com nomes diferentes?
3. **Transitividade.** Se A corresponde a B e B a C, mas A nao a C, o que acontece?
4. **Como medir qualidade** sem rotulo verdadeiro. O gerador sintetico pode produzir
   pares conhecidos para servir de gabarito.

### Criterios de aceite

- [ ] Blocking reduz candidatos de forma mensuravel
- [ ] Score detalhado persistido campo a campo, auditavel
- [ ] `POSSIBLE_MATCH` fica pendente, nunca funde sozinho
- [ ] Limiares configuraveis sem alterar codigo
- [ ] Relatorio de falsos positivos e negativos sobre dados sinteticos rotulados
- [ ] Nenhuma mudanca em `queue/worker.py`

### Risco principal

**Falso positivo e o risco critico do projeto inteiro.** Fundir duas pessoas distintas
corrompe dados de forma dificil de detectar e de reverter. Por isso tres faixas, score
auditavel e nenhuma fusao automatica em caso duvidoso.

---

## Fase 6 — Nexus Observability

### Objetivo

Enxergar o comportamento do sistema distribuido, nao apenas se ele responde.

### O que ja existe

- Logs estruturados em JSON, uma linha por evento
- `correlation_id` propagado da API ate o worker, inclusive entre processos
- Contadores e histogramas com P50, P95 e P99
- `/metrics` declarando `scope: in_process` e o estado de cada modulo
- Profundidade de fila vinda do armazenamento, nao de memoria

### O que falta

- Agregacao no CloudWatch, substituindo contadores em processo
- Consulta que reconstroi a jornada completa de um registro por `correlation_id`
- Metricas customizadas: profundidade de fila, idade da DLQ, backlog do outbox
- Alarmes: DLQ nao vazia, backlog crescendo, taxa de erro acima do limite
- Identificacao de gargalos a partir de dados, nao de suposicao

### Decisoes ja tomadas

- **Percentis, nao media.** A media esconde a cauda: 95 requisicoes de 10 ms e 5 de 2 s
  dao media de 110 ms e parecem saudaveis.
- **Metricas em processo nunca sao apresentadas como metricas de plataforma.**
- **Cold start e medido e reportado separadamente**, nao diluido.

### Decisoes em aberto

1. **CloudWatch Embedded Metric Format** (metricas extraidas do proprio log, sem chamada
   extra) ou `PutMetricData`.
2. **Tracing distribuido.** X-Ray ou OpenTelemetry — vale o custo, ou `correlation_id`
   em log estruturado ja resolve neste porte?
3. **Retencao.** 7 dias atende; alarmes historicos precisariam de mais.

### Criterios de aceite

- [ ] Uma consulta reconstroi a jornada completa de um registro
- [ ] Metricas de fila e DLQ visiveis no CloudWatch
- [ ] Alarme de DLQ nao vazia testado com falha real
- [ ] Gargalo identificado a partir de dados e documentado
- [ ] Retencao de 7 dias confirmada e dentro da franquia

---

## Fase 7 — Performance Engineering

### Objetivo

Medir o comportamento sob carga e identificar gargalos com evidencia.

### O que ja existe

`tests/load/locustfile.py` com quatro cenarios de pesos distintos — registro novo,
conteudo duplicado, replay e listagem. Um teste que so envia registros novos mede
apenas o caminho mais caro e esconde quanto replay e deduplicacao custam.

### O que falta

- Execucao com volumes crescentes (100, 1.000, 10.000)
- Medicao contra a AWS, nao so local
- Teste de concorrencia real na ingestao
- Analise de gargalos: API, DynamoDB, fila ou worker
- Relatorios versionados em `docs/performance/`

### Decisoes ja tomadas

- **Numeros locais nao valem como previsao.** DynamoDB Local nao aplica limites de
  throughput, nao simula rede e nao cobra.
- **Cold start reportado separadamente.**
- **P95 e P99 sempre, media nunca sozinha.**

### Medicao preliminar (Fase 1, local, 500 requisicoes sequenciais)

| p50 | p95 | p99 | max |
|---|---|---|---|
| 4,0 ms | 6,1 ms | 11,6 ms | 36,6 ms |

### Decisoes em aberto

1. **Qual volume justifica o custo** de medir contra a AWS?
2. **Particao quente do `gsi_recency`** — a Fase 7 pode confirmar se o limite de
   1.000 WCU/s e alcancado nos volumes do projeto. Se nao for, a mitigacao por sharding
   continua desnecessaria e isso vira dado, nao suposicao.
3. **Onde executar o Locust** para nao medir a propria maquina de origem.

### Criterios de aceite

- [ ] Resultados para tres volumes distintos
- [ ] Throughput, P50, P95 e P99 por cenario
- [ ] Gargalo identificado com evidencia
- [ ] Cold start quantificado separadamente
- [ ] Relatorio em `docs/performance/` com metodologia e limitacoes
- [ ] Custo da campanha de carga registrado em `COSTS.md`

---

## Fase 8 — Finalizacao

### Objetivo

Deixar o projeto compreensivel e reproduzivel por quem nao participou da construcao.

### O que falta

- Diagramas de arquitetura (hoje so existem diagramas em texto)
- README final com demonstracao completa
- Consolidacao dos ADRs e revisao de decisoes superadas
- CI/CD no GitHub Actions: lint, mypy, testes unitarios e de integracao
- `docs.nexus.mateus-bueno.dev`
- Demonstracao funcional gravada ou roteirizada
- Relatorio consolidado de desempenho
- **Documentacao explicita das limitacoes**

### Decisoes ja tomadas

- **CI ficou fora da Fase 1 por escolha de escopo.** Entra aqui.
- **Limitacoes sao parte da entrega**, nao nota de rodape. Cada relatorio de fase ja
  tem a sua secao.
- **Nenhuma capacidade nao implementada e declarada** em lugar nenhum.

### Criterios de aceite

- [ ] CI executando lint, mypy e testes a cada push
- [ ] Diagramas cobrindo arquitetura, fluxo de dados e infraestrutura AWS
- [ ] README permitindo a um terceiro subir o projeto do zero
- [ ] ADRs consolidados, com decisoes superadas marcadas como tal
- [ ] Documentacao publicada
- [ ] Demonstracao reproduzivel
- [ ] Limitacoes documentadas por fase
- [ ] Custo real acumulado registrado

---

## Dependencias entre as fases

```
Fase 3 (AWS) ────┬──> Fase 4 (Control Center)   precisa de API publica e autenticada
                 ├──> Fase 6 (Observability)    precisa do CloudWatch
                 └──> Fase 7 (Performance)      medicao real precisa da nuvem

Fase 5 (Entity Resolution)   independente das demais: substitui o processador
                             e pode ser feita antes ou depois da Fase 3

Fase 8 (Finalizacao)         depende de todas
```

**A Fase 5 nao depende da nuvem.** Se o objetivo for reduzir exposicao a custo, ela pode
vir antes da Fase 3 — roda inteiramente local, sobre a infraestrutura ja existente.

---

## Resumo de custo

| Fase | Custo | Observacao |
|---|---|---|
| 1 e 2 | US$ 0,00 | Concluidas, integralmente locais |
| 3 | US$ 0,50 – 2,00/mes | Unico custo fixo: hosted zone do Route 53 |
| 4 | US$ 0,00 | Vercel no plano gratuito |
| 5 | US$ 0,00 | Local; na AWS, apenas leitura adicional no DynamoDB |
| 6 | US$ 0,00 | Dentro da franquia do CloudWatch |
| 7 | Variavel | Depende do volume; registrar antes de executar |
| 8 | US$ 0,00 | GitHub Actions gratuito em repositorio publico |

**Compromisso mantido:** nenhum recurso pago sera criado sem apresentacao previa de
custo estimado, limites, franquias e riscos — e sem autorizacao explicita.
