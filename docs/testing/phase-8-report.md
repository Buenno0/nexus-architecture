# Fase 8 — Finalizacao

Data: 2026-11-12
Custo: **US$ 0,00** — nenhum recurso de nuvem criado nem consultado.

O objetivo da fase e o unico do projeto que nao se verifica rodando codigo: deixar a
plataforma compreensivel e reproduzivel por quem nao participou da construcao. A unica
forma honesta de testar isso e **executar o que a documentacao promete** e ver onde ela
mente.

Foi o que aconteceu: a demonstracao roteirizada falhou duas vezes antes de ficar pronta,
e as duas falhas eram defeitos reais, nao erros de roteiro.

## 1. O que foi implementado

| Entrega | Onde |
|---|---|
| Integracao continua | `.github/workflows/ci.yml` |
| Trava contra suite pulada em silencio | `tests/integration/conftest.py` |
| Diagramas em Mermaid | `docs/architecture/diagramas.md` |
| Indice e consolidacao dos ADRs | `docs/adr/README.md` |
| Demonstracao roteirizada | `scripts/demo.sh`, `make demo` |
| Relatorio consolidado e limitacoes atuais | `docs/testing/README.md` |
| Healthcheck do servico `api` | `docker-compose.yml` |
| Pipeline reproduzido a mao | `make ci` |

## 2. Arquivos criados e alterados

**Criados**

- `.github/workflows/ci.yml`
- `docs/architecture/diagramas.md`
- `docs/adr/README.md`
- `docs/testing/README.md`
- `docs/testing/phase-8-report.md`
- `scripts/demo.sh`

**Alterados**

- `tests/integration/conftest.py` — `NEXUS_TEST_REQUIRE_DYNAMO`
- `docker-compose.yml` — healthcheck do `api`
- `Makefile` — alvos `demo` e `ci`
- `docs/adr/ADR-005`, `ADR-008`, `ADR-009` — cabecalhos com o alcance alterado
- `README.md`, `ROADMAP.md`, `CHANGELOG.md`, `COSTS.md`, `NEXT-PHASES.md`

## 3. Como executar

```bash
./scripts/demo.sh --pausar
```

```bash
make ci
```

`make ci` roda os mesmos comandos do pipeline nesta maquina: `ruff`, `mypy --strict`,
a suite Python inteira com `NEXUS_TEST_REQUIRE_DYNAMO=1` e o `dashboard-check`.

## 4. O CI, e o que ele deliberadamente nao faz

Quatro jobs em paralelo: qualidade (ruff e mypy), testes Python, Control Center e
`terraform validate`.

Tres decisoes merecem registro.

**O DynamoDB sobe pelo mesmo `docker-compose.yml` do desenvolvimento**, nao por um
`services:` do GitHub Actions. O `services:` nao permite sobrescrever o comando do
container, e o DynamoDB Local sem `-sharedDb` abre uma base por combinacao de credencial
e regiao. O CI estaria medindo outro banco, e a divergencia so apareceria no dia em que
alguem confiasse nele.

**A suite de integracao roda, e nao pode pular em silencio.** `tests/integration/
conftest.py` chamava `pytest.skip` quando o banco nao respondia — comportamento certo na
maquina de quem desenvolve, armadilha no CI: o servico nao sobe, 43 testes pulam, o
pipeline fica verde, e nenhuma transacao, nenhum indice esparso e nenhuma escrita
condicional foi exercitada. `NEXUS_TEST_REQUIRE_DYNAMO=1` transforma a ausencia em
falha. **Um CI que passa sem testar e pior que CI nenhum**, porque produz confianca que
nao corresponde a nada.

**Nenhum job recebe credencial da AWS.** `terraform validate` roda com `-backend=false`,
que nao autentica e nao le estado. O job existe para impedir que o Terraform versionado
apodreca enquanto a infraestrutura esta destruida — nao para implantar. A consequencia
de custo esta em COSTS.md: nao existe caminho em que um push crie recurso.

### A primeira execucao, e o que ela prova

O repositorio foi publicado em 12/11/2026 como
[Buenno0/nexus-architecture](https://github.com/Buenno0/nexus-architecture), publico, e
**a primeira execucao passou nos quatro jobs** ([run 43149734246](https://github.com/Buenno0/nexus-architecture/actions/runs/43149734246)), em 1min31s.

Escrevi acima, antes de publicar, que nao podia afirmar nada sobre a ordem dos passos, o
cache das acoes ou o Docker do runner. Agora posso, e o resultado foi melhor do que eu
esperava: nada quebrou. Registro isso sem ajustar a previsao para parecer acertada — eu
contava com pelo menos uma falha, e nao houve.

O job de testes se decompoe assim:

| Passo | Duracao |
|---|---|
| Instalar dependencias (`uv sync --frozen`) | 3s |
| Subir o DynamoDB Local pelo compose | 12s |
| Suite completa | 72s |

**Os 12 segundos do banco sao a parte que importa.** A suite de integracao nao pode
passar sem ele: com `NEXUS_TEST_REQUIRE_DYNAMO=1`, a ausencia do DynamoDB faz o fixture
de sessao chamar `pytest.fail`, e o job cai. Job verde, portanto, significa que as
transacoes, o indice esparso e as escritas condicionais foram exercitadas de verdade no
runner — nao e inferencia sobre o que *provavelmente* aconteceu.

**O que continuo sem poder afirmar:** nao li o log do job. A API publica do GitHub nao
serve logs de execucao sem autenticacao, e `gh` nao esta autenticado nesta maquina.
Entao a contagem de 555 testes vem da suite local e do desenho da trava, nao de ter lido
`555 passed` na saida do runner. Quem quiser conferir abre o
[log do job](https://github.com/Buenno0/nexus-architecture/actions/runs/43149734246) no navegador.

## 5. Testes realizados

| O que | Resultado |
|---|---|
| `ruff check` / `ruff format --check` | limpos, 121 arquivos |
| `mypy --strict` | limpo, 42 arquivos |
| Suite Python com `NEXUS_TEST_REQUIRE_DYNAMO=1` | **555 passando**, cobertura 89% |
| Trava do CI com o banco fora do ar | **falha**, com a mensagem certa — nao pula |
| Trava ausente com o banco fora do ar | pula, como antes |
| `docker compose up -d --wait dynamodb` | saudavel em ~6s |
| `scripts/demo.sh` do zero | **11 atos, saida 0** |
| Control Center: `tsc`, `eslint`, `vitest` | limpos, 115 testes |
| YAML do workflow | valido, 4 jobs |
| `terraform fmt -check -recursive` | limpo |
| `terraform init -backend=false` + `validate` | configuracao valida, nada criado |

## 6. Os dois defeitos que a demonstracao encontrou

Escrever o roteiro nao encontrou nada. **Executa-lo encontrou dois.**

### `docker compose up --wait` mentia sobre estar pronto

Primeira execucao: `curl: (56) Recv failure: Connection reset by peer`, logo apos o
compose relatar o container como saudavel.

O servico `api` nao tinha healthcheck. Sem um, `--wait` considera pronto um container
que esta apenas **rodando** — e o uvicorn ainda nao abriu a porta. O `--wait` cumpria o
que promete; eu e que estava lendo nele uma garantia que ele nao da.

Isso nao e defeito do roteiro: qualquer automacao que suba a pilha e chame a API em
seguida levaria o mesmo reset, de forma intermitente e dificil de atribuir. Corrigido no
`docker-compose.yml`, mais um laco de espera no proprio roteiro, porque ele tambem roda
contra pilhas que alguem subiu de outro jeito.

### O roteiro narrava um alerta que nunca acendeu

Segunda execucao: saida 0, onze atos, tudo verde. E, dentro, isto:

```
ato  7:  "dead": 0,  "pending": 10
ato  8:  "O alerta acende sozinho"   ->  "alerts": []
ato 10:  "O alerta apaga"            ->  "alerts": []
```

O laco de injecao de falha fazia tres passadas com `sleep 2`. Mas o intervalo entre
entregas e **backoff exponencial**: a mensagem fica invisivel, um `drain` nesse meio
tempo nao recebe nada e termina imediatamente, e a terceira entrega so ficaria visivel
depois de ~4 s. As mensagens voltavam para `pending` e a DLQ nunca enchia.

O defeito grave nao e a espera curta. **E o roteiro ter seguido em frente narrando o
contrario do que mostrava na tela.** Dois atos afirmavam uma coisa e exibiam, logo
abaixo, a evidencia de que ela nao tinha acontecido — exatamente o que a secao 7 do
projeto proibe: apresentar como real algo que nao e.

Corrigido em duas partes. O laco passou a **observar o estado** em vez de contar o
tempo, repetindo ate a DLQ receber ou desistir com erro apos 12 passadas. E o roteiro
ganhou `exige()`: antes de narrar, ele confere.

```
ato  7:  "dead": 10
ato  8:  dlq_not_empty  (severity: error)
ato 10:  "alerts": []
```

A licao e a mesma da Fase 7, noutro disfarce: eu escrevi o que esperava ver e so
descobri que estava errado porque executei. Da primeira vez o erro foi tirar conclusao
de uma corrida; aqui foi afirmar um resultado sem conferir o estado que o sustentava.

## 7. Consolidacao dos ADRs

Nenhum ADR foi revogado. Tres tiveram o alcance alterado e agora dizem isso no proprio
cabecalho:

| ADR | Alteracao |
|---|---|
| 005 | Emendada pela 007. O marcador que garante idempotencia tambem congelava o acervo numa versao antiga do processador |
| 009 | Parcialmente superada pela 010. O principio permanece; a janela deslizante deixou de viver na aba |
| 008 | Implantada na AWS, verificada e **destruida**. A decisao vale; a infraestrutura nao existe |

O indice registra tambem o que **nao** virou ADR e por que: Mermaid, Locust e GitHub
Actions sao reversiveis num commit. O proprio documento diz quando isso mudaria — se o
CI passar a precisar de credenciais da AWS, a decisao deixa de ser reversivel sem
consequencia e vira ADR.

## 8. Limitacoes conhecidas

- **O log do CI nao foi lido daqui.** A API publica nao serve logs sem autenticacao;
  o resultado por job e por passo veio da API, a contagem de testes veio da suite local.
- **`docs.nexus.mateus-bueno.dev` nao existe.** Exige DNS e hospedagem; fora de escopo
  por decisao. A documentacao e Markdown no repositorio, renderizado pelo GitHub.
- **A demonstracao nao e gravada.** Nao ha video nem GIF. O roteiro e executavel e
  falha quando algo regride, o que um video nunca faz — mas exige a pilha local.
- **A demonstracao exige Docker e o ambiente Python.** Nao ha caminho sem instalar nada.
- **O roteiro nao cobre o Control Center.** Ele aponta para `make dashboard`; a
  verificacao da interface continua manual, como na Fase 4.
- **A consolidacao de limitacoes e manual.** Nada impede que um relatorio futuro liste
  uma limitacao e `docs/testing/README.md` nao seja atualizado.

## 9. Proximos passos

1. **Observar o CI ao longo de alguns pushes.** Uma execucao verde prova que o
   pipeline funciona hoje; nao prova que ele e estavel. Testes de integracao contra um
   banco em container sao candidatos classicos a intermitencia.
2. **Reavaliar o custo da trilha.** A Fase 7 mediu 4 ms, 25% do caminho de ingestao, e
   `NEXUS_TRAIL_ENABLED` existe. Manter ligada e defensavel; a decisao e do autor, e
   agora tem numero e chave.
3. **Medir na AWS** quando houver outra razao para subir a infraestrutura: cold start,
   latencia de rede real, efeito do pool de conexoes. Exige aumento da cota de
   concorrencia antes.
4. **Playwright no Control Center**, se a verificacao manual da interface comecar a
   custar caro.
