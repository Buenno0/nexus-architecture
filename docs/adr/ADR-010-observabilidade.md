# ADR-010 — Trilha durável, best-effort, chaveada por registro

- **Status:** Aceita
- **Data:** 2026-11-10

## Contexto

O ROADMAP pedia para a Fase 6 "rastreamento fim a fim por `correlation_id`". Boa parte
disso ja existia desde a Fase 1: logs em JSON, `correlation_id` gerado na borda e
propagado para o worker, contadores e histogramas com P50, P95 e P99.

Duas constatacoes da verificacao mostraram que nada daquilo servia ao proposito.

### 1. A trilha existia em teoria e era irrecuperavel na pratica

`docker compose logs api` tinha **zero** eventos `worker_record_processed`. O worker
roda por `docker compose exec`: escreve na sessao do terminal de quem chamou, nao no
log do container. Metade da jornada — a aceitacao — estava no log; a outra metade
evaporava junto com o terminal.

O investimento em `correlation_id` das Fases 1, 2 e 5 **nunca se pagou**. Pior: na AWS
seria mais grave ainda, com cada Lambda num grupo de log proprio e nenhum container
compartilhado.

### 2. A latencia fim a fim nunca era calculada

`StoredRecord.created_at` e `ProcessingResult.processed_at` existiam desde a Fase 2 e
jamais foram cruzados. O numero mais util para "identificacao de gargalos" — o item
seguinte do mesmo ROADMAP — estava a uma subtracao de distancia.

## Decisao

### 1. A trilha e feita de itens do DynamoDB, nao de linhas de log

```
PK = TRAIL#<record_id>    SK = <iso_timestamp>#<ulid>
```

O `SK` comeca pelo carimbo, entao a `Query` ja devolve em ordem cronologica sem ordenar
em memoria. O ULID no fim desempata eventos do mesmo milissegundo — e a verificacao
confirmou que funciona: eventos gravados fora de ordem voltaram ordenados.

### 2. Chaveada por `record_id`, nao por `correlation_id`

Duas razoes:

- **Cabe na tabela base.** `PK = TRAIL#<record_id>` nao exige indice novo. Um indice por
  `correlation_id` custaria escrita em toda ingestao.
- **Responde melhor a pergunta real.** Um registro reprocessado sob versao nova de
  processador tem varios `correlation_id`. Perguntar "o que aconteceu com este
  registro" deve trazer todos, nao um recorte por tentativa.

O `correlation_id` continua em cada evento, como atributo, para cruzar com os logs.

### 3. Toda escrita de observabilidade e best-effort

Falha de gravacao de trilha ou de amostra e registrada em log e engolida. **Jamais
propagada.**

Um registro perdido e dado perdido. Um evento de trilha perdido e uma linha a menos
numa investigacao. Tratar os dois com o mesmo rigor transformaria a observabilidade em
mais uma fonte de falha — e e ela que deveria explicar as falhas, nao causa-las.

Mesmo criterio que `increment_resolution_stats` ja adotava desde a Fase 5.

**Consequencia assumida:** a trilha pode ter buracos. Ela ajuda a investigar; nao e
registro de auditoria. Quem precisa de garantia usa a observacao e o `ProcessingResult`,
que sao transacionais.

O `TrailRecorder` engole ate erro de programacao — um detalhe que nao serializa, por
exemplo — porque o repositorio so protege contra falha de I/O, e uma excecao antes de
chegar nele derrubaria a operacao observada do mesmo jeito.

### 4. Seis marcos, nao rastreamento contínuo

`accepted`, `published`, `consumed`, `resolved`, `failed`, `dead_lettered`. Sao os
pontos em que o estado do registro muda. Instrumentar cada passo intermediario
multiplicaria escritas sem responder nenhuma pergunta nova.

TTL de 7 dias, reusando o atributo `expires_at` que a tabela ja tinha.

### 5. `end_to_end_ms` separado de `duration_ms`

`duration_ms` mede so o processamento. A diferenca entre os dois e o tempo que a
mensagem passou parada na fila.

Isso separa **"o processamento esta lento"** de **"a fila esta acumulando"** —
diagnosticos opostos, com correcoes opostas. A verificacao mostrou 5.465 ms de espera
contra 11 ms de processamento: nenhuma otimizacao do processador recuperaria aquele
tempo.

Delta negativo vira `None`, nao zero. As duas pontas sao carimbadas por processos
diferentes — na AWS, duas Lambdas. Relogios discordantes produzem medicao invalida, nao
latencia pequena, e gravar zero a esconderia dentro de um histograma plausivel.

### 6. Janela deslizante com amostragem oportunista

```
PK = SERIES#<metrica>    SK = <timestamp arredondado ao balde>
```

Quem passa por `/metrics` grava uma amostra se o balde do instante estiver livre,
reaproveitando as leituras que a rota ja faz — nenhuma leitura extra.

**Arredondar o carimbo antes de gravar e o que torna a escrita condicional util.** Com o
instante exato de cada observador, duas amostras nunca colidiriam e a densidade da serie
mediria o numero de abas abertas, nao o tempo. Com o balde, elas colidem de proposito e
`attribute_not_exists` deixa passar uma. Oito requisicoes simultaneas contra o DynamoDB
real produziram uma amostra.

Nao ha processo amostrando em laco: seria o worker residente que COSTS.md proibe.

**Limitacao assumida:** sem ninguem observando, nada e amostrado. Na AWS o EventBridge
Scheduler passa a chamar `/v1/ops/sample` e cobre a janela ociosa. Local, o historico
tem buracos quando o painel esta fechado — e a interface informa quantos baldes nao
foram medidos, em vez de desenhar uma reta sobre eles.

### 7. Alertas calculados, nunca configurados

Seis condicoes derivadas do estado real no instante da pergunta: DLQ nao vazia, backlog
do outbox, evento de outbox parado, taxa de erro HTTP, recusas pelo teto de cluster e
persistencia indisponivel.

E a licao da Fase 4. A API declarava `entity_resolution: not_implemented` porque alguem
escreveu isso a mao na Fase 2; a Fase 5 implementou a resolucao e esqueceu de corrigir.
**Estado declarado envelhece em silencio; estado derivado nao tem como.**

Backlog grande e backlog parado sao alertas separados de proposito. Sessenta eventos
recem-chegados sao vazao. Tres parados ha vinte minutos sao um dispatcher que nao roda —
e so o segundo caso perde dados pela expiracao do TTL.

Sem persistencia, o alerta correspondente vem **sozinho**: backlog e idade nao sao
avaliaveis, e acompanhar o erro de numeros inventados seria pior que omiti-los.

Sem CloudWatch: a infraestrutura AWS esta destruida e alarme que so existe na nuvem nao
serve ao ambiente onde a plataforma roda hoje. Quando ela voltar, estas condicoes viram
metricas customizadas e alarmes — o calculo ja esta pronto e continua valendo local.

## Alternativas consideradas

| Alternativa | Por que nao |
|---|---|
| OpenTelemetry + Jaeger | Resolve o problema, e traz um coletor e um backend de traces para rodar. Peso desproporcional para uma plataforma cujo modelo de custo e "nada roda sozinho". A decisao nao e contra OTel; e contra adiciona-lo agora. |
| Indice global por `correlation_id` | Escrita extra em toda ingestao para responder pior: um registro reprocessado tem varios. |
| Trilha transacional junto da observacao | Acoplaria a ingestao a gravacao de telemetria. Observabilidade passaria a ser causa de falha. |
| Amostragem por processo residente | Processo em laco com fila vazia consumindo recurso — exatamente o que a secao 6 do projeto proibe. |
| CloudWatch Alarms | A conta esta sem infraestrutura. Alarme que so existe na nuvem nao observa o ambiente de hoje. |

## Consequencias

**Positivas**

- A jornada de um registro atravessa API e worker e sobrevive aos dois processos.
- O delta entre marcos localiza o gargalo que o total esconde.
- A serie persiste a recarregar a pagina e a reiniciar a API — fecha a limitacao que o
  ADR-009 registrou.
- Nenhum indice novo; nenhum servico adicional; nenhum custo ocioso.

**Negativas**

- A trilha pode ter buracos e **nao serve como auditoria**.
- Escritas de trilha somam ao custo de ingestao: ate 6 itens por registro.
- A serie depende de alguem observar. Plataforma parada, serie parada.
- `end_to_end_ms` fica `None` quando os relogios discordam — correto, mas significa que
  o histograma tem menos amostras que registros processados.

## Custo

Com 10.000 registros/mes e todos os seis marcos: 60.000 escritas de ~400 bytes, mais
~175.000 amostras/mes se alguem observar continuamente a 15s. Em DynamoDB On-Demand a
US$ 0,625 por milhao de WRU, cerca de **US$ 0,15/mes**. Ver COSTS.md.
