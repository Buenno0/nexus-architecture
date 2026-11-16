# ADR-011 — Limites de escrita na demonstracao publica

- **Status:** Implantada na demonstracao publica em 15/11/2026.
- **Data:** 2026-11-15

## Contexto

A credencial de convidado esta no bundle publico. O JWT identifica uma sessao valida,
mas nao distingue o visitante de um operador. Antes desta decisao, o gateway roteava
operacoes de fila e decisoes de revisao para essa credencial. Confirmar uma revisao
pode fundir entidades e o motivo aceita texto livre em um acervo compartilhado.

## Decisao

Em modo demo, o gateway nao roteia POST em `/v1/ops/*` nem em
`/v1/resolution/*`. A API recusa independentemente as rotas de despacho, processamento,
redrive, reprocessamento, amostragem e decisao de revisao. A geracao sintetica continua
limitada pela cota do servidor. Operacoes continuam disponiveis no modo local ou de
operador fora da demo. O Scheduler invoca dispatcher e worker diretamente, sem usar
essas rotas HTTP.

Na aplicacao, uma dependencia global bloqueia por padrao metodos de escrita no modo
demo; a unica excecao e `POST /v1/demo/seed`. Isso tambem cobre futuras rotas de escrita
registradas na API. As protecoes especificas continuam como defesa adicional. Leituras
como `/metrics` podem registrar amostras operacionais limitadas; nao sao uma garantia
de ausencia absoluta de escritas internas.

Na verificacao de 15/11/2026, a credencial publica autenticou e uma decisao de revisao
para um identificador inexistente chegou a logica da versao publicada, que respondeu
`record_not_found`. Nao foi tomada uma decisao sobre um par existente. Requisicoes
invalidas as rotas de despacho, processamento, redrive e reprocessamento receberam
422, demonstrando que chegavam a validacao; nao foram executadas operacoes validas.

## Alternativas e consequencias

Uma autorizacao por papel permitiria operador e visitante na mesma implantacao, mas
exigiria um contrato de identidade e autorizacao adicional. Bloquear as mutacoes na
demo reduz a superficie agora e impede tambem que um operador as execute por HTTP nesse
ambiente. A interface informa a restricao. O acervo continua compartilhado e a
semeadura ainda consome cota; os limites e o throttle continuam necessarios.

Na mesma data, foi aplicada uma implantacao direcionada: as duas rotas de escrita
operacional foram removidas do gateway e a Lambda da API foi atualizada. Apos a
implantacao, a credencial de visitante autenticou e consultou registros, fila, metricas
e revisoes. Requisicoes validas para as cinco operacoes e para uma decisao de revisao
retornaram 404; a lista de rotas do gateway confirmou sua ausencia. Uma invocacao
direta autenticada da Lambda tambem devolveu 404 para amostragem operacional. A rota de
geracao continua disponivel; sua validacao rejeitou contagem zero, sem consumir cota.
Nenhuma operacao administrativa ou geracao valida foi executada no ambiente publico.
