# Padroes de acesso — DynamoDB single-table

Em DynamoDB a modelagem deriva das consultas, nao das entidades. Este documento define
as consultas **antes** das tabelas, conforme exigido pelo [ADR-001](../adr/ADR-001-dynamodb-local.md).

Tabela unica: `nexus-records`.

## Consultas exigidas pelas Fases 1 e 2

| # | Padrao de acesso | Mecanismo | Custo |
|---|---|---|---|
| 1 | Obter observacao por `record_id` | `GetItem` na tabela base | O(1) |
| 2 | Listar observacoes por tipo, mais recentes primeiro | `Query` em `gsi_recency` | O(pagina) |
| 3 | Localizar observacoes com a mesma chave natural | `Query` em `gsi_natural` | O(observacoes da entidade) |
| 4 | Detectar reenvio byte-identico | `Query` em `gsi_natural` com SK = fingerprint | O(1) |
| 5 | Recuperar operacao por chave de idempotencia | `GetItem` na tabela base | O(1) |
| 6 | Listar eventos de outbox pendentes | `Query` em `gsi_outbox_pending` | O(pendentes) |
| 7 | Verificar se uma observacao ja foi processada | `GetItem` na tabela base | O(1) |

## Consultas exigidas pela Fase 5

| # | Padrao de acesso | Mecanismo | Custo |
|---|---|---|---|
| 8 | Localizar candidatos por chave de bloco | `Query` com PK = `BLOCK#<chave>` | O(registros no bloco) |
| 9 | Obter entidade, membros e eventos de fusao | `Query` com PK = `ENTITY#<id>` | O(membros) |
| 10 | Descobrir a entidade de uma observacao | `Query` com PK = `RECORD#<id>` | O(1) |
| 11 | Listar pares pendentes de revisao | `Query` em `gsi_review` | O(pendentes) |
| 12 | Obter um par de revisao por identificador | `GetItem` na tabela base | O(1) |

O padrao 10 so funciona porque observacao e vinculo compartilham a mesma particao: uma
unica `Query` em `RECORD#<id>` devolve o registro **e** a entidade a que ele pertence.
E exatamente o beneficio que a modelagem single-table existe para dar.

## Consultas exigidas pela Fase 6

| # | Padrao de acesso | Mecanismo | Custo |
|---|---|---|---|
| 13 | Reconstruir a jornada de uma observacao | `Query` com PK = `TRAIL#<record_id>` | O(marcos) |
| 14 | Ler a serie temporal de uma metrica | `Query` com PK = `SERIES#<metrica>` | O(baldes na janela) |
| 15 | Localizar o evento de outbox pendente mais antigo | `Query` em `gsi_outbox_pending`, limite 1 | O(1) |

### Por que a trilha e chaveada por `record_id`, e nao por `correlation_id`

Chavear por `correlation_id` pareceria natural: e ele que atravessa os processos. Mas a
pergunta que se faz numa investigacao e *"o que aconteceu com este registro"*, e um
registro reprocessado sob uma versao nova de processador tem **varios**
`correlation_id` — um por passagem.

Com `TRAIL#<record_id>`, uma unica `Query` devolve a jornada inteira, incluindo os
reprocessamentos. O `correlation_id` vai como atributo de cada marco, para cruzar com
os logs.

Beneficio adicional: cabe na tabela base. Nenhum indice novo.

### Por que o `SK` comeca pelo carimbo de tempo

`SK = <carimbo ISO>#<ulid>` faz a `Query` devolver os marcos **ja em ordem
cronologica**, sem ordenacao em memoria. O ULID no fim desempata marcos emitidos no
mesmo milissegundo por processos diferentes.

### Baldes na serie temporal

`SK = <carimbo arredondado ao intervalo de amostragem>`. O arredondamento e o que
permite escrita condicional: duas replicas da API, ou duas abas do dashboard, pedindo
`/metrics` no mesmo intervalo tentam gravar **a mesma chave**, e so a primeira vence.
Sem o balde, cada leitura viraria uma amostra e a serie teria densidade proporcional ao
numero de observadores, nao ao tempo.

## Chaves da tabela base

| Item | PK | SK | Fase |
|---|---|---|---|
| Observacao | `RECORD#<record_id>` | `RECORD#<record_id>` | 1 |
| Idempotencia | `IDEMP#<hash(source,key)>` | `IDEMP#<hash(source,key)>` | 1 |
| Evento de outbox | `OUTBOX#<event_id>` | `OUTBOX#<event_id>` | 1 |
| Resultado de processamento | `PROCESSED#<record_id>#<versao>` | idem | 2 |
| Chave de bloco | `BLOCK#<chave>` | `RECORD#<record_id>` | 5 |
| Entidade canonica | `ENTITY#<entity_id>` | `ENTITY#<entity_id>` | 5 |
| Vinculo de membro | `ENTITY#<entity_id>` | `MEMBER#<record_id>` | 5 |
| Evento de fusao | `ENTITY#<entity_id>` | `MERGE#<ulid>` | 5 |
| Vinculo reverso | `RECORD#<record_id>` | `ENTITY#<entity_id>` | 5 |
| Par de revisao | `REVIEW#<pair_id>` | `REVIEW#<pair_id>` | 5 |
| Marco da trilha | `TRAIL#<record_id>` | `<carimbo>#<ulid>` | 6 |
| Amostra de metrica | `SERIES#<metrica>` | `<carimbo do balde>` | 6 |

PK e SK iguais nos itens simples: todos sao acessados por identidade direta. A chave
composta foi reservada desde a Fase 1 para itens filhos — e e ela que permite a Fase 5
adicionar entidades, vinculos e blocos **sem migracao nenhuma**.

### Por que o marcador de processamento leva a versao

`PROCESSED#<record_id>#<versao>` em vez de `PROCESSED#<record_id>`. A versao identifica o
processador que produziu o resultado.

Sem ela, trocar o `DefaultProcessor` pelo resolvedor da Fase 5 nao reprocessaria nada: o
marcador antigo existe e a escrita condicional recusaria. Com ela, a chave nova nao
colide, o acervo reprocessa naturalmente e o resultado de cada versao fica lado a lado
para comparacao. Ver ADR-007.

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
na mesma particao, limitada a 1.000 WCU/s na AWS.

**Medido na Fase 7** (`tools/particao_quente.py`, sobre o serializador real): o item
representativo tem **701 bytes**, entao a escrita no indice custa **1 WCU** e a
particao satura a **1.000 registros/s**. A ingestao local atinge 104 req/s de registros
novos, e a conta AWS limita a 10 execucoes Lambda concorrentes. A mitigacao por sharding
continua desnecessaria — agora por numero, nao por intuicao.

> A folga e menor do que a distancia entre 104 e 1.000 sugere. 701 bytes sao 68% de um
> bloco de 1 KB: um payload um pouco mais rico passa de 1.024 bytes, a escrita vira
> 2 WCU e o teto cai para 500 registros/s. A margem real esta no tamanho do item.

Caminho de mitigacao, se necessario: `RECORDS#<tipo>#<shard>` com leitura em N shards e
merge ordenado. Nao implementado agora porque adicionaria complexidade de paginacao sem
resolver problema existente.

### `gsi_review` — padrao 11

```
PK = review_shard  ("REVIEW#<0..N-1>")     SK = created_at
```

Projecao `KEYS_ONLY`, **esparso**: `review_shard` existe somente enquanto o par esta
pendente. Decidido o par, o atributo e removido e o item deixa o indice.

Mesmo padrao do `gsi_outbox_pending`, pela mesma razao: o indice acompanha a fila de
revisao, nao o tamanho da tabela.

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

Atributo `expires_at` (epoch em segundos), aplicado a tres classes de item:

| Item | TTL | Por que expira |
|---|---|---|
| Idempotencia | 48h | Protege contra replay; depois disso nao ha replay a proteger |
| Marco de trilha | 7 dias | Ajuda a investigar; investigacao de semanas atras usa outra fonte |
| Amostra de metrica | 7 dias | Janela de observacao, nao historico permanente |

Observacoes, eventos de outbox, entidades e resultados de processamento **nunca**
expiram: sao dado, nao observacao sobre o dado.

## Blocking: por que nao reaproveitar `gsi_natural`

`natural_key` e um **hash** (`src/nexus/shared/identity.py`). Hash so responde igualdade
exata — nao existe "hash parecido". Ele resolve o padrao 3, localizar observacoes da
mesma chave natural, mas nao serve para encontrar candidatos aproximados.

Por isso a Fase 5 grava chaves de bloco proprias, em texto claro, uma por criterio
(documento, e-mail, nome, telefone). Um registro produz varias; dois registros sao
candidatos se compartilham qualquer uma.

As chaves sao gravadas **depois** da comparacao, para que o registro corrente nao
apareca entre os proprios candidatos.

## O que nao e suportado

- Agregacao no banco. Metricas sao calculadas na aplicacao.
- Busca textual livre. Entity Resolution compara em memoria sobre candidatos obtidos por
  blocking, nunca varredura.
- `Scan` em caminho quente. Qualquer `Scan` em producao e defeito de modelagem.
- Comparacao de todos contra todos. Sem blocking a comparacao e O(n²) e inviavel.
