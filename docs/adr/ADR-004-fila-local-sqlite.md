# ADR-004 — Fila local sobre SQLite

- **Status:** Aceita
- **Data:** 2026-11-06

## Contexto

A Fase 2 precisa de uma fila real no ambiente local: visibility timeout, contagem de
entregas, backoff e Dead Letter Queue. Sem ela, nao ha como exercitar retentativa,
recuperacao de falhas nem idempotencia no consumo antes de ir para a AWS.

A restricao de custo exclui qualquer servico que fique ligado. A restricao pedagogica
exclui esconder o mecanismo atras de uma biblioteca: o objetivo e **compreender** como
uma fila garante entrega, nao importar o comportamento pronto.

## Decisao

Implementar a fila sobre **SQLite**, reproduzindo as primitivas do SQS.

| Primitiva | Mecanismo |
|---|---|
| Publicacao idempotente | `INSERT OR IGNORE` sobre `event_id` unico |
| Reivindicacao atomica | `BEGIN IMMEDIATE` + `UPDATE … RETURNING` |
| Visibility timeout | coluna `visible_at` adiada na entrega |
| Recibo por entrega | `receipt = <token do lote> || ':' || message_id` |
| Backoff | `visible_at = agora + base * 2^(tentativas-1)` |
| DLQ | tabela `dead_letters` ao atingir `queue_max_receive` |
| Redrive | devolve a fila com contagem zerada |

### `BEGIN IMMEDIATE` e o ponto critico

Com o `BEGIN` padrao, diferido, dois consumidores leem as mesmas linhas, ambos as
julgam disponiveis e ambos as reivindicam — entrega dupla silenciosa. `BEGIN IMMEDIATE`
adquire o bloqueio de escrita **antes** de ler, serializando a reivindicacao.

Verificado por teste: 4 consumidores concorrentes sobre 200 mensagens entregam cada uma
exatamente uma vez.

### O recibo identifica uma entrega, nunca o lote

Primeira implementacao gerava um recibo por lote. Consequencia:
`DELETE WHERE receipt = ?` apagava **todas** as mensagens do lote ao confirmar a
primeira. Se o worker caisse no meio, as restantes sumiam sem terem sido processadas, e
uma unica falha mandava o lote inteiro para a DLQ.

Concatenar o token do lote com o `message_id` da propria linha resolve numa unica
instrucao SQL, sem escritas adicionais.

## Restricao operacional: o arquivo nao atravessa a fronteira host/VM

**A fila so pode ser acessada de dentro do container.**

SQLite em modo WAL coordena leitores e escritores por um arquivo de memoria
compartilhada (`-shm`) e locks POSIX. Em bind mount no macOS, essa coordenacao atravessa
a fronteira entre o host e a VM Linux do Docker e **nao funciona de forma confiavel**.

Observado na pratica: com o arquivo em bind mount, um worker rodando no host contra a
API no container recebeu 167 entregas para 157 mensagens — 10 reentregas espurias.

Por isso:

- A fila vive num **volume nomeado**, nao em bind mount.
- `make dispatch`, `make process` e `make drain` executam via `docker compose exec`.
- Rodar a plataforma inteira no host, sem Docker, tambem e valido: o que nao pode e
  **misturar** os dois ambientes sobre o mesmo arquivo.

A restricao desaparece na Fase 3: o SQS e um servico de rede, sem arquivo compartilhado.

> Nota: aquelas 10 reentregas **nao produziram efeito duplicado**. A escrita condicional
> do [ADR-005](ADR-005-idempotencia-no-consumo.md) as capturou como `ja_processadas`, e
> exatamente 157 resultados foram gravados. Foi uma injecao de falha acidental que
> demonstrou a garantia funcionando.

## Consequencias

**Positivas**
- Cada garantia e uma linha de SQL legivel, nao comportamento importado.
- Zero custo e zero processo residente.
- Durabilidade real: `synchronous=FULL` faz a mensagem sobreviver a queda do processo.
- A troca por SQS e mudanca de configuracao — ingestao e worker dependem de
  `QueueClient`, nunca desta classe.

**Negativas**
- Nao escala para multiplos hosts: o arquivo e local.
- Exige disciplina de ambiente unico (a restricao acima).
- Mais codigo nosso para manter do que usar um broker pronto.
- Sem long polling: o consumidor pergunta, nao e notificado.

## Alternativas consideradas

| Alternativa | Motivo da rejeicao |
|---|---|
| Redis | Processo residente e dependencia a mais sem problema concreto a resolver |
| Celery | Traz broker e backend de resultado; esconde justamente o mecanismo que queremos entender |
| Kafka | Exige cluster permanente; custo fixo incompativel com COSTS.md |
| Fila em memoria | Nao sobrevive a reinicio; nao exercita durabilidade nem reentrega |
| `moto` simulando SQS | Simula a API, nao o comportamento sob concorrencia e falha |
