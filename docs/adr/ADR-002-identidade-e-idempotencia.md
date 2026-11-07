# ADR-002 — Separacao entre operacao de ingestao, conteudo e entidade

- **Status:** Aceita
- **Data:** 2026-11-06

## Contexto

Um rascunho anterior definia uma unica chave:

```
idempotency_key = sha256(tipo + documento_normalizado + email_normalizado)
```

A API responderia `200` com o registro existente sempre que a chave repetisse.

**Esse desenho perde dados.** A mesma pessoa chegando com telefone atualizado produz a
mesma chave natural — e a atualizacao e descartada em silencio. Nada falha, nenhum erro
e registrado, e o dado novo simplesmente nao entra. Isso nao e deduplicacao.

A causa raiz e a confusao entre tres conceitos distintos.

## Decisao

Separar explicitamente:

| Conceito | Identifica | Origem |
|---|---|---|
| `idempotency_key` | uma **operacao de ingestao** | cliente, header `Idempotency-Key`, **obrigatorio** |
| `record_fingerprint` | um **conteudo normalizado** | servidor, `sha256` do payload canonizado |
| Entity Resolution | se registros **diferentes** sao a mesma entidade | assincrono, score auditavel |

### Registros de origem sao observacoes imutaveis

Um registro ingerido nunca e sobrescrito. Mesma chave natural com fingerprint diferente
significa **nova observacao**, aceita e enfileirada. O vinculo entre observacoes e
estabelecido pelo resolver, com score registrado e reversivel.

A API nunca julga identidade — ela nao tem informacao suficiente para isso.

### Contrato resultante

| Situacao | Resposta |
|---|---|
| Header `Idempotency-Key` ausente | `400 Bad Request` |
| Corpo invalido | `422 Unprocessable Entity` |
| Chave conhecida, mesmo corpo | `200` com a resposta armazenada (`Idempotency-Replayed: true`) |
| Chave conhecida, corpo diferente | `409 Conflict` |
| Mesma chave natural **e** mesmo fingerprint | `200`, `status="duplicate"`, nao enfileira |
| Observacao nova | `202 Accepted`, `status="accepted"` |

`409` em chave reusada com corpo diferente e deliberado: reusar a chave com payload
distinto e bug do cliente. Devolver a resposta antiga esconderia esse bug.

O registro de idempotencia e gravado **na mesma transacao** que a observacao. Grava-lo
depois reabriria a janela de inconsistencia que o [ADR-003](ADR-003-transactional-outbox.md)
existe para fechar.

## Consequencias

**Positivas**
- Atualizacoes legitimas nunca sao descartadas em silencio.
- Replay de requisicao e seguro e explicito.
- A decisao de identidade fica num unico lugar, auditavel e ajustavel sem tocar na API.
- O historico de observacoes permite reconstruir como uma entidade foi formada.

**Negativas**
- Volume de armazenamento cresce: toda observacao e mantida, nao substituida.
- Header obrigatorio quebra clientes simples e torna teste manual mais verboso
  (`curl` precisa sempre enviar `-H 'Idempotency-Key: ...'`).
- Registros de idempotencia precisam de TTL, senao crescem indefinidamente.

**Mitigacao**
- TTL nativo do DynamoDB nos registros de idempotencia (48h por padrao, configuravel).
- README e gerador de dados sinteticos sempre enviam o header.

## Alternativas consideradas

| Alternativa | Motivo da rejeicao |
|---|---|
| Chave unica derivada do conteudo | Descarta atualizacoes legitimas (o defeito original) |
| Header opcional | Ambiguidade sobre quem garante a identidade da operacao |
| Servidor gera a chave quando ausente | Reintroduz a confusao entre operacao e conteudo |
| Sobrescrever o registro na mesma chave natural | Destroi historico; impossibilita auditar a resolucao |
