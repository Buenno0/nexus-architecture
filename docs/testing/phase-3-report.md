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
| Recursos AWS criados | 0 | **0** |
| **Custo da fase** | US$ 0,00 | **US$ 0,00** |

## A entrega

**Construido, nao implantado.** O deploy e um ato do dono da conta, com custo
conhecido, descrito em [docs/runbook-deploy.md](../runbook-deploy.md).

A decisao nao foi so cautela: o perfil ativo nao tem permissao para nenhum dos
servicos, e o unico perfil capaz usa AdministratorAccess com token SSO expirado desde
08/10/2026.

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

## O que **nao** foi verificado

**Nada rodou contra a AWS real.** Isso nao e detalhe:

- `moto` simula a API do SQS, nao o servico — nao exercita latencia, limites de taxa,
  consistencia eventual nem o comportamento real do `redrive_policy`.
- Nenhuma politica IAM foi testada contra o avaliador real. Estao escopadas por
  inspecao, nao por execucao.
- O pacote Lambda nunca foi carregado por um runtime Lambda.
- `terraform plan` exige credenciais validas; so `terraform validate` rodou.
- Cold start nao foi medido — escopo da Fase 7.

A primeira execucao de verdade e o passo 6 do runbook, e e la que diferencas entre
simulacao e servico vao aparecer, se existirem.

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
