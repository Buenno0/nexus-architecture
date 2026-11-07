# ADR-006 — Blocking, pontuacao e clusterizacao auditavel

- **Status:** Aceita
- **Data:** 2026-11-06

## Contexto

O [ADR-002](ADR-002-identidade-e-idempotencia.md) estabeleceu que a API **nunca** julga
identidade: ela nao tem informacao suficiente. Toda a decisao foi adiada para esta fase.

Comparar todos contra todos e O(n²) e inviavel. E fundir dois registros e uma operacao
cujo erro nao e simetrico:

| Erro | Consequencia |
|---|---|
| **Falso positivo** | Dados de pessoas distintas se misturam. Dificil de detectar, dificil de reverter. **Risco critico do projeto.** |
| Falso negativo | Duplicata permanece. Visivel e corrigivel depois. |

Todo o desenho e orientado por essa assimetria.

## Decisao

### 1. Blocking com chaves proprias

`natural_key` e um hash: so responde igualdade exata, nao serve para candidatos
aproximados. A resolucao grava chaves proprias em texto claro
(`BLOCK#<chave>` / `RECORD#<id>`), uma por criterio: documento, e-mail, nome e telefone.
Dois registros sao candidatos se compartilham **qualquer** uma.

Chaves independentes em vez de uma composta: a chave composta so encontraria quem
concorda em todos os criterios, e o caso interessante e a mesma pessoa cadastrada uma
vez com documento e outra sem.

**A normalizacao aqui e agressiva** — acentos removidos, tudo em minusculas — ao
contrario da normalizacao conservadora da ingestao. Os objetivos sao opostos: a ingestao
preserva sinal, o blocking maximiza recall. Agrupar demais custa comparacoes que o score
descarta; perder um par e definitivo.

**Teto de candidatos** com sinalizacao explicita (`candidates_truncated`). Truncar em
silencio esconderia falso negativo.

### 2. Pontuacao com piso e guarda

Score ponderado sobre os campos presentes **nos dois** registros. Campo ausente nao
conta como divergencia: penalizaria registros esparsos.

**Piso de similaridade.** Jaro-Winkler entre strings sem relacao fica entre 0,35 e 0,50,
nao perto de zero. Sem piso, essa similaridade de fundo inflaria o score de pares que
nao tem nada a ver. Abaixo do piso o resultado e exatamente zero.

**Criterio de subconjunto de tokens** para nomes: "Enzo Cunha" dentro de "Enzo Gabriel
da Cunha". Nome do meio omitido e das variacoes mais comuns entre fontes, e as demais
medidas a pontuam baixo. Exige dois tokens em comum — com um so, "Maria" casaria
igualmente com "Maria Souza" e "Maria Pereira" — e tem teto de 0,95: conter todos os
tokens do outro nome e evidencia forte, nao identidade.

**Guarda de campos minimos.** `MATCH` exige ao menos dois campos comparados. Duas
pessoas chamadas Maria Souza sao plausiveis; fundir por um unico campo seria temerario.
Excecao para identificadores fortes: dois CPFs identicos sao a mesma pessoa.

**Tres faixas, nunca duas.** `POSSIBLE_MATCH` existe para que duvida nao vire fusao.

### 3. Clusterizacao com fecho transitivo auditavel

Apenas arestas `MATCH` fundem. Cada vinculo guarda o par e a evidencia campo a campo que
o produziram; cada fusao gera um evento com a entidade de origem.

Union-find simples resolveria a estrutura em poucas linhas, mas nao a pergunta que
aparece quando algo da errado: *por que estes dois registros estao juntos?* Com fecho
transitivo, **um falso positivo contamina o cluster inteiro**. Sem rastro, a unica saida
seria refazer tudo.

**Teto de tamanho.** Cluster que cresce demais quase sempre indica fusao em cadeia por
evidencia fraca. Ao estourar, o sistema recusa e sinaliza: prefere falso negativo
visivel a falso positivo silencioso.

**Concorrencia por versao.** Toda mutacao de entidade e condicional sobre `version`;
conflito levanta `CommitConflictError`, a mensagem volta para a fila e a retentativa da
Fase 2 resolve. Nenhuma maquinaria nova.

### 4. Fila de revisao

`POSSIBLE_MATCH` vira um item com identificador derivado do par ordenado. Rejeicao fica
registrada e impede recriar o mesmo par — senao cada reprocessamento ressuscitaria uma
decisao ja tomada.

Indice esparso `gsi_review`, mesmo padrao do [ADR-003](ADR-003-transactional-outbox.md).

### 5. Medicao com gabarito

O gerador sintetico produz o gabarito (`--manifest`): cada registro carrega a entidade
verdadeira que o originou. `tools/evaluate_resolution.py` compara pares e reporta
precisao, recall e F1 separadamente — uma media esconderia a assimetria que importa.

Sem gabarito nao da para afirmar que a resolucao funciona, apenas que ela roda.

## Consequencias

**Positivas**
- Decisoes auditaveis campo a campo; pesos ajustaveis com evidencia.
- Nenhuma fusao automatica em caso duvidoso.
- Fusoes rastreaveis ate o par que as causou.
- Qualidade mensuravel, nao presumida.
- Worker, fila e persistencia nao mudaram: o contrato `RecordProcessor` ja previa isso.

**Negativas**
- Evidencia por vinculo ocupa espaco proporcional ao numero de vinculos.
- Blocking gera itens adicionais, um por chave por registro.
- Pesos e limiares sao parametros: exigem calibracao, nao sao verdades.
- Comparacao em memoria sobre candidatos: o teto protege o custo, mas tambem limita
  recall em blocos muito grandes.

## Resultado medido

500 registros sinteticos, 25% variantes realistas (abreviacao, erro de digitacao, troca
de provedor, campo omitido, documento ausente) e 15% duplicatas exatas:

| Metrica | Valor |
|---|---|
| Pares verdadeiros | 113 |
| Falsos positivos | **0** |
| Falsos negativos | **0** |
| Precisao | 1,0000 |
| Recall | 1,0000 |

A primeira execucao deu recall 0,9823. A avaliacao apontou a causa — nome do meio
omitido pontuando zero — que virou o criterio de subconjunto de tokens descrito acima.
**Esse ciclo e o motivo de o gabarito existir.**

> Ressalva: dados sinteticos com variacoes conhecidas nao representam a sujeira de
> dados reais. O numero mede o resolvedor contra este conjunto, nao contra o mundo.

## Alternativas consideradas

| Alternativa | Motivo da rejeicao |
|---|---|
| Comparar todos contra todos | O(n²); inviavel acima de alguns milhares de registros |
| Chave de bloco composta | So encontra quem concorda em todos os criterios |
| Duas faixas (funde ou nao) | Forca decisao automatica justamente onde a evidencia e fraca |
| Union-find sem rastro | Impossibilita localizar a aresta culpada por uma fusao errada |
| Similaridade sem piso | Similaridade de fundo infla o score de pares sem relacao |
| Fundir na ingestao | Viola o ADR-002; a API nao tem informacao para julgar identidade |
| Biblioteca pronta de record linkage | Esconde exatamente o mecanismo que o projeto existe para ensinar |
