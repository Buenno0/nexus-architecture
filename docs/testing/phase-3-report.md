# Relatorio — Fase 3 (Cloud Infrastructure)

Data: 2026-11-07 · Terraform 1.17.1 · moto 5.2.5 · Python 3.13.18

## Resumo

| Metrica | Fase 5 | Fase 3 |
|---|---|---|
| Testes | 402 | **486** |
| Falhas | 0 | 0 |
| Cobertura global | 90% | **89%** |
| Ruff / mypy strict | limpo | limpo |
| `terraform validate` | — | **Success** |
| Recursos AWS criados | 0 | 40, implantados em 07/11 e **destruidos em 09/11** |
| **Custo real medido** | — | **US$ 0,0001** |

## A entrega

Construido e, apos autorizacao explicita, **implantado em 07/11/2026** na conta
541099637415. 48 recursos, custo estimado de ~US$ 0,10/mes.

A hosted zone do Route 53 — unico custo fixo do projeto — **nao foi criada**.

### Verificacao na AWS real

| Verificacao | Resultado |
|---|---|
| `GET /health` | `200`, `persistence: ok`, `queue: enabled` |
| Rota protegida sem token | `401` |
| Ingestao sem token | `401` |
| `/v1/ops/dispatch` sem token | `401` |
| Rota protegida com token JWT | `200` |
| Ingestao com token | `202`, `outbox_pending: 0` (publicacao inline funcionou) |
| Consumo pelo worker | mensagens processadas, fila drenada |
| **Resolucao de identidade** | **duas variantes agrupadas na mesma entidade** |
| Cold start observado | ~2,2s (primeira invocacao) |
| Invocacao quente | ~0,1s

## A bateria de contrato compartilhada

A peca mais valiosa desta fase. A mesma verificacao roda contra `SqliteQueue` e
`SqsQueue` — 22 cenarios x 2 implementacoes = **44 testes**.

Duas implementacoes do mesmo contrato que divergem em comportamento sao uma armadilha:
o codigo passa local e falha na nuvem, ou funciona nos dois lugares de formas
diferentes. O defeito aparece em producao, onde custa caro.

Diferencas legitimas ficam isoladas em testes especificos, nunca forcadas a coincidir:

| Comportamento | SQLite | SQS |
|---|---|---|
| `publish` repetido | `False` — deduplica | `True` — nao deduplica |
| Quem decide a DLQ | `fail`, contando entregas | `redrive_policy` |
| Ordem de entrega | Por `visible_at` | Sem garantia |
| Contadores | Exatos | `Approximate*` |

## Verificacoes executadas

| Verificacao | Resultado |
|---|---|
| Suite completa | 486 passando |
| Contrato de fila, duas implementacoes | 44 passando |
| Adaptador SQS com `moto` | 24 passando |
| Handlers Lambda | 16 passando |
| `terraform fmt -check` | limpo |
| `terraform validate` | Success |
| Curingas abertos em IAM | **nenhum** |
| Pacote Lambda | 6,1 MB compactados, 22 MB descompactados |
| Binarios do pacote | ELF aarch64 Linux (compilacao cruzada correta) |
| `boto3` no pacote | removido (runtime ja fornece) |

## Defeitos encontrados e corrigidos

1. **Justificativa errada no ADR-003.** O event source mapping foi rejeitado por
   "custo com fila vazia". O calculo desmente: 1 a 5 pollers com long poll de 20s
   geram 130 mil a 650 mil requisicoes/mes, dentro da franquia permanente de 1 milhao
   do SQS. A decisao se mantem — ele processa sozinho, desfazendo a execucao sob
   demanda — mas a razao registrada estava errada e levaria a conclusoes erradas em
   outros contextos.

2. **COSTS.md subestimava o DynamoDB.** Dizia "~US$ 0" para On-Demand. A franquia cobre
   25 GB e 25 WCU/RCU **provisionados**, nao requisicoes On-Demand. Real: ~US$ 0,15 por
   10 mil registros, **linear no volume** — 1 milhao de registros custa ~US$ 15, o que
   muda a conversa sobre testes de carga.

3. **Compilacao cruzada silenciosamente errada.** Sem `--only-binary :all:`, o `uv`
   compila localmente quando nao acha wheel e gera binarios macOS. A Lambda nao os
   carrega, e o erro so apareceria no primeiro deploy.

4. **Plataforma conservadora demais.** `aarch64-manylinux_2_17` resolvia `rapidfuzz`
   para 3.13.0 em vez de 3.14.6. O runtime roda sobre Amazon Linux 2023 (glibc 2.34);
   o alvo correto e `aarch64-unknown-linux-gnu`.

5. **Servidor Uvicorn no pacote Lambda.** `uvloop` sozinho pesava 16 MB, e a Lambda nao
   usa nenhum deles — o Mangum fala ASGI direto com o FastAPI. Pacote caiu de 11 MB
   para 6,1 MB.

6. **`StartMessageMoveTask` nao verificavel.** O `moto` nao o implementa. Trocado por
   redrive manual, que tem duas vantagens: devolve a **contagem exata** (igual a fila
   local) e roda inteiro nos testes. Em volume alto a API nativa seria preferivel.

## O que o deploy real revelou

Escrevi antes que "`moto` simula a API, nao o servico" e que diferencas apareceriam no
primeiro deploy. **Apareceram cinco**, nenhuma detectavel localmente:

### 1. A franquia do DynamoDB provisionado e por conta, nao por recurso

Recomendei PROVISIONED como alternativa de "custo zero". A franquia de 25 RCU/WCU vale
**por conta, somando tabela e todos os indices**. Com 4 GSIs sao 5 componentes;
provisionar 25 em cada daria 125/125, ou **US$ 56,94/mes** — 712x o custo do On-Demand.

Pego ao inspecionar o plano do Terraform, **antes de aplicar**. A variavel virou um
orcamento total, dividido automaticamente.

### 2. O preco On-Demand estava desatualizado

A API de precos da AWS informa **US$ 0,625 por milhao de WRU**, nao US$ 1,25. A
estimativa caiu de US$ 0,15 para US$ 0,08 por 10.000 registros.

### 3. A cota de concorrencia impede reservar

A conta tem cota de **10 execucoes concorrentes no total**, e a AWS exige que sobrem 10
nao reservadas. Qualquer `reserved_concurrent_executions` e recusado.

A protecao nao desapareceu: a propria cota passa a ser o teto, e 10 simultaneas e mais
apertado que qualquer reserva que definiriamos. A variavel aceita `-1` e explica isso.

### 4. Remover `*.dist-info` quebrou a aplicacao em producao

O script apagava todos os metadados para encolher o pacote. O `email-validator`, que o
Pydantic usa em `EmailStr`, le a propria versao via `importlib.metadata`:

```
Runtime.ImportModuleError: Unable to import module 'nexus.handlers.api':
No package metadata was found for email-validator
```

A Lambda falhava **no import**, antes de atender a primeira requisicao. Corrigido para
remover apenas os metadados dos pacotes efetivamente removidos, com uma verificacao no
build que falha se faltar metadado de pacote conhecido por precisar dele.

### 5. `DescribeTable` faltava na policy

`GET /health` chama `ping()`, que faz `DescribeTable`. A acao nao estava na policy: a
API subia, respondia `200` e reportava `persistence: unavailable`. **Um health check
mentindo sobre o proprio estado.**

Faltava tambem `DeleteItem` na funcao `api` — confirmar uma revisao funde entidades, e
a fusao apaga itens.

`moto` nao avalia politicas IAM, entao nenhum teste local pegaria isso.

### 6. Container quente mantem credenciais em cache

Apos corrigir a policy, o simulador do IAM respondia `allowed` e a Lambda continuava
recebendo `AccessDenied` — por mais de tres minutos. Containers quentes carregam
credenciais em cache.

Resolvido com uma variavel `NEXUS_BUILD` derivada do hash do pacote: muda a cada build
e força containers novos no deploy.

### 7. O budget nunca teria disparado

O `cost_filter` do AWS Budgets apontava para a tag `Project=nexus-architecture`. **Tags
de alocacao de custo precisam ser ativadas explicitamente** no Billing; nenhuma estava
na conta.

O filtro nao casava com nada, entao o budget ficaria silencioso diante de qualquer
valor — uma protecao de custo que existia so no papel.

Descoberto ao medir o custo real na destruicao: a consulta filtrada por tag devolvia
US$ 0,00, e o zero vinha do filtro vazio, nao da ausencia de gasto. **Quase reportei
esse zero como resultado.**

Corrigido com `aws_ce_cost_allocation_tag`, documentando que a ativacao leva ate 24h e
nao reclassifica gasto anterior — razao a mais para manter o alerta por previsao, que
nao depende de historico acumulado.

### 8. `ReceiveMessage` devolve menos do que o pedido

Com 2 mensagens na fila e `MaxNumberOfMessages=10`, o SQS devolveu 1. E comportamento
documentado — ele amostra um subconjunto dos servidores. A fila SQLite devolve sempre
tudo que esta visivel.

Nao e defeito: o worker e chamado repetidamente ate a fila esvaziar. Mas quem
dimensionar lote contando com "pedi 10, recebo 10" vai errar.

## O que ainda **nao** foi verificado

- Comportamento sob carga: latencia, throttling, cold start no P99 — Fase 7.
- `redrive_policy` movendo para a DLQ apos `maxReceiveCount` no SQS real.
- `redrive_policy` movendo para a DLQ apos `maxReceiveCount` no SQS real.
- Nenhum registro DNS foi criado; a API responde pelo dominio da AWS.

## Custos

Estimativa no volume previsto (~10.000 registros/mes): **~US$ 0,70/mes**.

| Item | Custo |
|---|---|
| Route 53 hosted zone | US$ 0,50 (**unico fixo**) |
| DynamoDB On-Demand | ~US$ 0,20 (variavel, linear) |
| Lambda, SQS, API Gateway, Cognito, Logs | US$ 0 (franquia) |

Com `dynamodb_billing_mode = "PROVISIONED"` o custo variavel zera, em troca de
estrangular acima de 25 escritas/segundo. Detalhamento em [COSTS.md](../../COSTS.md).

## Limitacoes conhecidas

- **O primeiro deploy usara AdministratorAccess**, mais do que o necessario. O correto
  e uma role dedicada aos servicos do `iam.tf`; registrado como divida no runbook.
- **Dois mecanismos de DLQ** para manter coerentes: `fail` na fila local,
  `redrive_policy` no SQS. A bateria de contrato cobre o resultado observavel, nao a
  implementacao.
- **Estado do Terraform e local.** Para trabalho em equipe, backend remoto com lock.
- **Nenhum registro DNS gerenciado.** A alteracao e sua, com ACM validado antes.


## Custo real e destruicao

A infraestrutura ficou no ar de 07 a 09/11/2026 e foi destruida a pedido.

| Servico | Custo nos 3 dias |
|---|---|
| Amazon DynamoDB | **US$ 0,0001** |
| API Gateway, Lambda, SQS, Cognito, Scheduler, Logs | US$ 0,0000 (franquia) |

Destruicao verificada em dez categorias — DynamoDB, Lambda, SQS, API Gateway, Cognito,
Scheduler, IAM, Budgets, CloudWatch Logs e Route 53 — todas sem recurso remanescente, e
estado do Terraform zerado.

A estimativa de ~US$ 0,10/mes continua valida para o volume que ela assume (10.000
registros/mes); a demonstracao usou um volume muito menor.
