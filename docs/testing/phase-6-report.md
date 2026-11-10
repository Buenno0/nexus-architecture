# Relatorio da Fase 6 — Nexus Observability

- **Data:** 10/11/2026
- **Ambiente:** local (DynamoDB Local + API em container, worker sob demanda)
- **Custo:** US$ 0,00. Nenhum recurso AWS foi criado.

## 1. O que foi implementado

| Entrega | Onde |
|---|---|
| Trilha durável por `record_id`, seis marcos, TTL de 7 dias | `persistence/models.py`, `dynamo.py`, `observability/trail.py` |
| `end_to_end_ms` no resultado e no histograma | `queue/worker.py`, `persistence/models.py` |
| Janela deslizante persistida, amostragem oportunista | `observability/series.py` |
| Seis alertas calculados do estado real | `observability/alerts.py` |
| Quatro rotas de observabilidade | `ingestion/api.py` |
| Tela Trail, faixa de alertas, graficos persistidos | `control-center/src/` |
| ADR-010 | `docs/adr/ADR-010-observabilidade.md` |

## 2. Arquivos

**Criados:** `src/nexus/observability/trail.py`, `series.py`, `alerts.py`;
`tests/unit/test_trail.py`, `test_series_alerts.py`, `test_observability_api.py`;
`control-center/src/screens/Trail.tsx` e `Trail.test.tsx`;
`control-center/src/components/AlertBanner.tsx`, `.css` e `.test.tsx`;
`control-center/src/metrics/persisted.ts` e `persisted.test.ts`;
`docs/adr/ADR-010-observabilidade.md`; `.claude/launch.json`.

**Modificados:** `persistence/models.py`, `repository.py`, `dynamo.py`;
`shared/config.py`; `ingestion/service.py`, `api.py`, `schemas.py`;
`queue/worker.py`, `dispatcher.py`; `tests/fakes.py`;
`control-center/src/App.tsx`, `App.css`, `api/types.ts`, `api/queries.ts`,
`components/Chart.tsx`, `StatTile.tsx`, `StatTile.css`, `screens/Overview.tsx`,
`screens/QueueMonitoring.tsx`, `test-setup.ts`, `test-utils.tsx`;
`docs/architecture/access-patterns.md`; `docs/testing/phase-4-report.md`.

## 3. Como executar

```bash
make up
```

```bash
.venv/bin/python tools/generator.py --count 60 --duplicate-rate 0.1 --variant-rate 0.3 --post --seed 606
```

```bash
make drain
```

```bash
make dashboard
```

A tela **Trail** aceita um `record_id` ou um dos recentes.

## 4. Testes executados

| Suite | Resultado |
|---|---|
| Python | **546 testes**, 89% de cobertura global |
| `src/nexus/observability` | **92%** de cobertura |
| Dashboard | **115 testes**, 84,8% de cobertura |
| `ruff`, `mypy --strict`, `tsc`, `eslint` | limpos |

## 5. Verificacao ponta a ponta

### A trilha atravessa processos

60 registros gerados, 48 aceitos, 12 duplicados, fila drenada. A jornada de um registro:

```
accepted       api           —          fingerprint, source, event_id, record_type
published      api        +6 ms         event_id, via=inline
consumed       worker  +5.465 ms        processor_version, attempt, worker_id
resolved       worker     +16 ms        duration_ms=11,2  end_to_end_ms=5.485
```

**5.465 ms de espera na fila contra 11 ms de processamento.** E exatamente a distincao
que `end_to_end_ms` existe para fazer: o total de 5.487 ms nao diz onde o tempo foi, e
otimizar o processador nao recuperaria nada.

Os marcos vieram de **dois processos diferentes** — `api` e `worker` — sob o mesmo
`record_id`. Antes desta fase, a metade do worker existia so no terminal de quem rodou
`docker compose exec` e desaparecia com ele.

### A jornada de uma morte

Com `make fail-test RATE=1.0`, dez marcos num unico lugar:

```
accepted → published → consumed(1) → failed(1) → consumed(2) → failed(2)
         → consumed(3) → dead_lettered(3) → [redrive] → consumed(1) → resolved
```

Os deltas mostram o backoff crescendo: **521 ms, 3.174 ms, 6.767 ms** entre tentativas.

### Alertas

| Acao | Resultado |
|---|---|
| Plataforma saudavel | `alerts: []` |
| 12 mensagens na DLQ | `dlq_not_empty`, severidade `error`, origem `persistido` |
| Redrive + drain | alerta apagou |

### Concorrencia na amostragem

Oito `POST /v1/ops/sample` simultaneos contra o DynamoDB real, todos no mesmo balde:
**uma escrita, sete recusadas** com `balde ja ocupado por outro observador`.

### Persistencia da serie

`docker compose restart api` — as 4 amostras continuaram na serie. Era precisamente a
limitacao que o ADR-009 registrou e esta fase fechou.

### Tentativas de quebrar

| Entrada | Resposta |
|---|---|
| `record_id` inexistente | `200` com lista vazia e explicacao |
| `../etc/passwd` codificado | `404` |
| `record_id` com 200 caracteres | `422` |
| `window=99999` e `window=0` | `422` |
| `window=1440` (maximo) | `200`, 5.755 buracos declarados |

## 6. Defeitos encontrados e corrigidos

### 6.1 O worker lia uma chave que nao existia

O marco `resolved` pedia `summary.get("decision")`. O processador de resolucao nunca
produziu essa chave — `decision` vive dentro de `top_match`. O detalhe vinha sempre sem
ela, e nada falhava, porque chave ausente vira `None` e `None` e filtrado.

Trocada por `candidates_compared` e pelo sinal de truncamento, que existem e dizem se o
teto de cluster cortou candidatos — ou seja, se o resultado pode conter falso negativo.

**So apareceu olhando a saida real.** Os testes usavam o processador padrao e afirmavam
a presenca dos marcos, nao o conteudo de cada detalhe.

### 6.2 O grafico desenhava buracos como se fossem medicoes

A legenda prometia que os baldes nao medidos apareceriam "como interrupcao, nao como
zero". O eixo era categorico: dez minutos sem amostra ocupavam a mesma largura de um
balde de quinze segundos, com a linha passando reta por cima.

A frase estava certa e a tela desmentia. Agora o eixo e temporal, um balde ausente vira
ponto vazio e `connectNulls` esta desligado — a linha se parte de fato.

### 6.3 Os graficos nunca foram exercitados pelos testes

Ao trocar a serie de sessao pela persistida, onze testes do dashboard quebraram com
`ResizeObserver is not defined`.

O motivo e revelador: as series de sessao **comecavam vazias**, o `Chart` devolvia o
estado "aguardando leituras" e o componente de grafico nunca montava. Noventa e seis
testes passavam sem jamais renderizar um grafico. A quebra foi o sinal de que agora eles
renderizam.

### 6.4 O relatorio da Fase 4 publicou um numero errado

Ele dizia que a importacao dinamica derrubou o bundle inicial "de 869 kB para 238 kB".
Os 238 kB sao o **pedaco que saiu** — o chunk do Cognito, carregado sob demanda. O
`index.html` aponta para o outro arquivo: o bundle inicial caiu de ~950 kB para 712 kB.

Li a saida do `vite build` de cima para baixo e assumi que a linha menor era a entrada,
sem abrir o `index.html`. Numero publicado sem verificacao — exatamente o que a secao 9
manda nao fazer. Corrigido no relatorio da Fase 4, com a correcao registrada la.

### 6.5 `correlation_id` transbordava o card

Trinta e dois caracteres no corpo tipografico reservado a numeros de duas casas
invadiam o card vizinho.

### 6.6 `tsconfig.tsbuildinfo` estava versionado

Cache incremental do TypeScript em commit. Removido do controle de versao.

## 7. Limitacoes conhecidas

- **A trilha nao e auditoria.** Best-effort por decisao (ADR-010): pode ter buracos.
  Garantia continua em `StoredRecord` e `ProcessingResult`, que sao transacionais.
- **Sem ninguem observando, nada e amostrado.** A serie tem buracos quando o painel esta
  fechado. Na AWS o Scheduler cobriria; local, nao ha quem cubra. A interface declara
  quantos baldes faltaram.
- **A taxa de erro dos alertas vive no processo.** Zera no reinicio da API e nao agrega
  entre replicas. O alerta declara origem `processo`.
- **`end_to_end_ms` fica `None` com relogios discordantes**, entao o histograma tem menos
  amostras que registros processados.
- **Nada foi exercitado na AWS.** A infraestrutura esta destruida. A amostragem via
  EventBridge Scheduler e a rota `/v1/ops/sample` existem e sao testadas localmente; a
  integracao com o Scheduler **nao foi validada na nuvem**.
- **Sem teste de carga.** A trilha adiciona ate 6 escritas por registro; o impacto sob
  volume e tema da Fase 7.
- **A tela Trail nao tem busca por `correlation_id`.** A trilha e chaveada por registro
  por decisao; cruzar por `correlation_id` exige ler os logs.

## 8. Proximos passos

1. **Fase 7 — Performance Engineering.** Cenarios Locust, medicao sob carga, custo real
   das escritas de trilha em volume, separacao de cold start.
2. **Fase 8 — Finalizacao.** CI/CD, diagramas, consolidacao dos ADRs.
3. **Deploy do dashboard na Vercel**, que depende de reaplicar a infraestrutura AWS.
4. **Validar a amostragem pelo Scheduler na nuvem** quando a infraestrutura voltar.
