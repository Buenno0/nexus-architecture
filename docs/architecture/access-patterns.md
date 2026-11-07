# Padroes de acesso — DynamoDB single-table

Em DynamoDB a modelagem deriva das consultas, nao das entidades. Este documento define
as consultas **antes** das tabelas, conforme exigido pelo [ADR-001](../adr/ADR-001-dynamodb-local.md).

Tabela unica: `nexus-records`.

## Consultas exigidas pela Fase 1

| # | Padrao de acesso | Mecanismo | Custo |
|---|---|---|---|
| 1 | Obter observacao por `record_id` | `GetItem` na tabela base | O(1) |
| 2 | Listar observacoes por tipo, mais recentes primeiro | `Query` em `gsi_recency` | O(pagina) |
| 3 | Localizar observacoes com a mesma chave natural | `Query` em `gsi_natural` | O(observacoes da entidade) |
| 4 | Detectar reenvio byte-identico | `Query` em `gsi_natural` com SK = fingerprint | O(1) |
| 5 | Recuperar operacao por chave de idempotencia | `GetItem` na tabela base | O(1) |
| 6 | Listar eventos de outbox pendentes | `Query` em `gsi_outbox_pending` | O(pendentes) |

## Chaves da tabela base

| Item | PK | SK |
|---|---|---|
| Observacao | `RECORD#<record_id>` | `RECORD#<record_id>` |
| Idempotencia | `IDEMP#<hash(source,key)>` | `IDEMP#<hash(source,key)>` |
| Evento de outbox | `OUTBOX#<event_id>` | `OUTBOX#<event_id>` |

PK e SK iguais nos itens simples: todos sao acessados por identidade direta. A chave
composta fica disponivel para itens filhos (vinculos de entidade) na Fase 5, sem
migracao.

## Indices secundarios globais

### `gsi_natural` — padroes 3 e 4

```
PK = natural_key          SK = record_fingerprint
```

Projecao `ALL`. Uma `Query` por `natural_key` devolve todas as observacoes daquela
entidade candidata. Acrescentando `SK = fingerprint`, responde em uma leitura se aquele
conteudo exato ja foi observado.

**A combinacao nao e unica por design.** Mesma chave natural com fingerprints diferentes
significa observacoes distintas e legitimas da mesma entidade — ver
[ADR-002](../adr/ADR-002-identidade-e-idempotencia.md).

### `gsi_recency` — padrao 2

```
PK = "RECORDS#<record_type>"     SK = record_id (ULID)
```

Projecao `ALL`. O ULID ordena lexicograficamente por tempo de criacao, entao listar em
ordem cronologica inversa e `ScanIndexForward=False` — sem ordenacao em memoria.

**Limitacao conhecida: particao quente.** Com PK por tipo, toda escrita de pessoas cai
na mesma particao, limitada a 1.000 WCU/s na AWS. Nos volumes deste projeto
(milhares de registros sob demanda) isso nao e alcancado.

Caminho de mitigacao, se necessario: `RECORDS#<tipo>#<shard>` com leitura em N shards e
merge ordenado. Nao implementado agora porque adicionaria complexidade de paginacao sem
resolver problema existente.

### `gsi_outbox_pending` — padrao 6

```
PK = pending_shard  ("PENDING#<0..N-1>")     SK = next_attempt_at
```

Projecao `KEYS_ONLY` — o dispatcher so precisa localizar o item; o conteudo vem de um
`GetItem` na tabela base. Projecao menor significa indice menor e escrita mais barata.

**Indice esparso:** `pending_shard` existe somente enquanto o evento esta pendente. Ao
despachar, o atributo e removido e o item deixa o indice. O tamanho do indice acompanha
o backlog, nao a tabela. Ver [ADR-003](../adr/ADR-003-transactional-outbox.md).

## TTL

Atributo `expires_at` (epoch em segundos), aplicado apenas aos itens de idempotencia.
Observacoes e eventos de outbox nunca expiram automaticamente.

Sem TTL, os registros de idempotencia cresceriam indefinidamente — eles sao a unica
classe de item cujo valor e temporario por natureza.

## O que nao e suportado

- Agregacao no banco. Metricas sao calculadas na aplicacao.
- Busca textual livre. Entity Resolution faz comparacao em memoria sobre candidatos
  obtidos por blocking, nunca varredura.
- `Scan` em caminho quente. Qualquer `Scan` em producao e defeito de modelagem.
