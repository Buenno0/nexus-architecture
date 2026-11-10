# Relatorio de testes — Fase 4 (Nexus Control Center)

Data: 2026-11-09 · React 19 · TypeScript 5.7 strict · Vitest 3.2

## Resumo

| Metrica | Backend | Control Center |
|---|---|---|
| Testes | **499** | **96** |
| Falhas | 0 | 0 |
| Cobertura | 90% | **80,5%** |
| Lint / tipos | ruff + mypy strict limpos | ESLint + tsc strict limpos |

TypeScript em modo estrito com `noUncheckedIndexedAccess` e
`exactOptionalPropertyTypes`, sem nenhum `any`.

## O que foi exercitado

### As regras de honestidade, cobertas por teste

| Regra | Teste |
|---|---|
| Ausencia mostra `—`, nunca `0` | `StatTile` com `null`, e zero real exibindo `0` |
| Carregando nunca vira vazio | Fila de revisao e lista de observacoes com resposta pendente |
| Falha nunca vira numero | Parametrizado nas **cinco** telas: API fora do ar exibe erro |
| Metrica sem sentido se explica | `NotAvailable` nao renderiza digito nenhum |
| Todo numero declara a origem | Rotulo presente e com a explicacao correta |

### Leitura de metricas

| Cenario | Resultado |
|---|---|
| Chave `nome{a=1,b=2}` | Rotulos separados corretamente |
| Rota `/v1/records/{record_id}` | **Preservada**: um regex ingenuo cortaria no primeiro `}` |
| Valor com `=` ou `,` | Preservado |
| Contador que diminui | Amostra descartada, nao convertida em taxa negativa ou zero |
| Buffer de historico | Respeita o limite descartando o mais antigo |

### CORS

Preflight com origem permitida, recusa de origem desconhecida, header
`idempotency-key` liberado, `x-correlation-id` exposto, requisicao sem `Origin`
continuando a funcionar, e **recusa de `*` na configuracao**.

### Verificacao manual, com a stack real

Dashboard aberto em `localhost:5173` contra a API em Docker, com 120 registros
sinteticos ingeridos:

1. Overview carregou com os modulos e os rotulos de origem.
2. Ao reconstruir o container, os contadores `processo` zeraram enquanto a profundidade
   `persistido` continuou correta — **o rotulo explicou a diferenca sem que ninguem
   perguntasse**.
3. Entity Resolution listou o par em duvida com a evidencia campo a campo: documento e
   nome identicos, e-mail em outro provedor (0,750), telefone diferente (0,000),
   score 0,838 — abaixo do limiar, aguardando decisao.

## Defeitos encontrados

### 1. A API negava uma capacidade que tinha

`/metrics` declarava `"entity_resolution": "not_implemented"`, fixo no codigo desde a
Fase 2. A Fase 5 implementou a resolucao e nao atualizou o campo.

**Passou tres fases sem ser notado** porque ninguem le aquele campo num `curl`. Bastou
exibi-lo num card para a contradicao saltar: a tela de resolucao funcionando ao lado de
um rotulo dizendo que ela nao existia.

E o espelho do erro que a regra pretende evitar — em vez de anunciar o que nao existe,
negava o que existia. Agora o campo e derivado do processador configurado, com teste de
regressao.

### 2. Carregando era renderizado como vazio

A primeira captura de tela mostrou "Nenhum par aguardando decisao" enquanto o card ao
lado dizia 1 aguardando. A lista usava `data?.items.length ?? 0`, e durante o
carregamento isso vira zero.

Um operador leria "nada a decidir" e seguiria em frente. Corrigido com estado de
carregamento proprio e dois testes.

### 3. CORS ausente na API local

O FastAPI so instalava o middleware de observabilidade. Qualquer navegador em outra
origem seria bloqueado — o dashboard nao existiria sem isso. Resolvido com origens
explicitas e recusa de `*`.

### 4. Bundle carregava o SDK do Cognito sem uso

O SDK pesa centenas de kilobytes e so e usado quando o dashboard aponta para a AWS.
A importacao dinamica o tirou do caminho inicial.

> **Correcao registrada na Fase 6.** A frase original dizia que o bundle inicial caiu
> "de 869 kB para 238 kB". Esta errado, e o erro e meu. Os 238 kB sao o **pedaco que
> saiu** — o chunk do Cognito, carregado sob demanda —, nao o que ficou. O `index.html`
> aponta para o outro arquivo: o bundle inicial caiu de ~950 kB para **712 kB**.
>
> Eu li a saida do `vite build` de cima para baixo e assumi que a linha menor era a
> entrada, sem abrir o `index.html` para confirmar. Numero publicado sem verificacao,
> exatamente o que a secao 9 do projeto manda nao fazer. O defeito so apareceu na Fase 6
> porque alguem voltou a comparar o build com o anterior.

## Limitacoes conhecidas

- **O historico vive na aba.** Recarregar zera. E o preco de nao guardar serie temporal
  no servidor; o rotulo `sessao` comunica isso.
- **Contadores `processo` zeram no reinicio da API** e nao agregam entre replicas.
- **Sem testes ponta a ponta em navegador.** A verificacao em navegador foi manual;
  Playwright ficou de fora por peso.
- **O modo Cognito nao foi exercitado contra a AWS**, que esta destruida. O caminho de
  login tem teste de componente, nao de integracao.
- **Sem deploy na Vercel.** O dashboard roda local; publicar exigiria reaplicar a
  infraestrutura.
- **Uma unica rota de navegacao.** Nao ha roteador: a aba selecionada nao vai para a
  URL, entao nao da para compartilhar link de uma tela.
