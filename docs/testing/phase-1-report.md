# Relatorio de testes — Fase 1 (Nexus Ingestion)

Data: 2026-11-06 · Python 3.13.18 · DynamoDB Local 2.5.2

## Resumo

| Metrica | Valor |
|---|---|
| Testes | 169 |
| Falhas | 0 |
| Cobertura global | 91% |
| Cobertura `ingestion` | 88–100% por modulo |
| Cobertura `shared` | 100% |
| Tempo da suite | ~3 s |
| Ruff | sem erros |
| mypy `--strict` | sem erros |

```bash
make test     # suite completa com cobertura
make lint     # ruff + mypy strict
```

## Estrategia

**Unitarios** (sem Docker, ~0,3 s) usam um repositorio falso que reproduz as condicoes
de escrita do repositorio real. Um dublê que aceitasse qualquer escrita daria testes
verdes e producao quebrada.

**Integracao** rodam contra DynamoDB Local. Cada teste recebe uma **tabela propria**,
criada e destruida no escopo do caso — elimina a falha mais corrosiva em suite de
integracao: teste que passa isolado e falha em conjunto.

## O que foi exercitado

### Contrato de identidade (ADR-002)

| Cenario | Esperado | Resultado |
|---|---|---|
| Observacao nova | `202 accepted` | OK |
| Replay (mesma chave, mesmo corpo) | `202` + `Idempotency-Replayed: true` | OK |
| Chave reusada com corpo diferente | `409 idempotency_conflict` | OK |
| Conteudo byte-identico, chave nova | `200 duplicate`, `seen_count++` | OK |
| **Mesma entidade, conteudo novo** | **`202 accepted`, novo record_id** | **OK** |
| Header ausente / vazio / longo demais | `400` | OK |

A quinta linha e a regressao central: o desenho original derivava a chave de
idempotencia da chave natural e teria respondido `200 duplicate`, descartando a
atualizacao em silencio.

### Tentativas de quebrar o sistema

| Ataque | Resultado |
|---|---|
| Payload vazio, campo faltante, tipo errado | `422`, nunca `500` |
| Campo de 10 MB | `422` por limite de tamanho |
| Byte nulo e caracteres de controle | `422` |
| Unicode composto vs decomposto | Mesmo fingerprint (ruido de codificacao) |
| Emoji e acentos | Preservados integralmente |
| `Robert'); DROP TABLE records;--` | Armazenado como dado; persistencia intacta |
| Campo desconhecido no payload | `422` (`extra="forbid"`) |
| Cursor de paginacao adulterado | `400`, nunca `500` |
| Erro interno inesperado | `500` sem stack trace, nome de tabela ou ARN |

### Concorrencia

**50 requisicoes simultaneas com a mesma `Idempotency-Key` → exatamente 1 observacao.**
Verificado contra DynamoDB Local real, nao apenas no dublê.

A garantia vem da condicao `attribute_not_exists` dentro da transacao. Verificar antes
de gravar teria janela de corrida; a condicao e avaliada no momento da escrita.

### Transacao e outbox (ADR-003)

- Observacao, evento e idempotencia gravados atomicamente.
- Conflito nao deixa escrita parcial (verificado explicitamente).
- Evento pendente aparece no indice esparso; despacho o **remove** do indice e mantem
  o item na tabela base.
- Backoff cresce a cada tentativa.
- Tentativas esgotadas marcam `failed` e saem do indice, sem bloquear os demais.
- Falha de publicacao **nao** perde o registro: a observacao permanece consultavel e o
  evento fica pendente.

## Demonstracao com dados sinteticos

```bash
python tools/generator.py --count 500 --duplicate-rate 0.2 --variant-rate 0.1 --post --seed 2026
```

```
aceitos=400  duplicados=100  replays=0  conflitos=0  rejeitados=0  falhas=0
```

Os 400 aceitos sao ~350 registros originais mais ~50 **variantes** — mesma entidade com
telefone diferente. Sob o desenho original, essas 50 atualizacoes legitimas teriam sido
contadas como duplicatas e perdidas.

Latencia observada (500 requisicoes, DynamoDB Local, maquina de desenvolvimento):

| p50 | p95 | p99 | max |
|---|---|---|---|
| 4,0 ms | 6,1 ms | 11,6 ms | 36,6 ms |

**Estes numeros nao sao previsao de desempenho na AWS.** DynamoDB Local nao aplica
limites de throughput nem simula latencia de rede. Medicao formal com Locust e escopo
da Fase 7.

## Defeitos encontrados e corrigidos durante a Fase 1

1. **`Decimal` nao serializavel.** O DynamoDB devolve numeros como `Decimal`; o corpo
   armazenado para replay era devolvido ao cliente sem conversao. A ingestao original
   funcionava e o replay falhava com `500`. Corrigido na fronteira de desserializacao.
2. **`ExpressionAttributeNames` vazio.** O DynamoDB recusa o mapa vazio; o parametro
   precisa ser omitido. Quebrava todo o caminho de retentativa do outbox.
3. **Divergencia de `outbox_shards`.** Servico e repositorio liam a configuracao
   separadamente. Com valores diferentes, o dispatcher varreria shards distintos dos
   que a ingestao escreve e eventos ficariam orfaos. A configuracao passou a ser
   injetada uma unica vez, e a restricao operacional foi registrada no ADR-003.
4. **Gerador produzindo e-mails invalidos.** Nomes em portugues com acentos e espacos
   geravam enderecos recusados por validacao. Defeito do gerador, nao da plataforma —
   mas teria sido reportado como falha da API.

## Limitacoes conhecidas

- **Nao ha autenticacao.** A API e aberta no ambiente local. Requisito da Fase 3.
- **Deduplicacao por conteudo e best-effort sob concorrencia.** A busca por fingerprint
  le um indice secundario global, eventualmente consistente. Requisicoes simultaneas com
  chaves distintas e mesmo conteudo podem criar mais de uma observacao. Aceito por
  desenho: a resolucao autoritativa de identidade e do Entity Resolution (Fase 5).
- **Metricas sao do processo.** Zeram no reinicio e nao agregam entre replicas.
- **Nao ha fila.** Eventos permanecem pendentes no outbox; o backlog e visivel em
  `/metrics`. Escopo da Fase 2.
- **Particao quente no `gsi_recency`.** PK por tipo concentra escritas numa particao.
  Nao alcancado nos volumes atuais; mitigacao por sharding documentada.
- **Sem validacao de digito verificador** em documentos sinteticos.
