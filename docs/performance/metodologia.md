# Metodologia das medicoes — Fase 7

Este documento descreve **como** os numeros de `docs/performance/` foram obtidos, e o
que eles nao podem dizer. Ele existe porque a propria Fase 7 mostrou, por tres vezes,
que um numero sem metodo leva a conclusao errada com a mesma confianca de um numero
com metodo.

---

## O ambiente

| Componente | Configuracao |
|---|---|
| Maquina | 10 nucleos, 16 GB; Docker Desktop com 10 CPUs e ~7,7 GB |
| API | container com **teto de 2 CPUs e 2 GB**, uvicorn, 1 processo por padrao |
| DynamoDB | DynamoDB Local 2.5.2, container com **teto de 2 CPUs e 2 GB** |
| Fila | SQLite em volume nomeado, dentro do container da API — ADR-004 |
| Gerador | Locust 2.47, **no host**, fora dos tetos acima |

Os tetos sao explicitos no `docker-compose.yml` desde esta fase. Sem eles, API, banco e
gerador disputam os mesmos nucleos e o numero medido depende de quem ganhou o
escalonador naquele segundo — a medicao deixa de ter unidade.

## Os cenarios

Pesos distintos de proposito (`tests/load/locustfile.py`):

| Cenario | Peso | O que exercita |
|---|---|---|
| Registro novo | 6 | Caminho completo: normalizacao, indice, transacao, trilha |
| Conteudo duplicado | 2 | Consulta por fingerprint no `gsi_natural` |
| Replay | 2 | Saida antecipada por idempotencia: um `GetItem` |
| Listagem | 1 | `Query` no `gsi_recency` |

Um teste que so envia registros novos mede apenas o caminho mais caro e esconde quanto
replay e deduplicacao custam.

**O `rps` de um cenario dentro da mistura e o peso dele, nao o teto dele.** Para medir
capacidade por caminho, `NEXUS_LOAD_SCENARIO` restringe a carga a um cenario so.

## O que cada corrida registra

`tools/loadtest.py` grava, alem da latencia:

- **Delta dos contadores** de `/metrics`, para saber quantas ingestoes de fato
  ocorreram em vez de supor pelo numero de requisicoes.
- **Profundidade de fila e outbox**, antes e depois. Se o outbox cresce enquanto a
  latencia da API se mantem, o gargalo e consumo e nao ingestao — conclusoes opostas
  que sem estes dois numeros nao se distinguem.
- **Processos uvicorn**, contados dentro do container.
- **Saturacao do gerador**, pelo aviso do proprio Locust e pela CPU do processo.

O **aquecimento** — a requisicao que cada usuario faz ao subir, contra conexoes ainda
nao estabelecidas — e separado do agregado. Misturado, empurra a cauda para cima sem
representar nada que um cliente veria depois do primeiro segundo.

## Isolamento entre corridas

`tools/campanha.py` executa `docker compose down -v` e pre-carrega o acervo **antes de
cada corrida**, drenando a fila em seguida. Sem isso a segunda medicao herda o acervo
da primeira, e a diferenca entre elas confunde duas causas — mais dados na tabela e
mais carga — que a campanha existe para separar.

Isso foi aprendido errando: a primeira tentativa de repetir o eixo de workers
alternou as configuracoes **sem** reiniciar, imaginando que alternar cancelaria a
deriva. Nao cancela. A tabela cresce monotonicamente ao longo das seis corridas, entao
a configuracao que roda em segundo lugar enfrenta sempre um acervo maior.

## Repeticao e dispersao

**Uma corrida nao e uma medicao.** Repetindo a mesma configuracao tres vezes, o
coeficiente de variacao da vazao ficou entre **10% e 40%**.

Isso define um piso de deteccao. Efeitos menores que a dispersao **nao sao
observaveis** com uma corrida por configuracao, por mais limpa que a corrida pareca.
Todo numero comparativo neste diretorio traz a media das repeticoes e o desvio, nunca
um ponto solitario.

A variancia nao e defeito do arnes: sob saturacao quase todo o tempo de resposta e
espera em fila, e fila amplifica qualquer perturbacao do ambiente. Por isso o custo de
um **trabalho** — como as escritas da trilha — e medido no regime nao saturado, com
10 usuarios, onde a latencia reflete o que a requisicao faz e nao quanto tempo ela
esperou pela anterior.

## Percentis, nunca a media sozinha

P50, P95 e P99 em toda tabela. A media acompanha, nunca lidera: ela esconde a cauda, e
a cauda e o que o usuario sente. O percentil usado e o do vizinho mais proximo, sem
interpolacao — o valor devolvido corresponde a uma requisicao que de fato aconteceu.

## O que estes numeros nao podem dizer

- **Nao sao previsao de desempenho na AWS.** DynamoDB Local nao aplica limites de
  throughput, nao estrangula, nao tem particao quente e nao cobra. Ele e uma ferramenta
  de desenvolvimento, nao um modelo do servico.
- **Nao ha latencia de rede.** Tudo roda na mesma maquina.
- **Nao ha cold start.** Na AWS a primeira invocacao de uma Lambda inclui
  inicializacao. Essa parcela nao foi medida nesta fase; medi-la exige reimplantar a
  infraestrutura, decisao registrada em COSTS.md.
- **Vazao na AWS nao seria medivel nesta conta.** A cota e de 10 execucoes concorrentes
  no total: qualquer numero seria a cota, nao a arquitetura.
- **O ambiente e um laptop com outros processos.** Os tetos de CPU controlam a disputa
  entre os containers, nao a disputa com o resto do sistema operacional.
