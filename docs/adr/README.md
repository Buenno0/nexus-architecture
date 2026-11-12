# Decisoes de arquitetura (ADR)

Um ADR registra uma decisao e **o motivo dela**, incluindo o que foi recusado. O valor
esta na segunda parte: a decisao se le no codigo, a alternativa descartada nao.

Nenhum ADR e reescrito quando a realidade muda. A correcao entra como emenda no proprio
documento, com data — apagar o raciocinio original apagaria a razao de ter mudado.

## Indice

| # | Decisao | Status | Fase |
|---|---|---|---|
| [001](ADR-001-dynamodb-local.md) | DynamoDB Local em vez de PostgreSQL | Aceita | 1 |
| [002](ADR-002-identidade-e-idempotencia.md) | Separar operacao, conteudo e entidade | Aceita | 1 |
| [003](ADR-003-transactional-outbox.md) | Transactional outbox com GSI esparso | Aceita, com correcao interna | 2 |
| [004](ADR-004-fila-local-sqlite.md) | Fila local sobre SQLite | Aceita | 2 |
| [005](ADR-005-idempotencia-no-consumo.md) | Marcador e resultado num unico item | Aceita — **emendada pelo 007** | 2 |
| [006](ADR-006-entity-resolution.md) | Blocking, pontuacao e clusterizacao auditavel | Aceita | 5 |
| [007](ADR-007-versionamento-do-processador.md) | Versionar o processador no marcador | Aceita | 5 |
| [008](ADR-008-arquitetura-serverless.md) | Arquitetura serverless na AWS | Aceita — **implantada e destruida** | 3 |
| [009](ADR-009-control-center.md) | Todo numero declara de onde veio | Aceita — **parcialmente superada pelo 010** | 4 |
| [010](ADR-010-observabilidade.md) | Trilha durável, best-effort, por registro | Aceita | 6 |

Nenhum ADR foi **revogado**. Tres tiveram o alcance alterado, e cada um diz isso no
proprio cabecalho.

## As tres decisoes que mudaram

### 005 -> 007: o mecanismo que garantia correcao impedia melhoria

O ADR-005 fez do resultado do processamento o proprio marcador de "ja processado": um
item, uma escrita condicional, efeito unico sob reentrega.

A Fase 5 trocou o processador e a consequencia apareceu: os registros ja processados
tinham marcador, entao **o resolvedor novo nunca os veria**. A garantia de idempotencia
estava congelando o acervo numa versao antiga da logica.

O ADR-007 versiona o marcador. A garantia continua intacta — nada do ADR-005 foi
revogado —, mas passa a ser por versao de processador, o que torna o reprocessamento
possivel sem abrir mao dela.

### 009 -> 010: a limitacao aceita deixou de ser necessaria

O ADR-009 decidiu acumular a janela deslizante na aba do navegador e rotular esses
numeros como `sessao`, aceitando que recarregar a pagina zera o historico. A alternativa
— guardar a janela no servidor — foi **recusada com um argumento que estava certo na
epoca**: seria estado que tambem zera no reinicio.

A Fase 6 fechou isso persistindo a serie no armazenamento, e os graficos de profundidade
passaram a mostrar `persistido`. O principio do ADR-009 nao mudou em nada; mudou um caso
concreto que ele regia.

Duas observacoes que o ADR-009 fez continuam valendo sem emenda: contador que diminui e
descartado em vez de virar taxa zero, e ausencia e mostrada como `—`, nunca como `0`.

### 008: a decisao continua valida, a infraestrutura nao existe

O ADR-008 esta implementado, foi aplicado na AWS, verificado ponta a ponta e
**destruido**. O Terraform continua versionado e o job de CI o valida a cada push, para
que nao apodreca enquanto esta fora do ar.

Isso importa para ler o resto da documentacao: todo numero de desempenho deste projeto e
local. A Fase 7 **recusou** medir na AWS, porque a cota de 10 execucoes concorrentes da
conta faria qualquer vazao medida la ser a cota, nao a arquitetura.

## Correcoes dentro de um ADR

O **ADR-003** carrega uma correcao no proprio texto. O descarte do event source mapping
SQS -> Lambda foi justificado inicialmente por custo; o custo nao se sustenta, porque o
long-polling de uma fila ociosa cabe na franquia gratuita do SQS. A razao verdadeira e
outra — um consumidor residente desfaz a execucao sob demanda que a plataforma existe
para demonstrar. O argumento errado ficou no documento, marcado como errado.

## O que ainda nao tem ADR

Decisoes tomadas mas nao elevadas a ADR, porque nenhuma delas fechou uma alternativa
cara de reverter:

- **Mermaid para diagramas** em vez de imagem — reversivel num commit.
- **Locust** como gerador de carga — a metodologia em
  [docs/performance/metodologia.md](../performance/metodologia.md) e o que importa, e
  ela independe da ferramenta.
- **GitHub Actions** para CI. Vira ADR se o pipeline passar a precisar de credenciais
  da AWS, porque ai a decisao envolve confianca em terceiro e deixa de ser reversivel
  sem consequencia.

## Quando escrever um novo

Quando a decisao for cara de reverter, quando houver alternativa razoavel sendo
recusada, ou quando o motivo nao couber num comentario de codigo. **Decisao obvia nao
precisa de ADR** — e cerimonia, e o projeto ja recusou cerimonia antes (a Fase 1
dispensou infraestrutura como codigo exatamente por isso).
