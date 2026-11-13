# Fase 9 — Demonstracao publica

Data: 2026-11-12
Endereco: **https://nexus.mateus-bueno.dev**

A fase tem uma particularidade: **tudo o que ela encontrou de defeito ja existia.** O
codigo novo — rota de semeadura, tetos, login automatico — funcionou de primeira. O que
quebrou foi infraestrutura escrita nas Fases 3 e 4 que nunca tinha sido exercitada pelo
caminho real.

## 1. O que foi implementado

| Entrega | Onde |
|---|---|
| `POST /v1/demo/seed`, geracao no servidor | `src/nexus/ingestion/api.py` |
| Gerador sintetico sem Faker | `src/nexus/demo/synthetic.py` |
| Reserva de cota atomica | `src/nexus/persistence/dynamo.py` |
| Ingestao livre fechada em duas camadas | `api.py` + `infra/terraform/apigateway.tf` |
| Login automatico do convidado | `control-center/src/auth/provider.tsx` |
| Usuario convidado, tetos por variavel | `infra/terraform/` |
| Runbook | `docs/runbook-demo.md` |

## 2. Como executar

```bash
NEXUS_DEMO_MODE=true docker compose up -d --wait
```

Procedimento completo, incluindo Vercel e os dois applies do CORS, em
[runbook-demo.md](../runbook-demo.md).

## 3. Testes realizados

| O que | Resultado |
|---|---|
| Suite Python | **576 passando**, 21 novos |
| Control Center | **118 passando**, 3 novos |
| ruff, mypy, tsc, eslint, terraform fmt/validate | limpos |
| Reserva de cota concorrente contra DynamoDB real | 20 reservas de 10 sob teto de 50 → **exatamente 5 vencedoras**, totais `[10,20,30,40,50]` |
| Roteamento na AWS, sem credencial | ingestao livre `404`, demais `401`, `/health` `200` |
| Tetos na AWS | 150+150 sob teto 300 passa; proxima recusa `429`; `count:900` recusa |
| Pipeline na AWS | 300 semeados, 231 processados, fila e DLQ zeradas |
| Painel no ar | 231 analisados, 100 correspondencias, 45 entidades, 10 revisoes |

## 4. Os tres defeitos que o deploy revelou

Nenhum foi introduzido nesta fase.

**`USER_PASSWORD_AUTH` nao estava habilitado no client do Cognito.** O painel autentica
com esse flow; o login falharia. Latente desde a Fase 4, cujo relatorio registrava que
o modo Cognito tinha teste de componente e **nunca fora exercitado contra a AWS**. Era
exatamente isso que a lacuna escondia.

**`/v1/observability/*` nao existia no API Gateway.** O mapa de rotas e da Fase 3; a
Fase 6 criou as rotas na aplicacao com a infraestrutura ja destruida. Os testes de
integracao batem no FastAPI direto, e `terraform validate` confere sintaxe, nao
cobertura de rotas.

**`ANY` no `route_key` quebra o preflight.** `ANY /v1/ops/{proxy+}` casa tambem com
`OPTIONS`, entao o preflight caia no authorizer JWT — e navegador **nunca** envia
`Authorization` num preflight. `401`, preflight reprovado, requisicao real nem sai.
Valia para `/v1/ops/*`, `/v1/resolution/*` e a rota de observabilidade. Com `GET` e
`POST` explicitos, `OPTIONS` nao casa com rota nenhuma e o gateway responde `204`.

**Os tres apareciam no console como erro de CORS**, com a configuracao de CORS correta
o tempo todo. O sintoma apontava para o lugar errado. A verificacao que distingue os
casos esta no runbook: preflight `401` e rota `ANY`; real `404` e rota ausente.

### Dois meus

O painel consultava a API **antes de existir token**: `useHealth` e `useAlerts` sao
chamados no `App` antes da barreira de autenticacao, e hooks do React rodam
incondicionalmente. Com polling de 30s, a primeira visita podia ficar meio minuto com
o painel vazio.

E apontei o CORS para `nexus-architecture.vercel.app`, que **e de outra pessoa** —
subdominios `*.vercel.app` sao globais e o nome ja estava tomado. Confundi "parece
certo" com "e certo": titulo parecido, app Vite, HTTP 200. Nao houve exposicao, porque
a API exige JWT em tudo menos `/health` e aquele site nao tinha token. Mas e o mesmo
padrao que a secao 6 da Fase 7 documenta — concluir sem confirmar.

## 5. Cold start

Item que a Fase 7 registrou como impossivel sem infraestrutura:

| Funcao | Init | Memoria usada |
|---|---|---|
| `api` | 1.416 ms | 129 MB de 512 |
| `dispatcher` | 732 ms | 108 MB |
| `worker` | 573 ms | 112 MB |

**n=1 por funcao.** Pela licao da Fase 7, isso e observacao, nao medicao. Repetir
exigiria forcar containers novos alterando a configuracao fora do Terraform, criando
divergencia de estado.

As tres usam menos de 130 MB dos 512 alocados. Reduzir cortaria custo, mas na Lambda
memoria e CPU andam juntas — cortaria desempenho tambem. Fica como pergunta aberta.

## 6. Limitacoes conhecidas

- **O custo real ainda nao foi medido.** O Cost Explorer leva ate 24h, e a tag de
  alocacao so vale para uso posterior a ativacao. Precisa ser consultado depois.
- **A infraestrutura agora custa.** Pouco, mas deixou de ser zero, e permanece custando
  enquanto estiver no ar.
- **O dominio e `nexus-architecture-buenno.vercel.app`**, nao um nome proprio. Um
  dominio proprio custaria US$ 0,50/mes de hosted zone.
- **Cota de 5.000 registros nao se renova.** Atingida, a semeadura recusa ate alguem
  reiniciar o acervo. Nao ha rotina de limpeza.
- **Sem teste ponta a ponta automatizado do painel contra a AWS.** A verificacao desta
  fase foi manual, pelo navegador — e foi ela que achou os tres defeitos.
- **A cota e consumida pela intencao de gerar**, nao pelo resultado: registros
  deduplicados tambem contam.

## 6b. A rede de seguranca, observada

Entre duas verificacoes a fila ficou com 80 mensagens aguardando, porque alguem gerou
registros pelo painel e ninguem invocou o worker. Na verificacao seguinte o acervo
tinha passado de 231 para 311 registros analisados, com a fila zerada.

Ninguem drenou: foi o EventBridge Scheduler, a cada 15 minutos. E a rede de seguranca
do [ADR-003](../adr/ADR-003-transactional-outbox.md) funcionando em producao — a
garantia de retentativa da Fase 2 so vale se alguem consumir de novo, e esse "alguem"
precisa existir quando ninguem esta olhando o painel.

Nao foi um teste planejado. Foi o sistema fazendo o que esta escrito que faz, e o
numero no painel mostrando.

## 7. Proximos passos

1. **Consultar o custo real** depois de 24h e registrar em COSTS.md.
2. **Decidir quanto tempo a demonstracao fica no ar.** Destruir e `terraform destroy`,
   com verificacao em dez categorias ja exercitada na Fase 3.
3. **Teste ponta a ponta do painel no CI**, que teria pego os tres defeitos acima.
4. **Rever a memoria das Lambdas**, se custo passar a importar.
