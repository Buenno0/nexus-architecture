# ADR-008 — Arquitetura serverless na AWS

- **Status:** Aceita — **implementada, validada na AWS e destruida**
- **Data:** 2026-11-07
- **Situacao em 2026-11-12:** nenhum recurso existe. A infraestrutura foi aplicada,
  verificada ponta a ponta e destruida na Fase 3; o Terraform permanece versionado em
  `infra/terraform/`. Custo acumulado do projeto: US$ 0,00. Ver
  [phase-3-report.md](../testing/phase-3-report.md).

## Contexto

As Fases 1, 2 e 5 rodam local com custo zero. Levar a plataforma para a AWS precisa
satisfazer tres restricoes do projeto ao mesmo tempo:

1. **Orcamento limitado.** Nada permanentemente ligado.
2. **Execucao sob demanda.** O operador aciona; a plataforma nao processa sozinha.
3. **Privilegio minimo.** Cada componente acessa apenas o que usa.

O trabalho de arquitetura ja estava feito: `QueueClient` e `RecordRepository` sao
abstratos desde a Fase 1, e `NEXUS_ENV` / `NEXUS_QUEUE_BACKEND` decidem as
implementacoes num unico ponto. Nenhuma linha de logica de negocio muda nesta fase.

## Decisao

### Construir tudo, implantar nada

A entrega e codigo e infraestrutura como codigo — **nenhum recurso AWS foi criado**.

Nao e cautela decorativa:

- o perfil ativo (IAM Roles Anywhere) nao tem permissao para nenhum dos servicos;
- o unico perfil capaz usa AdministratorAccess com token SSO expirado;
- a conta tem IAM Identity Center, sugerindo uso alem deste projeto.

O deploy e um ato do dono da conta, com custo conhecido. `docs/runbook-deploy.md`
descreve o procedimento, incluindo como destruir tudo.

### Componentes

```
Internet
   |
   v
API Gateway HTTP API  --- authorizer JWT (Cognito)
   |                      /health aberto; todo o resto exige token
   v
Lambda api (Mangum)  -->  DynamoDB single-table, 4 GSIs
   |                 -->  SQS (publicacao inline best-effort)
   |
   |   invocacao explicita: Control Center, CLI ou Scheduler
   v
Lambda dispatcher  -->  le o indice esparso, publica no SQS
Lambda worker      -->  consome SQS, resolve identidade, grava

EventBridge Scheduler (15 min) ---> dispatcher e worker  [rede de seguranca]
AWS Budgets  --->  alertas em US$ 5 e US$ 10, mais previsao
```

### Tres funcoes, nao uma

Uma funcao unica com roteamento interno precisaria da **uniao** de todas as permissoes.
Separadas, cada politica cobre exatamente o seu uso:

| Funcao | DynamoDB | SQS |
|---|---|---|
| api | Get, Put, Update, Query, TransactWrite | Send, Receive, Delete, ChangeVisibility, GetAttributes |
| dispatcher | Get, Update, Query | Send |
| worker | Get, Put, Update, Delete, Query, TransactWrite | Receive, Delete, ChangeVisibility, Send, GetAttributes |

Nenhum `*` em `Action` ou `Resource`. Os unicos curingas sao escopados: os indices da
propria tabela e o prefixo dos log groups do projeto.

> Detalhe que costuma passar: consultar um GSI exige permissao no ARN **do indice**,
> nao apenas no da tabela. Omitir `${tabela}/index/*` produz um `AccessDenied` que so
> aparece na primeira consulta.

### Sem event source mapping

O worker nao e acionado pelo SQS. A invocacao vem do Control Center, da CLI ou do
Scheduler.

**A justificativa anterior, de custo, estava errada** — ver a correcao no ADR-003. Com
fila ociosa, o polling de 1 a 5 pollers gera entre 130 mil e 650 mil requisicoes por
mes, dentro da franquia permanente de 1 milhao do SQS.

O motivo real e a restricao 2: a plataforma existe para demonstrar execucao sob
demanda. Entregar essa decisao ao SQS removeria justamente o que o Control Center tem
a mostrar.

### Rede de seguranca agendada

Acionamento puramente manual tem um furo: a retentativa da Fase 2 so acontece se
alguem consumir de novo. Uma mensagem que falha quando ninguem olha o dashboard fica
parada indefinidamente.

O EventBridge Scheduler invoca dispatcher e worker a cada 15 minutos. Continua sendo
invocacao explicita — apenas disparada pelo relogio em vez do operador. A variavel
`enable_safety_net` desliga, para demonstracoes estritamente sob demanda.

### Cognito em vez de segredo compartilhado

Uma SPA nao guarda segredo: qualquer chave embutida no JavaScript esta publica. Um
authorizer com segredo compartilhado so funcionaria com o dashboard rodando local.

Cognito com JWT resolve de verdade, e a franquia de 50.000 usuarios ativos cobre o
projeto com folga. Auto-cadastro desligado: operadores sao criados por voce.

`/health` fica aberto — um health check que exige token nao serve para monitoramento
externo, e nao revela nada alem de estar no ar.

### Empacotamento em zip, compilado para ARM64

Zip em vez de imagem de container: cold start menor e deploy mais simples. Lambda em
Graviton (arm64) custa ~20% menos por GB-segundo.

Duas armadilhas tratadas no script de build:

1. **Compilacao cruzada obrigatoria.** macOS arm64 produzindo para Linux arm64. Sem
   `--only-binary :all:`, o `uv` compila localmente quando nao acha wheel e gera
   binarios macOS que a Lambda nao carrega — erro que so aparece no primeiro deploy.
2. **Plataforma correta.** O runtime Python 3.13 roda sobre Amazon Linux 2023
   (glibc 2.34). O alvo `aarch64-manylinux_2_17` e conservador demais e resolve para
   versoes antigas de pacotes compilados.

O pacote remove `boto3`/`botocore` (fornecidos pelo runtime) e o servidor Uvicorn com
suas aceleracoes — o Mangum fala ASGI direto com o FastAPI. Resultado: **6,1 MB
compactados**, contra 11 MB sem essas remocoes.

## Diferencas entre a fila local e o SQS

Documentadas porque sao reais, e porque a bateria de contrato compartilhada as isola
de proposito em vez de forcar uma falsa equivalencia:

| Comportamento | SQLite (ADR-004) | SQS |
|---|---|---|
| `publish` de evento repetido | `False` — deduplica por `event_id` | `True` — fila padrao nao deduplica |
| Quem decide a DLQ | `fail`, contando entregas | O `redrive_policy`, pelo `maxReceiveCount` |
| O que `fail` faz | Reagenda ou move | So encurta a visibilidade |
| Ordem de entrega | Por `visible_at` | Sem garantia |
| Contadores | Exatos | `Approximate*` — sao estimativas |

A deduplicacao perdida nao enfraquece nada: a garantia de efeito unico sempre foi a
escrita condicional do marcador (ADR-005), nunca a fila.

**A regra do `maxReceiveCount` deixa de viver na aplicacao e passa a ser configuracao
de infraestrutura.** Tenta-la nos dois lugares faria as duas divergirem.

## Consequencias

**Positivas**
- Nenhuma linha de logica de negocio mudou; so entraram adaptadores.
- A mesma bateria de testes roda contra as duas filas e falha se divergirem.
- `terraform destroy` derruba tudo num comando — controle de custo, nao conveniencia.
- Custo estimado de ~US$ 0,70/mes, com alertas antes de surpresa.

**Negativas**
- **Nada foi validado contra a AWS real.** `moto` simula a API, nao o servico.
- Cold start afeta o P99 e precisa ser medido separadamente (Fase 7).
- Terraform adiciona uma ferramenta e um arquivo de estado para cuidar.
- Dois mecanismos de DLQ para manter coerentes entre os ambientes.

## Alternativas consideradas

| Alternativa | Motivo da rejeicao |
|---|---|
| ECS/Fargate | Container permanentemente ligado; custo fixo |
| EC2 | Idem, e com servidor para administrar |
| Event source mapping SQS -> Lambda | Processa sozinho; remove o controle manual (nao e custo) |
| Imagem de container na Lambda | Cold start maior sem necessidade: o pacote cabe em 6 MB |
| Lambda authorizer com segredo | Inviavel com SPA publica |
| AWS SAM ou CDK | Terraform e mais transferivel e destroi com mais previsibilidade |
| VPC privada | NAT Gateway custa ~US$ 32/mes parado; isolamento por IAM basta |
| Aplicar agora, nesta conta | AdministratorAccess numa conta com Identity Center, sem necessidade |
