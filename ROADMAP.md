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
- [ ] Medicao sob carga **na nuvem** — a Fase 7 mediu local; a AWS exige reaplicar a infraestrutura e aumentar a cota de concorrencia

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

## Fase 5 — Nexus Entity Resolution  *(concluida)*

- [x] Blocking para selecao de candidatos
- [x] Comparadores: exato, Jaro-Winkler, Levenshtein, email, documento
- [x] Normalizacao de nomes
- [x] Score ponderado e configuravel
- [x] Decisao em tres faixas: MATCH / POSSIBLE_MATCH / NO_MATCH
- [x] `POSSIBLE_MATCH` nunca funde automaticamente
- [x] Score detalhado persistido para auditoria
- [x] Analise de falsos positivos e negativos

Recall 1,0000 e precisao mantida apos o ajuste de `token_set_ratio` — **contra o
gabarito sintetico**, cujas variacoes o proprio gerador criou. O numero mede o
resolvedor contra este conjunto, nao contra dados reais. Ver
[docs/testing/phase-5-report.md](docs/testing/phase-5-report.md) e
[ADR-006](docs/adr/ADR-006-entity-resolution.md).

> Esta secao ficou marcada como pendente ate a Fase 6, mesmo com a fase concluida antes
> da Fase 3. Mais um caso do que o ADR-010 chama de estado declarado envelhecendo em
> silencio — e o segundo no mesmo arquivo, depois da Fase 3.

---

## Fase 6 — Nexus Observability  *(concluida)*

- [x] Rastreamento fim a fim **atravessando processos**, por `record_id`
- [x] Seis marcos duraveis com TTL de 7 dias, sem indice novo
- [x] Metricas de throughput, latencia e falhas
- [x] Histograma com P50, P95, P99
- [x] `end_to_end_ms`: separa processamento lento de fila acumulando
- [x] Historico de execucao **persistido**, sobrevive a recarregar e a reiniciar
- [x] Seis alertas derivados do estado real, nunca configurados a mao
- [x] Tela Trail, faixa de alertas e graficos persistidos no Control Center
- [x] Toda escrita de observabilidade e best-effort e nunca derruba o observado
- [x] 546 testes Python (92% em `observability`), 115 no dashboard
- [ ] Amostragem pelo EventBridge Scheduler validada na nuvem — depende da Fase 3
- [x] Impacto das escritas de trilha sob carga — medido na Fase 7: **4 ms, 25% do caminho de ingestao**

A verificacao achou seis defeitos, entre eles um numero que eu havia publicado no
relatorio da Fase 4 sem verificar e um grafico que desmentia a propria legenda. Ver
[docs/testing/phase-6-report.md](docs/testing/phase-6-report.md) e
[ADR-010](docs/adr/ADR-010-observabilidade.md).

**Nao inclui:** OpenTelemetry, backend de traces, CloudWatch Alarms. A trilha e uma
ajuda para investigar, **nao um registro de auditoria**.

---

## Fase 7 — Performance Engineering  *(concluida, exceto a medicao na nuvem)*

- [x] Cenarios Locust por volume, com isolamento por caminho
- [x] Medicao de throughput e latencia, sempre com P50, P95 e P99
- [x] Testes de concorrencia contra o DynamoDB real
- [x] **Gargalo identificado com evidencia**: o caminho de escrita da ingestao
- [x] Decomposicao do custo: nucleo 56%, trilha 25%, publicacao 25%
- [x] Particao quente do `gsi_recency` fechada com numero
- [x] Repeticao e dispersao: nenhum numero comparativo vem de uma corrida so
- [x] Relatorio e metodologia em `docs/performance/`
- [x] Custo da campanha registrado em COSTS.md: **US$ 0,00**
- [ ] Cold start quantificado — depende de reaplicar a infraestrutura AWS
- [ ] Medicao sob rede real — idem, e exige aumento de cota de concorrencia

**Teto por caminho:** `replay` 571,5 req/s · `duplicata` 247,8 · `novo` 103,8. Mesma
pilha, mesmo processo: o limite e o trabalho de escrita, nao o custo de atender.

A fase registrou **quatro erros meus de medicao** — conclusao tirada de uma corrida
unica, alternancia que nao cancelava a deriva do acervo, isolamento de cenario que nao
isolava, e custo de trabalho medido sob saturacao. Estao em
[docs/testing/phase-7-report.md](docs/testing/phase-7-report.md), secao 6, porque sao o
conteudo da fase e nao um apendice constrangedor.

---

## Fase 8 — Finalizacao  *(concluida, exceto a execucao do CI)*

- [x] **Diagramas de arquitetura** em Mermaid, versionados em
      [docs/architecture/diagramas.md](docs/architecture/diagramas.md): modulos,
      ingestao, outbox esparso, ciclo de vida da mensagem, trilha entre processos,
      modelo single-table e a infraestrutura AWS (marcada como destruida no titulo)
- [x] **ADRs consolidados** em [docs/adr/README.md](docs/adr/README.md), com as tres
      decisoes de alcance alterado marcadas no proprio cabecalho: 005 emendada pela
      007, 009 parcialmente superada pela 010, 008 implantada e destruida
- [x] **Demonstracao reproduzivel** (`scripts/demo.sh`): onze atos, roteirizada e
      executavel, que **falha** quando o estado nao corresponde a narracao
- [x] **README final**, com a demonstracao em um comando
- [x] **Relatorio consolidado** em [docs/testing/README.md](docs/testing/README.md),
      separando limitacoes vencidas das que continuam valendo
- [x] **Limitacoes agrupadas por causa**, distinguindo troca deliberada de pendencia
- [x] CI escrito: `.github/workflows/ci.yml` — ruff, mypy, suite Python completa com
      DynamoDB real, Control Center e `terraform validate`
- [x] **CI executando a cada push**: repositorio publicado em 12/11/2026 e primeira
      execucao verde nos quatro jobs ([run 43149734246](https://github.com/Buenno0/nexus-architecture/actions/runs/43149734246))
- [ ] Documentacao publicada em `docs.nexus.mateus-bueno.dev` — exige DNS e hospedagem,
      fora de escopo por decisao

Dois defeitos foram encontrados **executando** o roteiro, nao escrevendo-o: o servico
`api` nao tinha healthcheck, entao `docker compose up --wait` devolvia antes de a porta
abrir; e o laco de injecao de falha esperava um tempo fixo que o backoff exponencial
ultrapassava, de modo que os atos do alerta narravam um alarme que nunca acendeu.

---

## Fase 9 — Demonstracao publica  *(concluida em 12/11/2026)*

**https://nexus.mateus-bueno.dev**

Objetivo: um endereco que um interessado abre e **usa**, em vez de ler. A arquitetura
favorece isso de um jeito que poucas favorecem — nada processa sozinho, entao o
visitante apertando "processar fila" nao e um atalho para demonstrar o modelo de
execucao sob demanda: **e** o modelo.

### Feito (nenhum recurso de nuvem criado)

- [x] `POST /v1/demo/seed`: gera no servidor, com teto por chamada e teto acumulado
- [x] `src/nexus/demo/synthetic.py`: gerador sem Faker, porque o pacote da Lambda
      inclui so `src/nexus` e o Faker e dependencia de desenvolvimento
- [x] **Logica de variacao unificada** com `tools/generator.py` — duas definicoes de
      "a mesma entidade observada de outro jeito" divergiriam
- [x] `reserve_demo_quota`: checagem e incremento numa **unica escrita condicional**
- [x] Ingestao livre fechada **na aplicacao**, nao so no roteamento do API Gateway
- [x] Terraform: `demo_mode` troca as rotas, usuario convidado no Cognito
- [x] Polling do painel com `refetchIntervalInBackground: false` explicito
- [x] 21 testes novos, incluindo concorrencia contra o DynamoDB real

### Pendente — exige autorizacao e custa dinheiro

- [x] `terraform apply` — **41 recursos criados em 12/11/2026**, com autorizacao
      explicita. Verificado sem credencial: ingestao livre responde `404` (a rota nao
      existe) e as demais `401` (existem e exigem token)
- [x] Control Center publicado na Vercel, com login automatico de convidado
- [x] **Tres defeitos de infraestrutura corrigidos**, nenhum introduzido nesta fase:
      `USER_PASSWORD_AUTH` ausente no Cognito, `/v1/observability/*` fora do gateway,
      e `ANY` no `route_key` reprovando o preflight de CORS
- [x] Acervo inicial semeado: 300 registros, 231 processados, 45 entidades,
      **10 pares aguardando decisao humana**
- [x] Cold start medido: `api` 1.416 ms, `dispatcher` 732 ms, `worker` 573 ms.
      **n=1 por funcao** — registrado como observacao, nao como medicao
- [ ] Registrar o custo real — o Cost Explorer leva ate 24h, e a tag de alocacao so
      vale para uso posterior a ativacao

### Custo

**US$ 0,05 a US$ 0,15/mes** sem dominio proprio; **US$ 0,55 a US$ 0,65** com a hosted
zone do Route 53, que e o unico recurso do projeto que cobra estando parado.

Pior caso de abuso, com os tetos padrao: 5.000 registros, cerca de **US$ 0,04**.
