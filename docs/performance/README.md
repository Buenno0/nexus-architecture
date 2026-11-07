# Performance

Medicao formal e escopo da **Fase 7**. Este diretorio recebera os relatorios do Locust.

## Observacao preliminar (Fase 1)

Coletada com `tools/generator.py` contra a stack local, 500 requisicoes:

| p50 | p95 | p99 | max |
|---|---|---|---|
| 4,0 ms | 6,1 ms | 11,6 ms | 36,6 ms |

### Por que estes numeros nao valem como previsao

- **DynamoDB Local nao aplica limites de throughput.** Nao ha estrangulamento, nao ha
  particao quente, nao ha custo.
- **Nao ha latencia de rede.** Tudo roda na mesma maquina.
- **Nao ha cold start.** Na AWS, a primeira invocacao de uma Lambda inclui inicializacao
  e distorce o P99. Essa parcela sera medida e reportada **separadamente**, nao diluida
  na media.
- **O gerador e sequencial.** Nao houve concorrencia real nesta coleta.

## Cenarios do Locust

Definidos em `tests/load/locustfile.py`, com pesos distintos de proposito:

| Cenario | Peso | O que exercita |
|---|---|---|
| Registro novo | 6 | Caminho completo: normalizacao, indice, transacao |
| Conteudo duplicado | 2 | Consulta por fingerprint no `gsi_natural` |
| Replay | 2 | Saida antecipada por idempotencia |
| Listagem | 1 | `Query` no `gsi_recency` |

Um teste que so envia registros novos mede apenas o caminho mais caro e esconde quanto
replay e deduplicacao custam de fato.

```bash
locust -f tests/load/locustfile.py --host http://localhost:8080 --headless -u 50 -r 10 -t 60s
```
