# ADR-009 — Todo numero declara de onde veio

- **Status:** Aceita
- **Data:** 2026-11-09

## Contexto

A secao 7 do projeto e explicita: **"Nao apresente dados ficticios como metricas
reais."** Construir a interface obrigou a traduzir essa regra para a tela, e isso
exigiu encarar um problema que o `curl` escondia.

Os numeros do Nexus vem de tres lugares, com garantias bem diferentes:

| Origem | Exemplo | Garantia |
|---|---|---|
| Armazenamento | `/v1/ops/queue`, `/v1/resolution/stats` | Duravel; consistente entre processos |
| Contador em processo | `/metrics` | Zera no reinicio da API; nao agrega entre replicas |
| Acumulado no navegador | series temporais dos graficos | Some ao recarregar a pagina |

Colocados lado a lado sem distincao, os tres parecem igualmente confiaveis. Nao sao.
Uma profundidade de fila persistida e uma afirmacao muito mais forte que um throughput
que some quando o container reinicia.

## Decisao

### 1. Cada card leva o rotulo da sua origem

`persistido`, `processo` ou `sessao`, com a explicacao ao passar o mouse. Nao e
decoracao: e a diferenca entre ler um numero e saber o que ele promete.

Isso ficou visivel na propria verificacao desta fase: ao reconstruir o container, os
contadores de ingestao zeraram enquanto a profundidade da fila continuou correta — o
rotulo explicava o porque sem que ninguem precisasse perguntar.

### 2. Historico fica no navegador

O backend nao guarda serie temporal: os contadores sao cumulativos e a latencia e um
resumo. Os graficos sao montados aqui, a partir do polling.

Guardar janela deslizante no servidor foi considerado e recusado: acrescentaria estado
que **tambem** zera no reinicio, e o ROADMAP ja colocou observabilidade persistente na
Fase 6. Acumular no cliente entrega o grafico hoje, sem fingir durabilidade.

A consequencia — recarregar a pagina zera — nao e escondida: e o que o rotulo `sessao`
comunica.

**Contador que diminui e descartado, nao zerado.** Contador cumulativo nao anda para
tras; quando anda, a API reiniciou. Converter isso em taxa zero inventaria um periodo
de ociosidade que nao houve.

### 3. O que nao existe aparece como nao existente

A secao 7 pede "workers em execucao". Esse numero **nao tem significado** nesta
arquitetura: a execucao e sob demanda, o worker consome um lote e termina. Nao ha
processo residente para contar.

Mostrar zero seria mentir. Omitir o card faria a pergunta sumir sem resposta. O card
existe, diz "nao se aplica" e explica por que — e nao renderiza digito nenhum, o que
um teste garante.

### 4. Ausencia e carregamento sao coisas diferentes

Sem valor, o card mostra `—`, nunca `0`. Uma lista ainda carregando mostra
"consultando…", nunca "nenhum item".

As duas regras tem a mesma raiz: *nao sei* e *nao existe* sao afirmacoes diferentes, e
trocar uma pela outra leva o operador a decidir com base em algo falso. A segunda regra
nasceu de um defeito real — a primeira captura de tela desta fase mostrou "Nenhum par
aguardando decisao" enquanto o contador ao lado dizia 1.

### 5. Falha nunca vira numero

Quando a consulta falha, a tela mostra o erro com o `correlation_id` — nunca o ultimo
valor conhecido. Um numero velho apresentado como atual e pior que numero nenhum.
Um teste parametrizado cobre as cinco telas.

### 6. Sem framework de CSS

Tema escuro proprio em custom properties. Tailwind resolveria mais rapido, mas o
projeto repete que nao adiciona tecnologia por sofisticacao visual, e o tema e pequeno.
Recharts, ao contrario, se justifica: graficos a mao seriam trabalho sem aprendizado.

## Consequencias

**Positivas**
- O operador sabe o que cada numero promete.
- O historico funciona sem acrescentar estado ao servidor.
- As regras de honestidade estao cobertas por teste, nao apenas por disciplina.
- Apontar para a AWS e trocar variaveis de ambiente.

**Negativas**
- Recarregar a pagina zera os graficos, e isso precisa ser explicado a cada novo usuario.
- Rotulos ocupam espaco em cada card.
- Com varias abas abertas, cada uma tem o proprio historico.
- A interface depende da API expor estado honesto — e nao expunha: ver abaixo.

## O defeito que a interface revelou

O `/metrics` declarava `"entity_resolution": "not_implemented"`, escrito a mao desde a
Fase 2. A Fase 5 implementou a resolucao e **esqueceu de atualizar esse campo**.

Ninguem notou por tres fases: ninguem le aquele campo num `curl`. Bastou exibi-lo num
card para a contradicao ficar obvia — a tela de Entity Resolution funcionando ao lado
de um rotulo dizendo que ela nao existia.

E o espelho do erro que a regra pretende evitar: em vez de anunciar capacidade
inexistente, a API negava uma que tinha. As duas coisas enganam.

Agora o campo e **derivado** do processador configurado, e um teste de regressao fixa o
comportamento. A licao e mais geral: **estado declarado a mao envelhece em silencio** —
deve ser derivado da realidade sempre que possivel.

## Alternativas consideradas

| Alternativa | Motivo da rejeicao |
|---|---|
| Nao distinguir origens | Faria contador volatil parecer tao confiavel quanto dado persistido |
| Janela deslizante no backend | Estado que tambem zera no reinicio; escopo da Fase 6 |
| Omitir metricas sem fonte | A pergunta da secao 7 sumiria sem resposta |
| Mostrar 0 no lugar de `—` | Zero e uma afirmacao; ausencia nao e |
| Manter o ultimo valor em caso de falha | Numero velho apresentado como atual |
| Tailwind | Tecnologia por sofisticacao visual, contra o principio do projeto |
