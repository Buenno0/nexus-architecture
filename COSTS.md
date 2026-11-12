# Custos — Nexus Architecture

**Regra inegociavel:** nenhum recurso AWS e criado sem apresentacao previa de custo
estimado e autorizacao explicita.

## Situacao atual

**US$ 0,00.** Nenhum recurso de nuvem provisionado.

## Custo real medido: deploy de 07 a 09/11/2026

A plataforma rodou na AWS por tres dias e foi destruida em 09/11. Custo real, da conta
inteira, no periodo:

| Servico | Custo | Origem |
|---|---|---|
| **Amazon DynamoDB** | **US$ 0,0001** | Nexus (unica tabela da conta) |
| Amazon API Gateway | US$ 0,0000 | Nexus, dentro da franquia |
| Lambda, SQS, Cognito, Scheduler | US$ 0,0000 | Nexus, dentro da franquia |

**Custo total do Nexus nos tres dias: cerca de um decimo de centavo.**

Os demais valores da conta no periodo (ECS US$ 0,42, VPC US$ 0,32, S3 US$ 0,22,
CloudWatch US$ 0,16) sao de outros projetos.

> **Ressalva sobre a medicao.** A primeira consulta, filtrada pela tag
> `Project=nexus-architecture`, devolveu US$ 0,00 — **mas nao porque nao houve gasto**.
> Nenhuma tag de alocacao de custo estava ativada na conta, entao o filtro nao casava
> com nada.
>
> Os numeros acima vem da apuracao por servico, sem filtro de tag, atribuindo ao Nexus
> os servicos que so ele usava. O Terraform passou a ativar a tag automaticamente
> (`aws_ce_cost_allocation_tag`), mas isso tem duas consequencias: leva ate 24h para
> refletir e nao reclassifica gasto anterior.
>
> **O budget tinha o mesmo defeito**: seu `cost_filter` apontava para a tag inativa e
> nunca teria disparado alerta. Corrigido.

### Comparacao com a estimativa

| | Estimado | Real (3 dias) |
|---|---|---|
| DynamoDB | ~US$ 0,10/mes | US$ 0,0001 |
| Demais servicos | US$ 0,00 | US$ 0,00 |

O volume da demonstracao foi muito menor que os 10.000 registros/mes da estimativa, o
que explica a diferenca. A estimativa continua valida para o volume que ela assume.

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

### Impacto da observabilidade (Fase 6)

A trilha e a serie sao escritas adicionais no DynamoDB. Nenhum servico novo, nenhum
recurso que cobre ocioso — mas nao sao de graca.

| Item | Volume | Observacao |
|---|---|---|
| Marcos da trilha | ate **6 por registro** | `accepted`, `published`, `consumed`, `resolved` no caminho feliz; `failed` e `dead_lettered` somam nas falhas |
| Tamanho do item | ~400 bytes | 1 WRU cada (a unidade cobre ate 1 KB) |
| Amostras da serie | 1 por balde de 15s | **somente quando alguem observa** |
| Leitura da trilha | 1 Query por consulta | sob demanda, no painel |

Com 10.000 registros/mes e observacao continua:

```
trilha:   10.000 x 6                       =  60.000 WRU
serie:    4/min x 60 x 24 x 30             = 172.800 WRU
                                             ---------
                                             232.800 WRU  =  0,2328 M

0,2328 M x US$ 0,625/M  =  US$ 0,15/mes
```

**A serie custa quase o triplo da trilha** se alguem deixar o painel aberto o mes
inteiro. Nao e um valor que assuste, mas e contraintuitivo: o custo da observabilidade
aqui e dominado por quem observa, nao por quanto a plataforma processa.

Em retentativa o numero sobe: cada tentativa gera `consumed` + `failed`. Um registro que
esgota tres tentativas antes da DLQ produz **8 marcos** em vez de 4.

**TTL de 7 dias em ambos.** A expiracao por TTL **nao consome WCU** — e das poucas
operacoes gratuitas do DynamoDB, e e por isso que a retencao curta nao tem custo de
limpeza.

**Nao medido na AWS.** Os numeros acima sao aritmetica sobre a tabela de precos, nao
observacao. A infraestrutura esta destruida desde 09/11/2026. O impacto sob carga real
e tema da Fase 7.

### Custo da campanha de carga (Fase 7)

**US$ 0,00.** A campanha inteira rodou contra DynamoDB Local em container. Nenhum
recurso AWS foi criado, e a conta segue sem infraestrutura desde 09/11/2026.

A medicao na nuvem foi **considerada e recusada**, com a razao registrada aqui porque
ela nao e de custo:

> A conta tem cota de **10 execucoes Lambda concorrentes no total**. Qualquer numero de
> vazao medido na AWS seria a cota, nao a arquitetura — com 10 concorrentes e ~100 ms
> de latencia, o teto e ~100 req/s por construcao. Medir ali responderia "qual e a
> cota da conta", pergunta cuja resposta ja esta no console.

O que a AWS **poderia** responder, e que continua em aberto: forma da latencia com rede
real e custo de cold start. Isso exige reimplantar a infraestrutura e caberia em menos
de US$ 1,00 — cerca de US$ 0,57 de DynamoDB para 50 mil registros com trilha, o resto
dentro da franquia. Fica para quando houver outra razao para subir a infraestrutura; a
tabela de "Quanto custa um teste de carga" acima continua valendo como estimativa.

## Custo da Fase 8 — integracao continua

**US$ 0,00.** O repositorio e publico, e repositorios publicos tem minutos ilimitados
em runners padrao do GitHub Actions. A primeira execucao consumiu 1min31s de relogio
nos quatro jobs.

Quando for publicado, o custo depende da visibilidade, e a diferenca nao e pequena:

| Visibilidade | Minutos de GitHub Actions | Custo |
|---|---|---|
| Publico | ilimitados em runners padrao | **US$ 0,00** |
| Privado | 2.000 min/mes na conta gratuita | US$ 0,008/min depois disso |

Uma execucao completa do pipeline consome os quatro jobs em paralelo. A suite Python
leva cerca de um minuto nesta maquina; somando instalacao de dependencias, subida do
DynamoDB e o Control Center, a estimativa e de **4 a 8 minutos de runner por push**.

Num repositorio privado com 2.000 minutos, isso da ordem de **250 a 500 execucoes por
mes** dentro da franquia — folgado para um projeto de uma pessoa, apertado se o
pipeline rodar em cada commit de um branch movimentado.

**Nenhum job do CI toca na AWS.** Nao ha credencial no pipeline, `terraform validate`
roda com `-backend=false` e nenhum recurso e criado. O custo de CI nao pode virar custo
de nuvem por acidente — e essa e a razao de a configuracao ser assim, nao so a
seguranca.

> Se algum dia o CI precisar de credenciais da AWS — para um teste de integracao real,
> por exemplo —, a conta de custo muda de natureza: passa a existir um caminho em que
> um push cria recurso. Isso exigiria OIDC em vez de chave estatica, um papel com
> permissao minima, e autorizacao explicita. Nao e o caso hoje.

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
