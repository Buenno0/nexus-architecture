# Corridas

Um JSON por corrida de carga, gravado por `tools/loadtest.py`. Cada arquivo registra os
parametros, o ambiente efetivo (processos da API, trilha ligada ou nao, acervo
pre-carregado), a latencia por cenario, o delta dos contadores, a profundidade de fila e
outbox antes e depois, e se o gerador saturou.

Os CSVs do Locust **nao** sao versionados: sao o rascunho de onde estes JSON saem.

## Como ler os nomes

| Prefixo | O que compara |
|---|---|
| `volume-N` | acervo de N registros, carga fixa |
| `concorrencia-N` | N usuarios simultaneos, acervo fixo |
| `workers-N` | N processos uvicorn — **inconclusivo**, ver `ctrl-wN-*` |
| `trilha-on` / `trilha-off` | instrumentacao da Fase 6 — **inconclusivo**, ver `linear-trilha-*` |
| `ctrl-wN-i` | repeticao i, estado zerado antes de cada corrida |
| `linear-trilha-*-i` | repeticao i no regime nao saturado (10 usuarios) |
| `teto-<caminho>` | um cenario isolado, para medir a capacidade daquele caminho |
| `capacidade-<caminho>` | **descartado**: isolamento defeituoso, media 2/11 dos turnos |
| `pool-N-i` | repeticao i com N conexoes no pool do botocore |
| `decomp-*` | caminho `novo` com componentes desligados um a um |
| `gargalo` | corrida instrumentada com amostragem de CPU |
| `sonda-*` | latencia de um `GetItem`, ocioso e sob carga |

As corridas marcadas como inconclusivas ou descartadas **ficam aqui de proposito**. O
relatorio explica por que cada uma nao concluiu, e apagar a evidencia tornaria a
explicacao impossivel de verificar.
