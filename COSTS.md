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
| DynamoDB armazenamento | 25 GB, permanente | < 1 GB | US$ 0 |
| **DynamoDB escrita On-Demand** | **nenhuma** | ~120k WRU | **US$ 0,08** |
| **DynamoDB leitura On-Demand** | **nenhuma** | ~200k RRU | **US$ 0,02** |
| EventBridge Scheduler | nenhuma | 2.880 invocacoes | ~US$ 0,004 |
| Cognito | 50.000 usuarios ativos/mes | 1-2 | US$ 0 |
| CloudWatch Logs | 5 GB ingestao / mes | < 500 MB | US$ 0 |
| Route 53 | nenhuma | 1 hosted zone | **US$ 0,50 / mes** |
| ACM | gratuito para uso em servicos AWS | 1 certificado | US$ 0 |

**Estimativa realista: ~US$ 0,10 por mes** no volume previsto de ~10.000 registros/mes.

> **Correcao (2026-11-07).** A versao anterior desta tabela dizia
> "DynamoDB On-Demand | 25 GB + 2,5M leituras | ~US$ 0". **Estava errado.** A franquia
> gratuita do DynamoDB cobre 25 GB de armazenamento e 25 WCU/RCU **provisionados** —
> ela **nao cobre requisicoes On-Demand**.
>
> Com ~12 WRU por registro (transacao de tres itens a 2x WRU cada, mais escritas nos
> indices e nos itens de resolucao), 10.000 registros custam cerca de US$ 0,08 em
> escrita. Pequeno, mas **nao zero — e linear no volume**, o que muda completamente a
> conversa nos testes de carga da Fase 7.
>
> **Segunda correcao (07/11/2026, apos consultar a API de precos da AWS).** O preco de
> escrita On-Demand em us-east-1 e **US$ 0,625 por milhao de WRU**, nao US$ 1,25 — a
> AWS reduziu pela metade. A estimativa acima ja usa o valor verificado.

### Quanto custa um teste de carga

| Registros | WRU aproximadas | Custo de escrita |
|---|---|---|
| 10.000 | 120.000 | US$ 0,08 |
| 100.000 | 1.200.000 | US$ 0,75 |
| 1.000.000 | 12.000.000 | **US$ 7,50** |

**Toda campanha de carga na AWS sera estimada e autorizada antes de rodar**, e o custo
real registrado aqui depois.

### A armadilha do modo provisionado

> **Correcao grave (07/11/2026).** Esta secao antes recomendava DynamoDB
> **Provisionado** como alternativa de "custo zero", afirmando que 25 WCU/RCU ficariam
> na franquia. **Estava errado, e caro.**
>
> A franquia de 25 RCU e 25 WCU e **POR CONTA, somando a tabela e TODOS os indices**.
> Esta tabela tem 4 GSIs — sao 5 componentes. Provisionar 25 em cada daria 125/125,
> ou seja **100 unidades acima da franquia**:
>
> | | Excedente | Preco/hora | Custo/mes |
> |---|---|---|---|
> | Escrita | 100 WCU | US$ 0,00065 | US$ 47,45 |
> | Leitura | 100 RCU | US$ 0,00013 | US$ 9,49 |
> | **Total** | | | **US$ 56,94** |
>
> Contra US$ 0,08 do On-Demand: **712 vezes mais caro**. Descoberto ao inspecionar o
> plano do Terraform, antes de aplicar.

O Terraform foi corrigido: `dynamodb_provisioned_capacity` passou a ser um **orcamento
total**, dividido automaticamente entre a tabela e os 4 GSIs. Com o padrao de 25, cada
componente recebe 5 unidades — dentro da franquia, custo zero.

Mas 5 WCU na tabela nao sustenta a plataforma: uma ingestao e `TransactWriteItems` com
3 itens, custando 6 WCU. A taxa sustentada cai para ~0,8 registros/segundo, e os 500
registros do gerador levariam ~10 minutos com throttling.

**Conclusao: use On-Demand.** US$ 0,08 por mes e menos de um centavo por dia, e o modo
provisionado so compensaria num volume em que a economia justificasse o estrangulamento
— que nao e o caso deste projeto.

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
| Event source mapping SQS -> Lambda | ~US$ 0 com fila ociosa | Rejeitado no ADR-003 **por processar sozinho**, nao por custo |
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
