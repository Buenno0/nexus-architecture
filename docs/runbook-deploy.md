# Runbook — Deploy na AWS

Procedimento para implantar o Nexus Architecture. **Nada aqui foi executado**: a Fase 3
entregou o codigo e a infraestrutura como codigo, e o deploy e um ato seu, com custo
conhecido.

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

| Sintoma | Causa provavel |
|---|---|
| `AccessDenied` em Query no DynamoDB | Falta `${tabela}/index/*` na policy — consultar GSI exige permissao no ARN do indice |
| `Unable to import module` na Lambda | Pacote com wheels do macOS; refaca `make lambda` |
| `401` em toda rota, inclusive com token | `audience` do authorizer diferente do client ID |
| Mensagens presas em voo | Worker caiu sem apagar; reaparecem apos o visibility timeout |
| Fatura acima do esperado | Verifique volume no DynamoDB — e o unico custo linear relevante |

---

## O que nao foi verificado

**Nada nesta fase rodou contra a AWS real.** `moto` simula a API do SQS, nao o servico:
nao exercita latencia, limites de taxa, consistencia eventual nem o comportamento real
do `redrive_policy`.

A primeira execucao de verdade e a do passo 6 — e e la que diferencas entre simulacao e
servico vao aparecer, se existirem.
