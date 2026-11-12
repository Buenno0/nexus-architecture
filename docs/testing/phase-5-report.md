# Relatorio de testes — Fase 5 (Nexus Entity Resolution)

Data: 2026-11-06 · Python 3.13.18 · DynamoDB Local 2.5.2

## Resumo

| Metrica | Fase 2 | Fase 5 |
|---|---|---|
| Testes | 267 | **402** |
| Falhas | 0 | 0 |
| Cobertura global | 92% | **93%** |
| Cobertura `src/nexus/resolution` | — | **~97%** |
| Ruff / mypy strict | limpo | limpo |

## Medicao de qualidade

**Esta e a metrica que importa.** O gerador produz o gabarito (`--manifest`): cada
registro carrega a entidade verdadeira que o originou. A avaliacao compara **pares**,
nao clusters, e reporta precisao e recall separadamente — uma media esconderia a
assimetria entre os dois tipos de erro.

```bash
python tools/generator.py --count 500 --duplicate-rate 0.15 --variant-rate 0.25 \
  --post --seed 2026 --manifest gabarito.json
make drain
python tools/evaluate_resolution.py --manifest gabarito.json
```

Conjunto: 413 observacoes, 315 entidades verdadeiras, 113 pares verdadeiros.
Variantes realistas: abreviacao de nome, erro de digitacao, troca de provedor de
e-mail, campo omitido, documento ausente.

| Metrica | Primeira execucao | Apos correcao |
|---|---|---|
| Falsos positivos | 0 | **0** |
| Falsos negativos | 2 | **0** |
| Precisao | 1,0000 | **1,0000** |
| Recall | 0,9823 | **1,0000** |
| F1 | 0,9911 | **1,0000** |

> **O que estes numeros nao dizem.** As variacoes do conjunto foram geradas por
> `tools/generator.py`, e o gabarito sabe quais pares sao verdadeiros porque o gerador
> os criou. Acertar 100% contra as proprias variacoes nao prova que o resolvedor
> funciona com dados reais — prova que ele cobre as formas de sujeira que eu soube
> imitar. O valor esta na coluna da esquerda: sem gabarito, os 2 falsos negativos da
> primeira execucao seriam invisiveis.

### O ciclo que justifica o gabarito

A primeira execucao perdeu 2 pares. A fila de revisao mostrou a causa concreta: um par
com **documento, e-mail e telefone identicos** caiu para `POSSIBLE_MATCH` porque
`full_name` pontuou **0,000** — "Enzo Cunha" contra "Enzo Gabriel da Cunha".

Jaro-Winkler da 0,629 e `token_sort_ratio` da 0,645 para esse par: ambos abaixo do piso.
O nome mais curto simplesmente parece diferente.

A correcao foi o criterio de subconjunto de tokens, com duas protecoes:

- **minimo de dois tokens em comum** — com um so, "Maria" casaria igualmente com
  "Maria Souza" e com "Maria Pereira";
- **teto de 0,95** — conter todos os tokens do outro nome e evidencia forte, nao
  identidade.

Recall subiu para 1,0000 **sem introduzir nenhum falso positivo**. Sem gabarito, essa
fraqueza teria passado como comportamento normal.

> **Ressalva:** dados sinteticos com variacoes conhecidas nao representam a sujeira de
> dados reais. O numero mede o resolvedor contra este conjunto, nao contra o mundo.

## O que foi exercitado

### Comparadores e pontuacao

| Cenario | Resultado |
|---|---|
| Acento, caixa, forma Unicode | Nao separam |
| Ordem dos tokens do nome | Nao separa |
| Nome do meio omitido | Pontua acima de 0,8 |
| Um unico token em comum | Pontua menos que subconjunto real |
| Nomes sem relacao | Zeram (piso de similaridade) |
| Documento com digito trocado | Positivo fraco; vai para revisao |
| Mesma parte local, dominio diferente | 0,75 |
| Mesmo dominio, locais sem relacao | 0,25 |
| Telefone com um digito diferente | Zera (e outra linha, nao erro) |
| Campo ausente | Nao penaliza nenhum dos lados |
| Guarda de 2 campos | Nome igual sozinho nao funde |
| Identificador forte exato | Dispensa a guarda |

### Clusterizacao

| Cenario | Resultado |
|---|---|
| A~B e B~C | Os tres na mesma entidade |
| Dois clusters ligados | Fusao da menor na maior |
| Fusao | Evento com o par, score e membros movidos |
| Entrada acima do teto | Recusada e entidade sinalizada |
| Fusao que estouraria o teto | Recusada e **ambas** sinalizadas |
| Par ja ligado | Nenhuma escrita |
| Versao divergente | `CommitConflictError`; a fila retenta |
| Entidade removida por fusao concorrente | Tratado sem corromper estado |

### Revisao

| Cenario | Resultado |
|---|---|
| `POSSIBLE_MATCH` | Abre revisao e **nao funde** |
| Confirmar | Funde os clusters |
| Recusar | Registra e nao funde |
| Decidido | Sai do indice esparso |
| Par repetido | Nao duplica a revisao |

### Reprocessamento (ADR-007)

| Cenario | Resultado |
|---|---|
| Acervo em `pipeline-v1` | Reenfileirado sob `resolution-v1` |
| Resultado da versao anterior | Permanece consultavel |
| Rodar duas vezes | Nada reenfileirado; nada duplicado |
| Reentrega dentro da mesma versao | Continua produzindo um unico resultado |

## Defeito de desenho encontrado durante a fase

**O marcador que garante idempotencia tambem impedia melhoria.**

Com `PROCESSED#<record_id>` sem versao, trocar o `DefaultProcessor` pelo resolvedor nao
reprocessaria nada: o marcador antigo existe, a escrita condicional recusaria, e os 157
registros ficariam fora da resolucao **silenciosamente** — sem erro, sem alerta, apenas
contados como `ja_processadas`.

Corrigido pelo [ADR-007](../adr/ADR-007-versionamento-do-processador.md): a versao entra
na chave, o acervo reprocessa naturalmente e o resultado anterior fica preservado.

## Limitacoes conhecidas

- **Metricas de qualidade valem para dados sinteticos.** Dados reais trazem sujeira que
  o gerador nao imita.
- **Pesos e limiares sao parametros calibrados contra este conjunto**, nao verdades.
- **Blocos muito grandes limitam recall.** O teto de candidatos protege o custo e
  sinaliza a truncagem, mas ela continua sendo uma perda possivel.
- **Teto de cluster recusa fusoes legitimas** em entidades muito observadas. E a troca
  deliberada: falso negativo visivel no lugar de falso positivo silencioso.
- **Nao ha interface de revisao**, apenas endpoints. A tela e escopo da Fase 4.
- **Rejeicao e por par, nao por entidade.** Rejeitar A-B nao impede que ambos se liguem
  por um terceiro registro.
- **Nao ha desfazer.** A evidencia permite localizar a aresta culpada, mas a operacao de
  reverter uma fusao especifica nao foi implementada.
