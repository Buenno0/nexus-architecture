# Arquitetura — Nexus Architecture

## Principio ordenador

**A API nunca processa. Ela aceita, valida, normaliza e enfileira.**

Todo trabalho computacionalmente caro acontece fora do ciclo de request/response.
Essa separacao e a razao de existir do projeto.

### Por que nao sincrono?

Se a API executasse entity resolution dentro do request, cada POST pagaria o custo de
comparar o registro contra a base inteira. Sob carga alta isso colapsa: conexoes presas,
timeouts em cascata, perda de dados. Separando ingestao de processamento:

- a API responde em milissegundos (valida, persiste e enfileira);
- o processamento escala de forma independente;
- uma falha no processamento nao derruba a ingestao.

---

## Os tres conceitos que NAO devem ser confundidos

Esta e a decisao central da plataforma. Confundi-los produz perda silenciosa de dados.

| Conceito | Identifica | Origem | Efeito |
|---|---|---|---|
| `idempotency_key` | uma **operacao de ingestao** | cliente, header `Idempotency-Key` (obrigatorio) | replay devolve a resposta armazenada, sem reprocessar |
| `record_fingerprint` | um **conteudo normalizado** | servidor, sha256 do payload canonizado | reenvio byte-identico nao gera nova observacao |
| Entity Resolution | se registros **diferentes** sao a mesma entidade | assincrono, com score auditavel | vincula registros, nunca sobrescreve |

### Por que a separacao importa

Se a chave de idempotencia fosse derivada da chave natural (`documento` + `email`), a mesma
pessoa chegando com telefone atualizado produziria a mesma chave — e a atualizacao seria
**descartada em silencio**. Isso nao e deduplicacao, e perda de dado.

Consequencia de design: **o registro de origem e uma observacao imutavel**. Mesma chave
natural com fingerprint diferente significa nova observacao — aceita e enfileirada. Quem
decide que duas observacoes sao a mesma pessoa e o resolver, depois, com score registrado.

A API nunca julga identidade. Ela nao tem informacao suficiente para isso.

Ver [ADR-002](docs/adr/ADR-002-identidade-e-idempotencia.md).

---

## Visao geral

```
Fontes sinteticas
       |
       v
+-------------------------+
|   NEXUS INGESTION       |  FastAPI + Pydantic
|   valida / normaliza    |  fingerprint + chave natural
|   transacao atomica     |  registro + outbox + idempotencia
+-----------+-------------+
            | publicacao best-effort
            v
+-------------------------+
|   NEXUS QUEUE ENGINE    |  consumo em lotes
|   retry + backoff       |  DLQ apos N tentativas
+-----------+-------------+
            |
            v
+-------------------------+
| NEXUS ENTITY RESOLUTION |  blocking -> comparacao
|  score -> decisao       |  MATCH / POSSIBLE / NO_MATCH
+-----------+-------------+
            |
            v
+-------------------------+
|      PERSISTENCIA       |  DynamoDB single-table
+-------------------------+

NEXUS OBSERVABILITY  — camada transversal (correlation_id, logs, metricas)
NEXUS CONTROL CENTER — cliente React que le metricas e dispara operacoes
```

---

## Fluxo de ingestao

```
 1. POST /v1/records/{tipo}  +  header Idempotency-Key
 2. Header ausente                      -> 400 Bad Request
 3. Pydantic valida o corpo             -> 422, nunca chega a persistencia
 4. Consulta (source, idempotency_key):
      encontrada, mesmo request_hash    -> 200 resposta armazenada (replay)
      encontrada, request_hash diferente-> 409 Conflict
 5. Normalizacao -> natural_key + record_fingerprint
 6. Observacao com mesmo (source, natural_key, record_fingerprint)?
      sim -> 200 status="duplicate", incrementa seen_count, NAO enfileira
 7. TransactWriteItems (atomico):
      - OBSERVACAO imutavel (novo record_id)
      - EVENTO DE OUTBOX pendente
      - REGISTRO DE IDEMPOTENCIA com a resposta
 8. Publicacao best-effort na fila -> em caso de sucesso, remove pending_shard
 9. 202 Accepted
----------------------- fronteira assincrona -----------------------
10. Worker le lote; verifica marcador de processamento (idempotencia no consumo)
11. Entity Resolution -> candidatos, score, decisao
12. Persiste vinculo a entidade canonica
13. Sucesso: remove da fila | Falha: retry com backoff | N falhas: DLQ
14. Metricas emitidas em cada etapa com o mesmo correlation_id
```

### Dois pontos de idempotencia, nao um

Na **ingestao** (passo 4) impede efeito duplicado de uma operacao repetida.
No **consumo** (passo 10) impede processamento duplicado quando a fila reentrega.

SQS e *at-least-once*. Reentrega nao e excecao, e comportamento normal. Assumir que
"a mensagem chega uma vez" e o erro classico desta arquitetura.

---

## Transactional Outbox

### O problema: dual-write

Gravar no banco e depois publicar na fila sao duas operacoes. Um crash entre elas deixa
o registro persistido e **nunca processado** — invisivel, porque do ponto de vista do
cliente nada falhou. A ordem inversa e pior: evento publicado para um registro que nao
existe.

### A solucao

`TransactWriteItems` grava observacao e evento atomicamente. Ou os dois existem, ou
nenhum. Um dispatcher move eventos pendentes para a fila depois, com entrega
at-least-once.

### Recuperacao de eventos pendentes: GSI esparso

```
Item de outbox:
  PK/SK          = OUTBOX#<event_id>
  record_id, correlation_id, created_at
  attempts       = 0
  next_attempt_at
  status         = pending | dispatched | failed
  pending_shard  = "PENDING#<0..N-1>"   <-- presente SOMENTE enquanto pendente

GSI gsi_outbox_pending:  PK = pending_shard,  SK = next_attempt_at
```

O dispatcher consulta `pending_shard = PENDING#n AND next_attempt_at <= agora`.
Ao publicar com sucesso, **remove o atributo** `pending_shard` — e o item desaparece do
indice, porque indices esparsos contem apenas itens que possuem a chave.

**O indice e proporcional ao backlog, nao ao tamanho da tabela.** Um scan seria O(n)
sobre tudo; aqui a leitura e O(pendentes).

Em falha: `attempts += 1`, `next_attempt_at = agora + backoff`. Ao atingir o limite,
remove `pending_shard` e marca `status=failed` — sai do caminho quente sem travar os
demais, e permanece consultavel para inspecao.

O `shard` evita particao quente: com PK constante toda a escrita do indice cairia numa
unica particao. Com N shards o dispatcher tambem paralelliza.

### Acionamento: inline + rede de seguranca

A API tenta publicar imediatamente apos a transacao (caminho feliz, baixa latencia).
Se a publicacao falhar ou o processo morrer antes de limpar o atributo, o evento continua
pendente no GSI e o dispatcher sob demanda recupera.

Crash **depois** de publicar e **antes** de limpar republica o evento. Aceitavel e
esperado: a entrega e at-least-once e a idempotencia no consumo absorve. O inverso —
perder o evento — seria inaceitavel.

**Descartado:** DynamoDB Streams -> Lambda. Event source mapping faz long-polling
continuo, exatamente o padrao de custo que decidimos evitar. O GSI esparso funciona
identico no DynamoDB Local e na AWS.

Ver [ADR-003](docs/adr/ADR-003-transactional-outbox.md).

---

## Consumo: fila, retentativa e DLQ

### A fila (ADR-004)

Localmente, a fila e um banco SQLite que reproduz as primitivas do SQS: publicacao
idempotente, reivindicacao atomica, visibility timeout, backoff e Dead Letter Queue.
Cada garantia e uma linha de SQL legivel, em vez de comportamento importado.

Duas propriedades sustentam a correcao:

- **`BEGIN IMMEDIATE`** adquire o bloqueio de escrita antes de ler. Com o `BEGIN`
  diferido, dois consumidores leem as mesmas linhas e ambos as reivindicam.
- **O recibo identifica uma entrega de uma mensagem**, nunca o lote. Com recibo por
  lote, confirmar a primeira mensagem apagaria todas as outras.

**Restricao:** a fila so e acessada de dentro do container. SQLite em WAL coordena por
memoria compartilhada e locks POSIX, que nao atravessam a fronteira host/VM no macOS.
A restricao desaparece na Fase 3, com SQS.

### Idempotencia no consumo (ADR-005)

```
PK = SK = PROCESSED#<record_id>
ConditionExpression: attribute_not_exists(pk)
```

O resultado do processamento **e** o marcador de ja processado. Duas coisas que
precisam ser atomicas deixam de precisar de transacao quando viram uma so.

O worker consulta o marcador antes de processar, mas isso e otimizacao. A garantia e a
condicao na escrita: `CommitConflictError` significa que outro worker venceu, o trabalho
foi feito, e a mensagem sai da fila.

---

## Resolucao de identidade (ADR-006)

O resolvedor substituiu o processador da Fase 2 **sem que worker, fila ou persistencia
mudassem** — o contrato `RecordProcessor` existia exatamente para isso.

```
observacao
   |
   v  chaves de bloco (documento, e-mail, nome, telefone)
candidatos  --- teto com sinalizacao de truncagem
   |
   v  score ponderado, campo a campo, com piso de similaridade
decisao
   |
   +-- MATCH           -> funde clusters, registra o par e a evidencia
   +-- POSSIBLE_MATCH  -> fila de revisao, NUNCA funde sozinho
   +-- NO_MATCH        -> nada
```

### Duas normalizacoes com objetivos opostos

A ingestao preserva acentos e caixa porque sao **sinal** para o resolvedor. O blocking
os remove porque, comparando, viram **ruido**. Agrupar demais custa comparacoes que o
score descarta; perder um par e definitivo.

### O marcador tambem impedia melhoria

A chave do marcador passou a incluir a versao do processador
([ADR-007](docs/adr/ADR-007-versionamento-do-processador.md)). Sem isso, trocar o
processador nao reprocessaria nada: o marcador antigo existe e a escrita condicional
recusaria — o acervo ficaria fora da resolucao em silencio.

### Acionamento

```
POST /v1/ops/dispatch   publica eventos pendentes do outbox
POST /v1/ops/process    consome um lote
GET  /v1/ops/queue      profundidade: pendentes, em voo, DLQ, outbox
POST /v1/ops/redrive    devolve mensagens da DLQ
POST /v1/ops/reprocess  reenfileira o acervo sob a versao corrente
GET  /v1/resolution/*   entidades, revisoes e contadores
```

Nada processa sozinho. Nenhum worker residente, nenhum polling continuo — todo o modelo
de custo depende disso.

---

## Fronteiras dos modulos

| Modulo | Responsabilidade | Nao faz |
|---|---|---|
| Ingestion | HTTP, validacao, normalizacao, idempotencia, transacao, publicacao | Nao compara entidades, nao decide duplicidade |
| Queue Engine | Consumo, lotes, retry, backoff, DLQ, dispatcher de outbox | Nao conhece regra de negocio — o processador e injetado |
| Entity Resolution | Blocking, comparacao, score, decisao, clusters | Nao acessa fila nem HTTP; e invocado como processador |
| Observability | correlation_id, logs JSON, metricas | Nao e processo separado — e camada transversal |
| Control Center | Visualizacao e operacao | Nenhuma logica de negocio |

## Comunicacao entre modulos

| De -> Para | Mecanismo | Acoplamento |
|---|---|---|
| Cliente -> Ingestion | HTTP/JSON | Contrato versionado (`/v1/`) |
| Ingestion -> Queue | Outbox + publicacao | Assincrono, atomico na origem |
| Queue -> Entity Resolution | Chamada de funcao | Mesmo processo |
| Todos -> Persistencia | Interface `Repository` | Abstracao fina |
| Control Center -> API | HTTP/JSON | Cliente externo |

Entity Resolution e chamada de funcao, nao outra fila. Uma segunda fila adicionaria
latencia e um ponto de falha sem resolver problema existente. Sera promovida a fila
apenas se houver necessidade concreta de escalar separadamente.

---

## Estrategia local -> AWS

Dois mecanismos tornam a migracao possivel sem reescrita:

1. **Interfaces nas fronteiras de I/O.** `QueueClient` e `Repository` sao abstratos.
   A logica de negocio nao sabe qual implementacao esta ativa.
2. **Selecao por configuracao.** `NEXUS_ENV=local|aws` decide as implementacoes em um
   unico ponto. Nenhum `if` de ambiente espalhado pelo codigo.

| Componente | Local | AWS (Fase 3) |
|---|---|---|
| API | Uvicorn em Docker | Lambda + API Gateway (Mangum) |
| Fila | SQLite (ADR-004) | SQS + DLQ |
| Worker / dispatcher | Processo Docker | Lambda sob demanda |
| Dados | DynamoDB Local | DynamoDB On-Demand |
| Logs | stdout JSON | CloudWatch Logs |

DynamoDB Local e a mesma API do DynamoDB gerenciado, incluindo `TransactWriteItems` e
indices esparsos — o codigo de persistencia e literalmente o mesmo nos dois ambientes.
Ver [ADR-001](docs/adr/ADR-001-dynamodb-local.md).

---

## Decisoes registradas

- [ADR-001](docs/adr/ADR-001-dynamodb-local.md) — DynamoDB Local em vez de PostgreSQL
- [ADR-002](docs/adr/ADR-002-identidade-e-idempotencia.md) — Separacao entre operacao, conteudo e entidade
- [ADR-003](docs/adr/ADR-003-transactional-outbox.md) — Transactional outbox com GSI esparso
- [ADR-004](docs/adr/ADR-004-fila-local-sqlite.md) — Fila local sobre SQLite
- [ADR-005](docs/adr/ADR-005-idempotencia-no-consumo.md) — Marcador e resultado como um unico item
- [ADR-006](docs/adr/ADR-006-entity-resolution.md) — Blocking, pontuacao e clusterizacao auditavel
- [ADR-007](docs/adr/ADR-007-versionamento-do-processador.md) — Versionamento do processador
