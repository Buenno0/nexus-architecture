# ADR-001 — DynamoDB Local em vez de PostgreSQL no ambiente local

- **Status:** Aceita
- **Data:** 2026-11-06

## Contexto

O plano inicial previa PostgreSQL no ambiente local e DynamoDB na AWS. Isso implicaria
manter dois modelos de dados: um relacional e um NoSQL orientado a padroes de acesso.

Dois modelos significam duas implementacoes de repositorio, dois conjuntos de testes de
integracao e uma classe inteira de bugs que so aparece apos o deploy — comportamentos
que diferem entre os bancos (transacoes, consistencia, unicidade condicional).

## Decisao

Usar **DynamoDB Local** em container Docker no ambiente de desenvolvimento, com o mesmo
codigo de persistencia que rodara contra o DynamoDB gerenciado na AWS.

PostgreSQL sai do escopo do projeto.

## Consequencias

**Positivas**
- Um unico modelo de dados e uma unica implementacao de repositorio.
- `TransactWriteItems`, escritas condicionais e indices esparsos se comportam igual nos
  dois ambientes — pre-requisito para o outbox do [ADR-003](ADR-003-transactional-outbox.md).
- Testes de integracao locais exercitam o mesmo caminho de codigo da nuvem.
- A modelagem single-table e exercitada desde o primeiro dia, nao adaptada depois.

**Negativas**
- Exige aprender modelagem NoSQL orientada a acesso em vez de aproveitar SQL existente.
- Consultas ad hoc sao mais trabalhosas: sem `JOIN`, sem agregacao no banco.
- Padroes de acesso precisam ser definidos **antes** das tabelas. Errar a modelagem
  custa caro para corrigir depois que ha dados.

**Mitigacao**
- Os padroes de acesso sao documentados em `docs/architecture/` antes da implementacao.
- DynamoDB Local nao e identico ao gerenciado: nao aplica limites de throughput, nao
  simula latencia de rede e nao cobra. Numeros de performance locais **nao** podem ser
  apresentados como previsao de custo ou desempenho na AWS.

## Alternativas consideradas

| Alternativa | Motivo da rejeicao |
|---|---|
| PostgreSQL local + DynamoDB AWS | Dois modelos, divergencia local/producao, esforco duplicado |
| PostgreSQL em tudo (Aurora Serverless v2) | Custo minimo continuo de ~US$ 43/mes, conflita com a restricao de orcamento |
| `moto` em vez de DynamoDB Local | Simula a API, mas nao e o motor real; diferencas sutis em transacoes e condicoes |
