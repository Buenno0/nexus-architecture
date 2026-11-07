# ADR-007 — Versionamento do processador no marcador de processamento

- **Status:** Aceita
- **Data:** 2026-11-06

## Contexto

O [ADR-005](ADR-005-idempotencia-no-consumo.md) definiu que o resultado do processamento
**e** o marcador de "ja processado": um item em `PROCESSED#<record_id>`, gravado com
escrita condicional. Isso garante efeito unico sob reentrega.

A Fase 5 substituiu o processador. E ai aparece a consequencia nao prevista:

**o marcador que garante idempotencia tambem impede melhoria.**

Os 157 registros processados pelo `DefaultProcessor` ja tinham marcador. O resolvedor de
identidade nunca os veria: a escrita condicional recusaria, o worker contaria
`ja_processada` e o acervo inteiro ficaria fora da resolucao — silenciosamente, sem erro
nenhum.

## Decisao

**A versao do processador entra na chave do marcador.**

```
PROCESSED#<record_id>#<versao>
```

`DefaultProcessor` → `pipeline-v1`. `ResolutionProcessor` → `resolution-v1`.

Consequencias diretas:

- A chave nova nao colide com a antiga, entao o acervo **reprocessa naturalmente**.
- O resultado da versao anterior **permanece consultavel**, lado a lado, para comparar
  o que mudou entre processadores.
- A idempotencia continua intacta **dentro de cada versao**: reentrega sob a mesma
  versao segue produzindo exatamente um resultado.

### Reprocessamento explicito

Registros ja consumidos nao tem mais mensagem na fila — ela foi apagada ao confirmar o
processamento. Trocar a versao nao os traz de volta sozinho.

`POST /v1/ops/reprocess` (e `make reprocess`) pagina as observacoes e reenfileira
**apenas as que nao tem resultado na versao corrente**. Rodar duas vezes nao duplica
trabalho. Teto de lote aplicado, como em toda operacao da plataforma.

### A injecao de falhas nao muda a versao

`FailureInjectingProcessor` delega `version` ao processador que envolve. Ela nao altera
o que e produzido quando nao falha; criar versao propria reprocessaria o acervo sem
motivo.

## Consequencias

**Positivas**
- Trocar o processador deixa de exigir operacao destrutiva.
- Historico preservado: da para comparar versoes sobre os mesmos registros.
- O caminho de melhoria fica explicito, em vez de depender de apagar marcadores a mao.

**Negativas**
- Um item por registro **por versao**: o armazenamento cresce a cada versao do processador.
- Reprocessar o acervo custa uma passada completa de worker.
- Versoes antigas acumulam indefinidamente; nao ha politica de expurgo (nenhuma e
  necessaria nos volumes atuais).

**Mitigacao**
- A versao so muda quando o **significado** do resultado muda, nao a cada alteracao de
  codigo.
- Se o acumulo vier a incomodar, TTL por versao antiga resolve sem alterar o desenho.

## Alternativas consideradas

| Alternativa | Motivo da rejeicao |
|---|---|
| Comando que apaga marcadores | Destrutivo: o resultado anterior some e um disparo acidental reprocessa tudo |
| So registros novos passam pelo resolvedor | O acervo existente ficaria permanentemente fora da resolucao |
| Marcador com data de validade | Reprocessaria por tempo, nao por mudanca de comportamento |
| Atributo de versao dentro do item, sem mudar a chave | A escrita condicional e sobre a chave; o item antigo continuaria bloqueando |
