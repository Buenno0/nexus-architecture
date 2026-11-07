# Custos — Nexus Architecture

**Regra inegociavel:** nenhum recurso AWS e criado sem apresentacao previa de custo
estimado e autorizacao explicita.

## Situacao atual

**US$ 0,00.** Nenhum recurso de nuvem provisionado. Tudo roda localmente em Docker.

Fases 1 e 2 permanecem integralmente locais.

---

## Estimativa para Fase 3

| Servico | Franquia gratuita | Uso previsto | Custo estimado |
|---|---|---|---|
| Lambda | 1M req + 400k GB-s / mes (permanente) | ~10k req | US$ 0 |
| API Gateway (HTTP API) | 1M req / mes (12 meses) | ~10k req | US$ 0 |
| SQS | 1M req / mes (permanente) | ~50k req | US$ 0 |
| DynamoDB On-Demand | 25 GB armazenamento | < 1 GB | ~US$ 0 |
| DynamoDB GSI esparso | incluso no On-Demand | proporcional ao backlog | ~US$ 0 |
| CloudWatch Logs | 5 GB ingestao / mes | < 500 MB | US$ 0 |
| Route 53 | nenhuma | 1 hosted zone | **US$ 0,50 / mes** |
| ACM | gratuito para uso em servicos AWS | 1 certificado | US$ 0 |

**Total realista: US$ 0,50 a US$ 2,00 por mes.**

O unico custo fixo garantido e a hosted zone do Route 53.

### Impacto do outbox

Cada ingestao passa a fazer `TransactWriteItems` com 3 itens em vez de 1 escrita simples.
Transacoes consomem 2x WCU por item. Somando a escrita e a remocao no GSI esparso, o
custo por ingestao e aproximadamente **4x** o de uma escrita simples.

Em valores absolutos isso permanece dentro da franquia nos volumes previstos, mas e uma
decisao consciente de trocar custo por correcao. Ver
[ADR-003](docs/adr/ADR-003-transactional-outbox.md).

---

## Armadilhas identificadas

Servicos que cobram **mesmo sem uso**:

| Recurso | Custo parado | Decisao |
|---|---|---|
| NAT Gateway | ~US$ 32 / mes | Nao usar VPC privada |
| Aurora Serverless v2 | ~US$ 43 / mes minimo | Rejeitado no ADR-001 |
| RDS | continuo por instancia | Fora do escopo |
| EC2 permanente | continuo | Fora do escopo |
| Event source mapping SQS -> Lambda | long-polling continuo | Rejeitado no ADR-003 |
| CloudWatch Logs sem retencao | acumula indefinidamente | Retencao de 7 dias |
| DynamoDB Provisioned | cobra capacidade reservada | Usar On-Demand |
| Elastic IP nao associado | ~US$ 3,60 / mes | Nao usar |

---

## Guard rails previstos

- `ReservedConcurrentExecutions` por funcao Lambda
- `MaximumBatchSize` no consumo
- Retencao de logs de 7 dias
- AWS Budget com alerta em US$ 5
- Teto rigido de 10.000 registros por operacao de geracao
- TTL em registros de idempotencia (48h)

---

## Aviso sobre medicoes locais

DynamoDB Local nao aplica limites de throughput, nao simula latencia de rede e nao cobra.
Numeros de performance obtidos localmente **nao** podem ser apresentados como previsao de
custo ou desempenho na AWS.
