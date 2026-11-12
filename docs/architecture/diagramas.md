# Diagramas — Nexus Architecture

Diagramas em [Mermaid](https://mermaid.js.org/), nao em imagem. A razao e de revisao:
um PNG muda e o diff mostra "binario alterado"; um diagrama em texto mostra qual seta
mudou. O GitHub renderiza Mermaid nativamente, entao o custo de legibilidade e zero.

Cada diagrama abaixo descreve **o que esta implementado e testado**. O da infraestrutura
AWS e a excecao explicita, e diz isso no proprio titulo.

---

## 1. Modulos e o que atravessa cada fronteira

```mermaid
flowchart TB
    gerador["Gerador sintetico<br/><i>tools/generator.py</i>"]
    cc["Control Center<br/><i>React — cliente da API</i>"]

    subgraph ingestao["Nexus Ingestion"]
        api["FastAPI + Pydantic<br/>valida, normaliza, decide idempotencia"]
    end

    subgraph fila["Nexus Queue Engine"]
        outbox["Dispatcher do outbox<br/>le o GSI esparso"]
        worker["Worker<br/>lote, retentativa, backoff, DLQ"]
    end

    subgraph resolucao["Nexus Entity Resolution"]
        engine["Blocking -> comparacao -> score<br/>MATCH / POSSIBLE / NO_MATCH"]
    end

    dynamo[("DynamoDB<br/>single-table")]
    sqlite[("Fila SQLite<br/><i>SQS na AWS</i>")]

    gerador -->|"HTTP /v1/records"| api
    cc -->|"HTTP /v1/ops, /metrics, /v1/observability"| api
    api -->|"TransactWriteItems"| dynamo
    api -.->|"publicacao best-effort"| sqlite
    outbox -->|"eventos pendentes"| sqlite
    dynamo --> outbox
    sqlite --> worker
    worker -->|"chamada de funcao,<br/>nao segunda fila"| engine
    engine --> dynamo
    worker --> dynamo

    obs["Nexus Observability<br/>correlation_id, logs JSON, metricas,<br/>trilha, serie, alertas"]
    obs -.->|"camada transversal,<br/>nao processo"| ingestao
    obs -.-> fila
    obs -.-> resolucao

    style obs stroke-dasharray: 5 5
```

**Entity Resolution e chamada de funcao, nao uma segunda fila.** Outra fila somaria
latencia e um ponto de falha sem resolver problema existente. Promove-la depende de
necessidade concreta de escalar separadamente, que nao existe.

**Observability nao e um processo.** E a razao de ela aparecer tracejada: nao ha
servico de observabilidade para subir ou cair.

---

## 2. Ingestao: os dois desvios antes da transacao

```mermaid
sequenceDiagram
    autonumber
    participant C as Cliente
    participant A as API
    participant D as DynamoDB
    participant Q as Fila

    C->>A: POST /v1/records/person<br/>Idempotency-Key: k
    alt sem Idempotency-Key
        A-->>C: 400 — o header e obrigatorio
    end
    A->>A: Pydantic valida o corpo
    alt corpo invalido
        A-->>C: 422 — nunca alcanca a persistencia
    end

    A->>D: busca (source, k)
    alt operacao ja vista, mesmo request_hash
        D-->>A: resposta armazenada
        A-->>C: 200 replay — nenhum efeito novo
    else operacao ja vista, corpo diferente
        A-->>C: 409 — a mesma chave, outro conteudo
    end

    A->>A: normaliza -> natural_key + record_fingerprint
    A->>D: ha observacao com o mesmo conteudo?
    alt conteudo identico ja observado
        A->>D: incrementa seen_count
        A-->>C: 200 duplicate — NAO enfileira
    end

    rect rgb(238, 238, 238)
        note over A,D: TransactWriteItems — atomico
        A->>D: observacao imutavel + evento de outbox + registro de idempotencia
    end

    A-)Q: publicacao best-effort
    Q--)A: ok -> remove pending_shard
    A-->>C: 202 Accepted
```

**Os dois desvios sao perguntas diferentes.** O passo da chave de idempotencia pergunta
*"esta operacao ja foi executada?"*; o do fingerprint pergunta *"este conteudo ja foi
observado?"*. Um cliente que repete a chamada com chave nova e conteudo igual passa pelo
primeiro e para no segundo — e e por isso que `seen_count` existe.

---

## 3. Outbox: por que o indice e proporcional ao backlog

```mermaid
flowchart LR
    subgraph tabela["Tabela base — cresce para sempre"]
        i1["OUTBOX#a<br/>pending_shard = PENDING#0"]
        i2["OUTBOX#b<br/>pending_shard = PENDING#1"]
        i3["OUTBOX#c<br/><s>pending_shard</s> removido<br/>status = dispatched"]
        i4["OUTBOX#d<br/><s>pending_shard</s> removido<br/>status = failed"]
    end

    subgraph gsi["gsi_outbox_pending — so quem tem a chave"]
        g1["PENDING#0 | next_attempt_at"]
        g2["PENDING#1 | next_attempt_at"]
    end

    i1 --> g1
    i2 --> g2
    i3 -.->|"sumiu do indice"| gsi
    i4 -.->|"sumiu do indice"| gsi

    disp["Dispatcher"] -->|"Query shard a shard<br/>next_attempt_at <= agora"| gsi
```

Publicar com sucesso **remove o atributo**, e o item desaparece do indice — indices
esparsos contem apenas itens que possuem a chave. A leitura e O(pendentes), nao O(tabela).
Um `Scan` com filtro leria tudo e cobraria por tudo.

O `shard` existe para que a escrita do indice nao caia toda numa particao: com `PK`
constante, todo evento pendente disputaria a mesma. Como efeito secundario, permite
despachar em paralelo.

---

## 4. Consumo: o ciclo de vida de uma mensagem

```mermaid
stateDiagram-v2
    [*] --> Pendente: publicada
    Pendente --> EmVoo: worker reivindica<br/>(BEGIN IMMEDIATE)
    EmVoo --> Processada: processador retorna
    EmVoo --> Pendente: visibility timeout expira<br/>(worker morreu)
    EmVoo --> Retentativa: ProcessingError
    Retentativa --> Pendente: backoff exponencial
    Retentativa --> DLQ: atingiu queue_max_receive
    DLQ --> Pendente: POST /v1/ops/redrive
    Processada --> [*]

    note right of Processada
        Antes de processar, o worker consulta o
        marcador de resultado. Reentrega encontra
        o marcador e devolve skipped_duplicate:
        a entrega e at-least-once por desenho,
        nao por defeito.
    end note
```

`EmVoo --> Pendente` nao e caminho de erro. **A mensagem volta sozinha quando o
consumidor morre sem confirmar** — e essa e a propriedade que torna o worker descartavel.

O recibo identifica *uma entrega de uma mensagem*, nunca o lote. Com recibo por lote,
confirmar a primeira apagaria as demais.

---

## 5. A trilha atravessa processos

```mermaid
sequenceDiagram
    participant A as API <br/>(processo 1)
    participant T as TRAIL#record_id
    participant W as Worker <br/>(processo 2)

    A->>T: accepted
    A->>T: published
    note over A,W: fronteira assincrona — a mensagem espera na fila
    W->>T: consumed
    alt processamento falha
        W->>T: failed (tentativa, motivo)
        W->>T: failed
        W->>T: dead_lettered
    else sucesso
        W->>T: resolved (duracao, entidade, score)
    end

    note over T: GET /v1/observability/trail/{record_id}<br/>devolve tudo em ordem, com o delta entre marcos
```

**E a unica estrutura do projeto que um unico processo nao consegue produzir.** Antes
dela, `accepted` ficava no log do container da API e `consumed` no terminal de quem
executou o worker — as duas metades da mesma jornada em lugares que nunca se encontram.

O delta entre marcos e o que diagnostica: um total de oito segundos com sete deles entre
`published` e `consumed` e espera na fila, e nenhuma otimizacao do processador os
recupera.

---

## 6. Modelo single-table

```mermaid
flowchart TB
    subgraph base["Tabela base — PK / SK"]
        r["RECORD#id | RECORD#id<br/><i>observacao imutavel</i>"]
        idem["IDEMP#source#key | IDEMP#...<br/><i>resposta armazenada, TTL</i>"]
        ob["OUTBOX#event | OUTBOX#event"]
        proc["RECORD#id | RESULT#versao<br/><i>marcador e resultado num item so</i>"]
        ent["ENTITY#id | ENTITY#id"]
        mem["ENTITY#id | MEMBER#record"]
        tr["TRAIL#record | iso#ulid<br/><i>TTL 7 dias</i>"]
        se["SERIES#metrica | balde<br/><i>TTL 7 dias</i>"]
    end

    subgraph indices["Indices"]
        g1["gsi_natural<br/>candidatos de blocking"]
        g2["gsi_outbox_pending<br/>esparso: so pendentes"]
        g3["gsi_recency<br/>listagem por recencia"]
    end

    r --> g1
    r --> g3
    ob --> g2
```

Marcador de processamento e resultado sao **um unico item** (ADR-005): gravados
separadamente, um crash entre as duas escritas deixaria o registro marcado como
processado sem resultado nenhum.

Trilha e serie usam a tabela base e **nenhum indice novo** — foi o criterio que decidiu
chavear a trilha por `record_id` em vez de `correlation_id`.

---

## 7. Infraestrutura AWS — construida, validada e **destruida**

> Este diagrama descreve o que o Terraform em `infra/terraform/` cria quando aplicado.
> **Nada disso esta no ar hoje.** A infraestrutura foi aplicada, verificada e destruida
> na Fase 3; o custo acumulado do projeto e US$ 0,00. Ver
> [COSTS.md](../../COSTS.md) e [docs/testing/phase-3-report.md](../testing/phase-3-report.md).

```mermaid
flowchart TB
    nav["Navegador<br/>Control Center"]
    cog["Cognito User Pool<br/><i>autoriza /v1/ops</i>"]

    subgraph aws["AWS"]
        agw["API Gateway HTTP<br/>CORS restrito + authorizer JWT"]
        lam["Lambda ingestao<br/><i>o mesmo FastAPI, via Mangum</i>"]
        lw["Lambda worker"]
        ld["Lambda dispatcher"]
        ddb[("DynamoDB On-Demand")]
        sqs[["SQS"]]
        dlq[["SQS DLQ<br/>maxReceiveCount = 3"]]
        sch["EventBridge Scheduler<br/><i>invocacao explicita</i>"]
        cw["CloudWatch Logs<br/>retencao 7 dias"]
        bud["Budget<br/>alerta em US$ 5"]
    end

    nav --> cog
    nav --> agw
    agw --> lam
    lam --> ddb
    lam --> sqs
    sch --> ld
    sch --> lw
    ld --> ddb
    ld --> sqs
    sqs --> lw
    sqs -.->|"3 falhas"| dlq
    lw --> ddb
    lam --> cw
    lw --> cw
    ld --> cw

    style aws stroke-dasharray: 5 5
```

**Nao ha event source mapping de SQS para Lambda.** Ele faz long-polling continuo, o que
desfaz exatamente a execucao sob demanda que a plataforma existe para demonstrar. O
preco dessa escolha esta registrado: sem consumidor residente, uma mensagem que falha
espera ate alguem invocar o worker.

**Nao ha VPC privada.** O isolamento e por IAM. Um NAT Gateway custaria cerca de
US$ 32/mes parado, mais que todo o resto da plataforma somado.

---

## Como manter

Mermaid vive dentro do Markdown e renderiza no GitHub sem passo de build. Para conferir
antes de versionar: [mermaid.live](https://mermaid.live).

Diagrama que descreve algo nao implementado precisa dizer isso **no titulo**, como o da
secao 7 — nao em nota de rodape, que ninguem le depois de ter olhado a figura.
