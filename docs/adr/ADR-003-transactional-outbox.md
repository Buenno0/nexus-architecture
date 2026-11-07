# ADR-003 — Transactional outbox com GSI esparso

- **Status:** Aceita
- **Data:** 2026-11-06

## Contexto

Persistir o registro e publicar na fila sao duas operacoes contra sistemas diferentes.
Nao existe transacao distribuida entre elas. Isso e o problema do **dual-write**:

- Grava e depois publica: um crash no meio deixa o registro persistido e **nunca
  processado**. Invisivel — do ponto de vista do cliente nada falhou.
- Publica e depois grava: pior ainda, um evento aponta para um registro inexistente.

Em volume alto, "raramente acontece" significa "acontece todo dia".

## Decisao

Usar **transactional outbox**. `TransactWriteItems` do DynamoDB grava atomicamente a
observacao, o evento de outbox e o registro de idempotencia. Ou os tres existem, ou
nenhum.

### Recuperacao de pendentes: GSI esparso

```
Item de outbox:
  PK/SK          = OUTBOX#<event_id>
  record_id, correlation_id, created_at
  attempts, next_attempt_at
  status         = pending | dispatched | failed
  pending_shard  = "PENDING#<0..N-1>"   <-- SOMENTE enquanto pendente

GSI gsi_outbox_pending:  PK = pending_shard,  SK = next_attempt_at
```

O dispatcher consulta `pending_shard = PENDING#n AND next_attempt_at <= agora`.
Ao publicar com sucesso, **remove o atributo** — e o item sai do indice, porque indices
esparsos contem apenas itens que possuem a chave.

**O indice e proporcional ao backlog, nao ao tamanho da tabela.** Leitura O(pendentes)
em vez de O(total).

Em falha: `attempts += 1`, `next_attempt_at = agora + backoff exponencial`. Ao atingir
o limite, remove `pending_shard` e marca `status=failed` — sai do caminho quente sem
bloquear os demais, e continua consultavel.

O shard evita particao quente: com PK constante, toda escrita do indice cairia numa
unica particao. Com N shards o dispatcher tambem paraleliza.

#### Restricao operacional: o numero de shards faz parte do contrato de dados

Quem escreve e quem le precisam concordar sobre ``outbox_shards``. O dispatcher varre
``PENDING#0`` ate ``PENDING#N-1``; eventos gravados num shard fora dessa faixa ficam
**permanentemente orfaos** — nunca despachados e invisiveis na contagem de backlog.

Portanto:

- **Reduzir** ``outbox_shards`` com eventos pendentes e destrutivo. Drene o backlog antes.
- **Aumentar** e seguro para eventos novos, desde que o dispatcher ja varra a faixa maior.

Por isso a configuracao e injetada uma unica vez e compartilhada entre ingestao e
dispatcher, em vez de cada componente ler a sua. Essa divergencia foi encontrada por um
teste de integracao antes de existir dispatcher — exatamente onde deveria ser encontrada.

### Acionamento: inline + rede de seguranca

A API tenta publicar imediatamente apos a transacao. Caminho feliz: latencia baixa, item
sai do indice em seguida. Caminho triste: falha de publicacao ou crash antes da limpeza
deixa o item pendente, e o dispatcher sob demanda recupera.

Crash **depois** de publicar e **antes** de limpar republica o evento. Aceitavel: a
entrega e at-least-once e a idempotencia no consumo absorve. Perder o evento seria
inaceitavel; entrega-lo duas vezes, nao.

## Consequencias

**Positivas**
- Nenhum registro aceito fica permanentemente sem processamento.
- Funciona identico no DynamoDB Local e na AWS.
- O backlog pendente e observavel: basta consultar o GSI.
- Compativel com o modelo de execucao sob demanda — nenhum polling continuo.

**Negativas**
- Toda ingestao faz uma transacao em vez de uma escrita simples: mais caro e mais lento.
- O GSI custa escrita adicional por evento (insercao e remocao).
- Entrega duplicada e possivel por construcao; o consumidor **precisa** ser idempotente.
- Mais codigo e mais estado para manter do que publicar direto na fila.

**Mitigacao**
- Idempotencia no consumo e requisito de aceite da Fase 2, nao item opcional.
- Teste explicito de reentrega da mesma mensagem.
- Metrica de backlog pendente exposta no `/metrics` e no Control Center.

## Alternativas consideradas

| Alternativa | Motivo da rejeicao |
|---|---|
| Publicar direto, sem outbox | Dual-write: perda silenciosa de registros |
| DynamoDB Streams -> Lambda | Event source mapping faz long-polling continuo = custo com fila vazia |
| Scan periodico por `status=pending` | O(n) sobre a tabela inteira; inviavel com volume |
| GSI nao esparso com `status` como PK | Indice cresce junto com a tabela; itens ja despachados permanecem nele |
| Dispatcher agendado (EventBridge) | Invocacoes mesmo com fila vazia; contraria execucao sob demanda |
