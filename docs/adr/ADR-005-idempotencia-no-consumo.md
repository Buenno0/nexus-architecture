# ADR-005 — Idempotencia no consumo: o marcador e o resultado

- **Status:** Aceita
- **Data:** 2026-11-06

## Contexto

A entrega e *at-least-once* por construcao. O [ADR-003](ADR-003-transactional-outbox.md)
admite explicitamente que o dispatcher pode republicar um evento apos crash, e o
[ADR-004](ADR-004-fila-local-sqlite.md) reentrega mensagens cujo prazo de visibilidade
expirou. **Reentrega nao e excecao: e comportamento normal.**

O worker precisa entao gravar duas coisas: o resultado do processamento e a marca de que
aquela observacao ja foi processada. Se forem escritas separadas, um crash entre elas
deixa o resultado gravado sem marcador — a reentrega reprocessa e grava de novo. E o
mesmo dual-write do ADR-003, do outro lado do fluxo.

A resposta obvia e uma transacao. Existe uma melhor.

## Decisao

**Fazer do marcador e do resultado o mesmo item.**

```
PK = SK = PROCESSED#<record_id>
ConditionExpression: attribute_not_exists(pk)
```

A existencia do item **e** o marcador. Duas coisas que precisam ser atomicas deixam de
precisar de transacao quando viram uma so: basta uma escrita condicional, mais barata
que `TransactWriteItems` e sem janela nenhuma.

### A chave deriva do registro, nao do evento

A unicidade que importa e "esta observacao foi processada". Uma observacao pode receber
mais de um evento se o outbox republicar; chavear por `event_id` permitiria processar a
mesma observacao duas vezes sob dois eventos diferentes.

### A consulta previa nao e a garantia

O worker consulta o marcador antes de processar. Isso e **otimizacao**: evita trabalho
numa reentrega. Entre a consulta e a escrita existe janela de corrida, e dois workers
podem passar pela consulta ao mesmo tempo.

Quem fecha a janela e a condicao na escrita. `CommitConflictError` nao e erro: significa
que outro worker venceu e o trabalho foi feito. O worker conta como `ja_processada`,
apaga a mensagem e segue.

### Observacoes continuam imutaveis

Nada e escrito na observacao original — nem um campo `processed_at`. O
[ADR-002](ADR-002-identidade-e-idempotencia.md) estabelece que registros de origem sao
imutaveis, e o resultado do processamento e informacao derivada, que vive em item
proprio.

## Consequencias

**Positivas**
- Efeito unico garantido por uma unica operacao condicional.
- Mais barato que transacao: uma escrita, nao `TransactWriteItems`.
- O resultado fica auditavel: worker, tentativas, duracao, resumo e `correlation_id`.
- A Fase 5 substitui o processador sem tocar nesta garantia.

**Negativas**
- Um item por observacao processada: o armazenamento cresce junto com o volume.
- Reprocessar de proposito exige apagar o marcador — nao ha caminho acidental.
- A consulta previa gasta uma leitura que, no caminho feliz, nao encontra nada.

## Alternativas consideradas

| Alternativa | Motivo da rejeicao |
|---|---|
| Marcador e resultado em itens separados, em transacao | Funciona, mas custa 2x WCU por item e resolve com transacao o que um item unico resolve de graca |
| Apenas a consulta previa, sem condicao | Tem janela de corrida; dois workers processam a mesma mensagem |
| Campo `processed_at` na observacao | Viola a imutabilidade do ADR-002 e destroi o historico |
| Deduplicacao so na fila | Vale enquanto a mensagem esta na fila; apos consumida e apagada, a republicacao entra de novo |
| Confiar em exactly-once do broker | SQS Standard nao oferece; FIFO oferece janela limitada e custa throughput |
