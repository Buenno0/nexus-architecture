# Relatorio de testes — Fase 2 (Nexus Queue Engine)

Data: 2026-11-06 · Python 3.13.18 · SQLite 3.46.1 (container) · DynamoDB Local 2.5.2

## Resumo

| Metrica | Fase 1 | Fase 2 |
|---|---|---|
| Testes | 169 | **265** |
| Falhas | 0 | 0 |
| Cobertura global | 91% | **90%** |
| Cobertura `src/nexus/queue` | — | **~90%** |
| Ruff / mypy strict | limpo | limpo |

## O que foi exercitado

### Fila (ADR-004)

| Cenario | Resultado |
|---|---|
| Publicacao idempotente por `event_id` | Republicacao nao duplica |
| Visibility timeout expira | Mensagem reaparece com `receive_count` incrementado |
| Recibo vencido | Nao apaga trabalho ja reivindicado por outro consumidor |
| Recibo por mensagem | Confirmar uma nao afeta as demais do lote |
| Falha dentro do limite | Reagenda com backoff crescente |
| Falha no limite | Vai para a DLQ |
| Mensagem envenenada | Nao bloqueia as demais do lote |
| Redrive | Devolve a fila com contagem zerada |
| Durabilidade | Sobrevive a nova conexao e a reinicio |
| **4 consumidores, 200 mensagens** | **Nenhuma perdida, nenhuma entregue duas vezes** |
| 20 publicacoes concorrentes do mesmo evento | Exatamente uma vence |

### Idempotencia no consumo (ADR-005)

| Cenario | Resultado |
|---|---|
| Mesma mensagem reentregue | Exatamente um `ProcessingResult` |
| Consulta previa | Evita o trabalho, mas nao e a garantia |
| Corrida na escrita | `CommitConflictError` tratado como ja processada, nao como erro |
| `make process` duas vezes | Nenhum resultado duplicado |
| Registro inexistente | DLQ imediata, sem gastar tentativas |

### Pipeline ponta a ponta

`POST → outbox → dispatch → fila → worker → ProcessingResult`, contra DynamoDB Local e
fila SQLite reais, incluindo a recuperacao de eventos que a ingestao nao publicou.

## Demonstracao operacional

```bash
python tools/generator.py --count 200 --duplicate-rate 0.2 --variant-rate 0.1 --post --seed 2026
# aceitos=157  duplicados=43  replays=0  conflitos=0  falhas=0

make drain
# recebidas=157  processadas=157  ja_processadas=0  retentativas=0  dlq=0  duracao=558ms
```

### Ciclo de falha completo

```
40 mensagens, injecao de falhas a 100%
  tentativa 1 -> retentativas=40
  tentativa 2 -> retentativas=40
  tentativa 3 -> dlq=40
redrive      -> devolvidas=40
reprocessar  -> processadas=40, fila vazia
```

### Recuperacao pelo dispatcher

Com `NEXUS_QUEUE_BACKEND=none`, 40 registros ingeridos acumularam no outbox sem consumir
tentativas. Religada a fila, `make dispatch` recuperou todos — 25 no primeiro lote
(teto padrao) e 15 no segundo.

## Defeitos encontrados e corrigidos

1. **`executescript` dentro de transacao explicita.** Ele gerencia a propria transacao;
   o `COMMIT` seguinte falhava com "cannot commit - no transaction is active".

2. **Ordem dos PRAGMAs.** `journal_mode=WAL` antes de `busy_timeout` falhava com
   "database is locked" quando varias conexoes abriam ao mesmo tempo, em vez de esperar
   pelo bloqueio.

3. **Recibo por lote em vez de por mensagem.** `DELETE WHERE receipt = ?` apagava
   **todas** as mensagens do lote ao confirmar a primeira. Um worker que caisse no meio
   perderia as restantes sem processa-las, e uma unica falha mandaria o lote inteiro
   para a DLQ. Corrigido concatenando o token do lote com o `message_id` da linha.

4. **Volume nomeado pertencente a root.** O container roda sem privilegios e nao
   conseguia abrir o banco. Um volume vazio herda dono do diretorio correspondente na
   imagem, entao o `chown` passou para o Dockerfile.

5. **SQLite com WAL sobre bind mount do macOS.** Ver abaixo.

## O achado mais instrutivo

Com o arquivo da fila em bind mount, um worker no **host** consumindo a fila escrita
pela API no **container** recebeu **167 entregas para 157 mensagens**.

Causa: o modo WAL coordena leitores e escritores por memoria compartilhada (`-shm`) e
locks POSIX, que nao atravessam de forma confiavel a fronteira entre o host macOS e a VM
Linux do Docker.

Correcao: a fila passou para volume nomeado e todo acesso acontece dentro do container
(ADR-004). Apos a mudanca: **157 recebidas, 157 processadas, zero duplicatas.**

**O detalhe que importa:** aquelas 10 reentregas **nao produziram efeito duplicado**. A
escrita condicional do ADR-005 as capturou como `ja_processadas`, e exatamente 157
resultados foram gravados. Foi uma injecao de falha acidental — e a garantia de
idempotencia funcionou exatamente como projetada, antes de alguem saber que havia uma
falha a corrigir.

## Limitacoes conhecidas

- **A fila so pode ser acessada de dentro do container** (ADR-004). A restricao
  desaparece na Fase 3: o SQS e servico de rede, sem arquivo compartilhado.
- **Endpoints `/v1/ops/*` nao tem autenticacao.** Expostos apenas no ambiente local;
  autenticacao e requisito da Fase 3.
- **Nao ha Entity Resolution.** O processador da Fase 2 executa mecanica de pipeline e
  declara `entity_resolution: not_implemented` no proprio resultado. Fase 5.
- **`in_flight` agrega mensagens em processamento e mensagens aguardando retentativa.**
  Ambas estao invisiveis; distingui-las exigiria uma coluna a mais sem necessidade atual.
- **Sem long polling.** O consumidor pergunta, nao e notificado — consistente com o
  modelo de execucao sob demanda.
- **A fila nao escala para multiplos hosts.** E um arquivo local, por desenho.
