# Runbook — Deploy na AWS

Procedimento para implantar o Nexus Architecture.

**Executado em 07/11/2026** na conta 541099637415, apos autorizacao explicita. 48
recursos, custo estimado de ~US$ 0,10/mes. A hosted zone do Route 53 — unico custo fixo
— nao foi criada.

> **Antes de comecar, leia [COSTS.md](../COSTS.md).** O custo estimado e ~US$ 0,70/mes,
> sendo US$ 0,50 fixos da hosted zone do Route 53. O restante acompanha o uso e cresce
> linearmente com o volume.

---

## Pre-requisitos

| Item | Verificacao |
|---|---|
| Terraform >= 1.9 | `terraform version` |
| AWS CLI v2 | `aws --version` |
| uv | `uv --version` |
| Conta AWS com permissao | ver abaixo |

### Sobre as credenciais

O perfil `ozymandias` (IAM Roles Anywhere) **nao tem permissao** para DynamoDB, Lambda,
SQS, API Gateway, Budgets nem Route 53. Confirmado em 07/11/2026.

O perfil `ozymandias-admin` tem AdministratorAccess via SSO, com token expirado:

```bash
aws sso login --profile ozymandias-admin
```

```bash
aws sts get-caller-identity --profile ozymandias-admin
```

> **Recomendacao.** AdministratorAccess e mais do que o deploy precisa. O ideal e criar
> uma role dedicada ao projeto, com permissao para os servicos listados no `iam.tf` e
> mais nada. Fazer o primeiro deploy com admin e aceitavel; manter assim nao e.

---

## 1. Empacotar a aplicacao

```bash
make lambda
```

Compila para **Linux arm64** a partir do macOS. Esperado: ~6 MB compactados, ~22 MB
descompactados (limite da Lambda: 250 MB).

Se o pacote vier muito maior, provavelmente o `--only-binary :all:` falhou e wheels do
macOS entraram — que a Lambda nao carrega.

---

## 2. Configurar as variaveis

```bash
cp infra/terraform/terraform.tfvars.example infra/terraform/terraform.tfvars
```

Obrigatorio preencher `budget_notification_email`. Sem ele os alertas de orcamento nao
chegam a lugar nenhum.

Decisao de custo neste ponto:

| `dynamodb_billing_mode` | Custo | Limite |
|---|---|---|
| `PROVISIONED` | **US$ 0,00** (franquia de 25 WCU/RCU) | Estrangula acima de 25 escritas/s |
| `PAY_PER_REQUEST` | ~US$ 0,15 por 10 mil registros | Sem limite pratico |

Para demonstrar, `PROVISIONED` basta e nao custa nada. Troque antes dos testes de carga.

---

## 3. Revisar o que sera criado

```bash
cd infra/terraform && terraform init
```

```bash
terraform plan -out=tfplan
```

**Leia o plano antes de aplicar.** Confira:

- [ ] Nenhum recurso fora da lista abaixo
- [ ] `aws_budgets_budget` presente
- [ ] `reserved_concurrent_executions` em todas as Lambdas
- [ ] `retention_in_days` nos log groups
- [ ] Nenhum `aws_lambda_event_source_mapping`

Recursos esperados: 1 tabela DynamoDB, 2 filas SQS, 3 Lambdas, 3 roles + 6 policies,
1 HTTP API com stage e rotas, 1 authorizer, 1 user pool + client, 2 schedules
(se `enable_safety_net`), 1 budget, 4 log groups.

---

## 4. Aplicar

```bash
terraform apply tfplan
```

Anote as saidas: `api_endpoint`, `cognito_user_pool_id`, `cognito_client_id`.

---

## 5. Criar o primeiro operador

Auto-cadastro esta desligado de proposito.

```bash
aws cognito-idp admin-create-user --user-pool-id "$(terraform output -raw cognito_user_pool_id)" --username voce@exemplo.com --user-attributes Name=email,Value=voce@exemplo.com Name=email_verified,Value=true --profile ozymandias-admin
```

---

## 6. Verificar

```bash
curl -s "$(terraform output -raw api_endpoint)/health"
```

Esperado: `{"status":"ok","environment":"aws",...}`.

```bash
curl -s -o /dev/null -w '%{http_code}\n' "$(terraform output -raw api_endpoint)/v1/records?limit=1"
```

**Esperado: `401`.** Um `200` aqui significa que o authorizer nao esta protegendo a
rota — pare e investigue antes de seguir.

Com um token valido no header `Authorization`, as rotas de ingestao e operacao
respondem como no ambiente local.

---

## 7. Dominio (opcional, custa US$ 0,50/mes)

A hosted zone do Route 53 e **o unico custo fixo garantido** do projeto. Ela continua
cobrando mesmo sem trafego, e sobrevive a um `terraform destroy` se tiver sido criada
fora do Terraform.

Os registros DNS **nao** sao gerenciados aqui: a alteracao e sua, com o certificado ACM
validado antes.

---

## 8. Destruir

```bash
cd infra/terraform && terraform destroy
```

Depois, confirme que nao sobrou nada cobrando:

```bash
aws ce get-cost-and-usage --time-period Start=$(date -v-7d +%Y-%m-%d),End=$(date +%Y-%m-%d) --granularity DAILY --metrics UnblendedCost --profile ozymandias-admin
```

O `terraform destroy` **nao remove**: a hosted zone criada manualmente, log groups de
Lambdas ja apagadas (expiram em 7 dias) e o historico do Cost Explorer.

---

## Solucao de problemas

Todos os casos abaixo foram encontrados no deploy real de 07/11/2026.

| Sintoma | Causa | Correcao |
|---|---|---|
| `InvalidParameterValueException: decreases account's UnreservedConcurrentExecution below 10` | Cota da conta e de 10 execucoes concorrentes; a AWS exige 10 nao reservadas | `lambda_reserved_concurrency = -1`. A cota da conta vira o teto |
| `Runtime.ImportModuleError: No package metadata was found for email-validator` | O build removia todos os `*.dist-info`; o Pydantic le a versao via `importlib.metadata` | Corrigido no `build_lambda.sh`, que agora verifica os metadados obrigatorios |
| `/health` responde `200` com `persistence: unavailable` | Falta `dynamodb:DescribeTable` na policy — `ping()` usa | Adicionado ao `iam.tf` |
| `AccessDenied` persiste apos corrigir a policy, com o simulador dizendo `allowed` | Container quente com credenciais em cache | `NEXUS_BUILD` derivado do hash do pacote força containers novos |
| `AccessDenied` em Query no GSI | Falta `${tabela}/index/*` — consultar indice exige permissao no ARN do indice | Ja no `iam.tf` |
| `process` devolve menos mensagens do que `max_messages` | `ReceiveMessage` do SQS amostra servidores e pode devolver menos | Normal. Chame ate `received: 0` |
| Fatura acima do esperado | Volume no DynamoDB — unico custo linear | Veja a tabela em COSTS.md |

---

## O que ainda nao foi verificado

O deploy de 07/11 validou saude, autenticacao, ingestao, consumo e resolucao de
identidade. Continuam sem verificacao:

- comportamento sob carga: latencia, throttling e cold start no P99 (Fase 7);
- `redrive_policy` movendo para a DLQ apos `maxReceiveCount` no SQS real;
- custo real — o Cost Explorer leva ate 24h para refletir o uso;
- dominio proprio: a API responde pelo endereco da AWS.

As diferencas entre `moto` e o servico real estao catalogadas em
[docs/testing/phase-3-report.md](testing/phase-3-report.md).
