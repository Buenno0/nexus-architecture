# Verificacao — relatorio consolidado

Um relatorio por fase, mais esta consolidacao. Os relatorios de fase sao **registro
historico e nao sao reescritos**: uma limitacao listada na Fase 1 continua la mesmo
depois de resolvida, porque apagar o que se sabia na epoca apagaria a razao da decisao
seguinte.

Esta pagina existe por causa disso. Quem abre `phase-1-report.md` hoje le "nao ha fila"
— verdade em 06/11, falso desde a Fase 2. **A secao "O que mudou de estado" abaixo e a
que vale para o estado atual.**

Ultima atualizacao: 2026-11-12, ao concluir a Fase 8.

## Relatorios

| Fase | Modulo | Relatorio | O que ele prova |
|---|---|---|---|
| 1 | Ingestion | [phase-1-report.md](phase-1-report.md) | Validacao na borda, idempotencia por operacao, transacao atomica com o outbox |
| 2 | Queue Engine | [phase-2-report.md](phase-2-report.md) | Visibility timeout, retentativa com backoff, DLQ, redrive, idempotencia no consumo |
| 3 | Cloud Infrastructure | [phase-3-report.md](phase-3-report.md) | A mesma plataforma na AWS — aplicada, verificada e destruida |
| 4 | Control Center | [phase-4-report.md](phase-4-report.md) | Toda metrica rotula a origem; nenhum numero inventado |
| 5 | Entity Resolution | [phase-5-report.md](phase-5-report.md) | Blocking, score auditavel, tres faixas, nenhuma fusao automatica em duvida |
| 6 | Observability | [phase-6-report.md](phase-6-report.md) | Trilha durável que atravessa processos, serie persistida, alertas calculados |
| 7 | Performance | [phase-7-report.md](phase-7-report.md) | Gargalo identificado com evidencia — e quatro erros de medicao corrigidos |
| 8 | Finalizacao | [phase-8-report.md](phase-8-report.md) | A documentacao faz o que promete — verificado executando-a, e ela falhou duas vezes antes |

Metodologia e corridas de carga: [docs/performance/](../performance/).

## Estado da verificacao em 2026-11-12

| | |
|---|---|
| Testes Python | **555**, todos passando |
| Cobertura | **89%** (`src/nexus`, branch coverage) |
| Testes do Control Center | **115**, todos passando |
| `ruff check` / `ruff format` | limpos |
| `mypy --strict` | limpo |
| `tsc --noEmit` / `eslint` | limpos |
| Recursos de nuvem no ar | **nenhum** |
| Custo acumulado do projeto | **US$ 0,0001** (DynamoDB, 3 dias na Fase 3) |

Os testes de integracao rodam contra DynamoDB Local **de verdade** — transacao, indice
esparso e escrita condicional nao sao simulados. O CI os executa; a variavel
`NEXUS_TEST_REQUIRE_DYNAMO` impede que a ausencia do banco vire suite pulada em silencio.

O pipeline roda no GitHub Actions desde 12/11/2026, em
[Buenno0/nexus-architecture](https://github.com/Buenno0/nexus-architecture/actions/runs/43149734246).

## O que mudou de estado

Limitacoes que os relatorios de fase registram e que **nao valem mais**:

| Registrada em | Limitacao | Resolvida em |
|---|---|---|
| Fase 1 | "Nao ha fila: eventos ficam pendentes no outbox" | Fase 2 |
| Fase 1 | "Particao quente nao alcancada; mitigacao documentada" — era suposicao | Fase 7, medida: satura a 1.000 reg/s, medimos 104 |
| Fase 2 | "Nao ha Entity Resolution; o processador declara `not_implemented`" | Fase 5 |
| Fase 2 | "A fila so e acessada de dentro do container" | Fase 3 na AWS (SQS). **Continua valendo localmente** |
| Fase 4 | "O historico vive na aba; recarregar zera" | Fase 6, serie persistida |
| Fase 5 | "Nao ha interface de revisao, apenas endpoints" | Fase 4, tela Entity Resolution com confirmar/recusar |
| Fase 6 | "Sem teste de carga; o custo da trilha sob volume e desconhecido" | Fase 7: **4 ms**, 25% do caminho de ingestao |
| Fase 1–7 | "CI/CD fora de escopo" | Fase 8 — **verde no GitHub Actions** desde 12/11/2026 |

## Limitacoes atuais, agrupadas por causa

### A infraestrutura AWS nao existe

Causa comum do maior grupo. A Fase 3 aplicou, verificou e destruiu.

- Cold start nao foi quantificado.
- Nenhuma medicao de desempenho sob rede real. A Fase 7 **recusou** medir na AWS: a
  conta tem cota de 10 execucoes concorrentes, e qualquer vazao medida la seria a cota.
- `NEXUS_DYNAMO_MAX_POOL_CONNECTIONS` nao foi validado onde importaria. Local nao teve
  efeito mensuravel (100,6 contra 100,8 req/s).
- A amostragem da serie pelo EventBridge Scheduler existe, e testada localmente e
  **nunca foi exercitada na nuvem**.
- O login por Cognito tem teste de componente, nao de integracao.
- O Control Center nao esta publicado na Vercel.
- O primeiro deploy usaria `AdministratorAccess` — divida registrada no runbook.

### Decisoes deliberadas, nao pendencias

Estas nao sao para resolver. Cada uma e uma troca escolhida, com a razao registrada.

- **A trilha nao e auditoria.** Best-effort por decisao (ADR-010): pode ter buracos. A
  garantia esta em `StoredRecord` e `ProcessingResult`, que sao transacionais.
- **A amostragem e oportunista.** Sem ninguem observando, nada e amostrado — e a
  interface declara quantos baldes faltaram em vez de interpolar uma linha reta.
- **Deduplicacao por conteudo e best-effort sob concorrencia.** O indice e eventualmente
  consistente; a resolucao autoritativa de identidade e do Entity Resolution.
- **Teto de cluster recusa fusoes legitimas.** Falso negativo visivel no lugar de falso
  positivo silencioso — o erro critico do projeto nao e simetrico.
- **Nada processa sozinho.** Sem consumidor residente, uma mensagem que falha espera ate
  alguem invocar o worker. E o preco da execucao sob demanda, aceito explicitamente.
- **Contadores de `/metrics` sao de um processo.** Zeram no reinicio, nao agregam entre
  replicas, e com varios workers refletem so quem respondeu. A interface rotula
  `processo`; profundidade de fila e contadores de resolucao vem do armazenamento.

### Pendencias reais

- **A fila local nao atravessa a fronteira do container** (ADR-004), e nao escala para
  varios hosts. Por desenho local; some com SQS.
- **Nao ha autenticacao no ambiente local.** Os endpoints `/v1/ops/*` disparam trabalho.
  Na AWS ha authorizer JWT via Cognito; local, nao.
- **Sem testes ponta a ponta em navegador.** A verificacao do Control Center e por
  componente mais inspecao manual.
- **Uma unica rota no dashboard.** A aba selecionada nao vai para a URL.
- **Nao ha como desfazer uma fusao especifica.** A evidencia permite localizar a aresta
  culpada; reverter nao foi implementado.
- **Rejeicao de par nao impede ligacao por um terceiro registro.**
- **Nao houve profiling.** A decomposicao do caminho de escrita e por diferenca entre
  configuracoes: atribui custo a componentes, nao a funcoes.
- **Metricas de qualidade da resolucao valem para dados sinteticos.** Pesos e limiares
  foram calibrados contra este conjunto; nao sao verdades gerais.

## O que a verificacao nao cobre

Dito uma vez, sem rodeio:

- Nenhum comportamento sob dados reais. **O projeto usa exclusivamente dados
  sinteticos**, por decisao, do inicio ao fim.
- Nenhum numero de desempenho que valha como previsao para a AWS. DynamoDB Local nao
  estrangula, nao simula rede e nao cobra.
- Nenhuma garantia de disponibilidade. Nao ha SLO, nao ha teste de resiliencia de
  infraestrutura, e nada aqui esta dimensionado para producao.

## O habito que a Fase 7 ensinou

A secao 6 do [relatorio da Fase 7](phase-7-report.md) registra quatro erros de medicao,
dois deles com o sinal invertido — a mesma configuracao reportada como melhor e como
pior em corridas diferentes.

O padrao foi sempre o mesmo: um numero, uma explicacao plausivel, uma conclusao
publicada. A explicacao plausivel errou nas quatro vezes.

**Repetir a medicao e olhar a dispersao antes de olhar a diferenca** foi o unico
antidoto que funcionou, e vale para qualquer numero deste repositorio.
