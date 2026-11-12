# Relatorio da Fase 7 — Performance Engineering

- **Data:** 11/11/2026
- **Ambiente:** local (DynamoDB Local + API em container, Locust no host)
- **Custo:** US$ 0,00. Nenhum recurso AWS foi criado.

## 1. O que foi implementado

| Entrega | Onde |
|---|---|
| Arnes de carga com captura de estado | `tools/loadtest.py` |
| Campanha com isolamento entre corridas | `tools/campanha.py` |
| Comparacao derivada dos resultados | `tools/comparar.py` |
| Amostragem de CPU durante carga | `tools/cpu_durante_carga.py` |
| Sonda de latencia do armazenamento | `tools/sonda_dynamo.py` |
| Analise da particao quente | `tools/particao_quente.py` |
| Repeticoes controladas | `tools/repetir_workers.py`, `repetir_trilha.py`, `regime_linear.py` |
| Isolamento de cenario no Locust | `tests/load/locustfile.py` |
| Concorrencia contra o banco real | `tests/integration/test_concorrencia.py` |
| `trail_enabled` e pool configuravel | `shared/config.py`, `persistence/tables.py` |
| Tetos de CPU e `--workers` por servico | `docker-compose.yml` |
| Relatorio e metodologia | `docs/performance/` |

## 2. Como executar

```bash
make up
```

```bash
make campaign
```

```bash
make load NOME=exp USUARIOS=50 DURACAO=60s
```

`make campaign` **zera tabela e fila entre corridas**. Os dados sao sinteticos e
recriados pelo gerador, mas a operacao e destrutiva e esta marcada como tal.

## 3. Resultados

Tabelas completas em [docs/performance/README.md](../performance/README.md).

**Gargalo identificado:** o caminho de escrita da ingestao. Com cada caminho isolado,
`replay` entrega 571,5 req/s, `duplicata` 247,8 e `novo` 103,8 — 5,5x de diferenca na
mesma pilha, mesmo processo, mesma concorrencia.

**Decomposicao do caminho de escrita** (regime nao saturado): nucleo 9 ms (56%),
trilha da Fase 6 4 ms (25%), publicacao na fila 4 ms (25%).

**Joelho da curva** entre 10 e 50 usuarios simultaneos.

**Particao quente do `gsi_recency`:** satura a 1.000 registros/s; medimos 104. A
mitigacao por sharding continua desnecessaria, agora por numero — com a ressalva de que
a folga real e de 32% no tamanho do item, nao os 900% que a distancia entre 104 e 1.000
sugere.

## 4. Testes

| Suite | Resultado |
|---|---|
| Python | **555 testes**, incluindo 4 novos de concorrencia contra o DynamoDB real |
| `ruff`, `ruff format`, `mypy --strict` | limpos |
| Corridas de carga | 51 corridas registradas em `docs/performance/runs/` |

Os testes de concorrencia novos exercitam contra o banco real o que ja era coberto
contra o repositorio falso. A diferenca nao e cerimonial: a traducao de
`TransactionCanceledException` para conflito resolvido so existe no caminho real, e se
ela quebrar todas as requisicoes perdedoras viram erro 500 sem nenhum teste unitario
notar.

## 5. Defeitos encontrados e corrigidos

### 5.1 Rotas declaravam a configuracao injetada e a ignoravam

`/health` declarava `settings: SettingsDep` e sobrescrevia com `get_settings()` na linha
seguinte. `/metrics` fazia o mesmo com `environment`; `list_records` nem declarava a
dependencia. Invisivel porque o ambiente raramente difere entre a configuracao real e a
injetada — ate um teste precisar injetar uma diferente.

### 5.2 Override de dependencia passando classes

`tests/unit/test_cors.py` registrava `Settings`, `FakeRepository` e
`RecordingQueueClient` como overrides. O FastAPI inspeciona a assinatura do que recebe:
`Settings` virou parametros de consulta e os campos com `default_factory` chegaram como
o sentinela interno do Pydantic. **Mesmo defeito que a Fase 4 corrigiu em outro
arquivo**, dormente ate `/health` passar a depender de settings.

### 5.3 Contagem de processos uvicorn sempre errada

Com `--workers N`, o uvicorn cria os trabalhadores por `multiprocessing` e a linha de
comando deles nao menciona `uvicorn`: e `spawn_main`. Contar por "uvicorn" devolvia 1
em qualquer configuracao — plausivel e sempre errado, o pior tipo de numero.

### 5.4 Contadores de `/metrics` sao inuteis com multiplos processos

Com 4 workers, o delta de `ingestion_accepted_total` caiu de 5.355 para 293 enquanto a
fila mostrava 5.071 mensagens — trabalho equivalente. `/metrics` le os contadores **do
processo que atendeu a requisicao**, e com 4 processos enxerga um quarto da verdade.

O rotulo `processo` do ADR-009 sempre disse isso. Esta e a primeira vez que havia dado
mostrando o estrago.

### 5.5 Bug no proprio teste de concorrencia

Passei a string do JSON onde o repositorio espera o enum `RecordType`. As tres
asserções anteriores ja tinham passado, entao a garantia se sustentou — o teste e que
estava errado.

## 6. Erros de medicao cometidos nesta fase

Estes nao sao defeitos do codigo. Sao erros meus de metodo, e sao o conteudo principal
da fase.

### 6.1 Tratei uma corrida unica como conclusao — duas vezes, com sinais opostos

A campanha mediu 163 req/s com 1 processo contra 150 com 4, e eu relatei que mais
processos pioravam o sistema. A medicao seguinte, instrumentada, deu 170 contra 193 — a
direcao oposta. Repetindo tres vezes com estado zerado: **90,4 contra 87,8, diferenca de
3% dentro de uma dispersao de 10% a 26%.** As duas conclusoes anteriores eram ruido
lido como sinal.

### 6.2 Alternei configuracoes achando que isso cancelaria a deriva

Rodei w1, w4, w1, w4, w1, w4 sem reiniciar, imaginando que a alternancia neutralizaria
o crescimento do acervo. Nao neutraliza: a tabela cresce monotonicamente ao longo das
seis corridas, entao a configuracao que roda em segundo lugar enfrenta sempre um acervo
maior. O resultado tinha queda monotonica dentro de cada serie — 210, 153, 137 — que eu
quase li como diferenca entre configuracoes.

### 6.3 "Isolei" um cenario sem isolar nada

Fiz as tarefas desabilitadas retornarem cedo. O Locust continua aplicando o tempo de
espera depois delas, entao o "teto do replay" que medi — 117,6 req/s — era exatamente
2/11 da taxa de turnos: a aritmetica dos pesos. Com o isolamento correto, removendo a
tarefa da lista, o teto real e **571,5 req/s**, quase cinco vezes maior.

### 6.4 Medi o custo de um trabalho sob saturacao

As primeiras medicoes do custo da trilha deram 147 contra 128 req/s e P50 dobrando, com
200 usuarios. Sob saturacao quase todo o tempo de resposta e espera em fila, e fila
amplifica qualquer perturbacao do ambiente: o CV ficou entre 30% e 40% e a diferenca nao
era conclusiva. No regime nao saturado o CV caiu para **0% a 1%** e o custo real
apareceu limpo: **4 ms**, nao "o dobro da latencia".

**O padrao comum aos quatro:** eu olhei um numero, formei uma explicacao plausivel e a
publiquei. A explicacao plausivel foi errada todas as vezes. O unico antidoto que
funcionou foi repetir a medicao e olhar a dispersao antes de olhar a diferenca.

## 7. Limitacoes conhecidas

- **Nada foi medido na AWS.** A infraestrutura esta destruida. E a conta tem cota de 10
  execucoes concorrentes: qualquer vazao medida la seria a cota, nao a arquitetura.
- **Cold start nao foi quantificado** — depende do item acima.
  *(Atualizacao de 12/11/2026: medido na Fase 9, quando a infraestrutura voltou ao
  ar. `api` 1.416 ms de init, `dispatcher` 732 ms, `worker` 573 ms. **Uma observacao
  por funcao, n=1** — pela licao da secao 6 abaixo, isso nao e uma medicao.)*
- **Os eixos de volume e concorrencia tem uma corrida por configuracao.** Os efeitos sao
  grandes o bastante para a tendencia ser confiavel; a magnitude, menos.
- **O ambiente e um laptop com outros processos.** Os tetos de CPU controlam a disputa
  entre containers, nao com o resto do sistema.
- **DynamoDB Local nao e o DynamoDB.** Nao estrangula, nao tem particao quente, nao
  cobra. A analise da particao quente e aritmetica sobre o modelo de dados real, nao
  observacao do comportamento.
- **Nao houve profiling do processo.** A decomposicao e por diferenca entre
  configuracoes, que atribui custo a componentes mas nao a funcoes.
- **`NEXUS_DYNAMO_MAX_POOL_CONNECTIONS` nao foi validado onde deveria importar.**
  Localmente nao teve efeito; o cenario em que ele importaria — rede real — e o que nao
  foi medido.

## 8. Proximos passos

1. **Fase 8 — Finalizacao.** CI/CD, diagramas, consolidacao dos ADRs, README final.
2. **Medir na AWS** quando houver outra razao para subir a infraestrutura: cold start,
   latencia de rede real e o efeito do pool de conexoes.
3. **Pedir aumento de cota de concorrencia** antes de qualquer teste de vazao na nuvem.
4. **Profiling do caminho de escrita**, se os 9 ms do nucleo virarem incomodo.
