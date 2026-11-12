# Performance — Fase 7

Medicoes de carga da plataforma. **Tudo aqui foi obtido localmente**, contra DynamoDB
Local em container, e nao vale como previsao de desempenho na AWS — ver
[metodologia.md](metodologia.md) para o que estes numeros podem e nao podem dizer.

Resultados brutos em [`runs/`](runs/), um JSON por corrida.

---

## 1. Teto por caminho

Cada caminho isolado, 200 usuarios, acervo de 1.000 registros.

| Caminho | Teto | P50 | P95 | O que faz |
|---|---|---|---|---|
| `replay` | **571,5 req/s** | 21 ms | 200 ms | 1 `GetItem` e sai |
| `duplicata` | **247,8 req/s** | 300 ms | 1.500 ms | + `Query` no `gsi_natural` + update |
| `novo` | **103,8 req/s** | 1.400 ms | 2.600 ms | + transacao de 3 itens, trilha, publicacao, baixa do outbox |

**Esta tabela e a identificacao do gargalo.** Mesma pilha, mesmo processo, mesma
concorrencia: 5,5x de diferenca entre o caminho que so le e o que escreve. O custo fixo
de atender uma requisicao nao e o limite — o mesmo FastAPI entrega 571 req/s quando nao
precisa escrever.

Cada camada de trabalho de escrita corta a capacidade aproximadamente pela metade.

## 2. Onde vao os milissegundos do caminho de escrita

Decomposto no regime nao saturado (10 usuarios), onde a latencia reflete trabalho e nao
espera em fila.

| Configuracao | P50 do `novo` | Parcela |
|---|---|---|
| Completo | 16 ms | — |
| Sem trilha | 12 ms | trilha = **4 ms (25%)** |
| Sem publicacao na fila | 12 ms | fila = **4 ms (25%)** |
| Sem as duas | 9 ms | nucleo = **9 ms (56%)** |

O nucleo e validacao, normalizacao, `GetItem` de idempotencia, `Query` de fingerprint e
a transacao de 3 itens.

> **A observabilidade da Fase 6 custa tanto quanto toda a publicacao na fila.** Quatro
> milissegundos em dezesseis. E um numero defensavel para o que ela entrega — a trilha
> que atravessa processos —, mas e um quarto do caminho de ingestao, e quem precisar
> desse quarto agora tem `NEXUS_TRAIL_ENABLED=false` e sabe exatamente o que ganha.

## 3. Concorrencia

Acervo de 1.000 registros, mistura ponderada.

| Usuarios | req/s | P50 | P95 | P99 |
|---|---|---|---|---|
| 10 | 31,8 | 14 ms | 31 ms | 69 ms |
| 50 | 94,8 | 31 ms | 1.200 ms | 2.100 ms |
| 200 | 158,9 | 740 ms | 2.300 ms | 2.800 ms |

**O joelho esta entre 10 e 50 usuarios.** Abaixo dele o sistema responde em dezenas de
milissegundos; acima, a vazao continua subindo enquanto a latencia explode — o
comportamento classico de uma fila se formando. Com 200 usuarios a vazao e 5x maior que
com 10, e a espera e 50x.

## 4. Volume do acervo

Carga fixa de 50 usuarios, acervo variando.

| Acervo | req/s | P50 | P95 | P99 |
|---|---|---|---|---|
| 100 | 122,0 | 28 ms | 520 ms | 1.300 ms |
| 1.000 | 109,1 | 27 ms | 1.100 ms | 1.600 ms |
| 10.000 | 70,3 | 190 ms | 1.800 ms | 2.200 ms |

Com 10.000 registros o outbox acumulou pendencias pela primeira vez: a publicacao
inline deixou de dar conta e o dispatcher — a rede de seguranca do ADR-003 — passou a
ser necessario de fato.

> **Ressalva:** uma corrida por configuracao. A queda de 43% esta acima da dispersao
> medida (10% a 40%), mas por pouco. A tendencia e confiavel; a magnitude, menos.

## 5. Processos da API: sem efeito detectavel

Tres repeticoes por configuracao, estado zerado antes de cada corrida, 200 usuarios.

| Processos | req/s por corrida | Media | Desvio | CV |
|---|---|---|---|---|
| 1 | 63,6 · 108,5 · 99,2 | 90,4 | 23,7 | 26% |
| 4 | 98,4 · 82,0 · 83,0 | 87,8 | 9,2 | 10% |

**Diferenca de 3%, dentro da dispersao.** Escalar a API horizontalmente nao move o teto
neste ambiente — o que e coerente com a secao 1: o limite esta no trabalho de escrita,
nao em capacidade de atendimento.

Com 4 processos o container encosta no proprio teto de CPU (pico de 201,5% de 200%) e a
vazao nao sobe. Capacidade de CPU disponivel nao era a restricao ativa.

## 6. Candidatos eliminados por medicao

| Candidato | Evidencia | Veredito |
|---|---|---|
| CPU do DynamoDB Local | mediana de 38-44% do teto de 2 CPUs | Nao e |
| Latencia do armazenamento | `GetItem` de 0,73 ms ocioso para 2,28 ms sob carga | Nao explica centenas de ms |
| Gerador de carga | 18-21% de um nucleo; aviso do Locust nunca disparou | Nao e |
| Numero de processos da API | sem efeito detectavel (secao 5) | Nao e |
| Pool de conexoes do botocore | 100,6 vs 100,8 req/s com 10 e 50 conexoes | Nao e |

O pool merece nota. O aviso `Connection pool is full` aparece nos logs sob concorrencia,
e o padrao do botocore e 10 conexoes — parecia um gargalo obvio. Nao e, localmente: o
round-trip ao DynamoDB Local e sub-milissegundo e o pool nunca aperta. Na AWS, com
latencia de rede real, o calculo muda. A configuracao `NEXUS_DYNAMO_MAX_POOL_CONNECTIONS`
existe desde esta fase com o padrao **inalterado** em 10, para quando isso for medivel.

## 7. Particao quente do `gsi_recency`

`docs/architecture/access-patterns.md` registrava desde a Fase 1 que o indice usa
`PK = "RECORDS#<tipo>"` — uma particao so para todos os registros de um tipo — e
afirmava que o limite de 1.000 WCU/s "nao e alcancado nos volumes deste projeto". A
afirmacao estava certa e **nunca tinha sido medida**.

`tools/particao_quente.py` fecha isso usando o serializador real:

| | |
|---|---|
| Item representativo | **701 bytes** |
| Projecao do indice | `ALL` |
| WCU por escrita no indice | **1** |
| Saturacao da particao | **1.000 registros/s** |

Medimos 104 req/s de registros novos localmente, e a AWS limita a conta a 10 execucoes
Lambda concorrentes. A mitigacao por sharding continua desnecessaria — agora por
numero.

> **Margem menor do que parecia.** 701 bytes sao 68% de um bloco de 1 KB. Um payload um
> pouco mais rico passa de 1.024 bytes, a escrita vira 2 WCU e o teto cai para 500
> registros/s. A folga e de 32% no tamanho do item, nao nos trezentos por cento que a
> distancia entre 104 e 1.000 sugere.

## 8. Cold start

**Nao medido.** Exige reimplantar a infraestrutura AWS, destruida em 09/11/2026. A
decisao de nao medir — e por que vazao na AWS nao seria medivel nesta conta de todo
jeito — esta em [COSTS.md](../../COSTS.md).

O que existe e um analogo local: a primeira requisicao de cada usuario, contra conexoes
ainda nao estabelecidas, roda entre **116 e 310 ms** contra 13-21 ms em regime. Toda
corrida separa esse numero do agregado, porque misturado ele empurra a cauda para cima
sem representar nada que um cliente veria depois do primeiro segundo.
