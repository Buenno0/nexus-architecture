# Runbook — demonstracao publica

Procedimento da Fase 9. Complementa [runbook-deploy.md](runbook-deploy.md), que cobre
a infraestrutura em si.

Ultima execucao: **12/11/2026**.

## Estado atual

| | |
|---|---|
| Infraestrutura | **no ar** desde 12/11/2026 |
| API | `https://1vsn0kmtx8.execute-api.us-east-1.amazonaws.com` |
| Painel | `https://nexus-architecture-buenno.vercel.app` |
| Acervo | 300 registros semeados, 231 processados, 45 entidades, 10 revisoes pendentes |
| Cota consumida | 300 de 5.000 |

## 1. Infraestrutura

```bash
cd infra/terraform && terraform plan -out=tfplan && terraform apply tfplan
```

Com `demo_mode = true` no `terraform.tfvars`. O `plan -out` seguido de `apply` do mesmo
arquivo garante que o revisado e o executado — e nao e preciosismo: o Terraform grava um
arquivo de plano **mesmo quando a precondicao da senha falha**, e esse plano parcial nao
inclui o usuario convidado. Aplicado por engano, subiria a demonstracao com uma tela de
login que ninguem consegue passar.

## 2. Verificacao sem credencial nenhuma

A prova de que o roteamento mudou nao precisa de token, e a distincao entre os codigos e
o ponto inteiro:

```bash
API=https://1vsn0kmtx8.execute-api.us-east-1.amazonaws.com; curl -s -o /dev/null -w "ingestao livre: %{http_code}\n" -X POST "$API/v1/records/person" -H 'content-type: application/json' -H 'Idempotency-Key: x' -d '{}'
```

- **404** na ingestao livre: a rota nao existe no gateway.
- **401** em `/v1/demo/seed`, `/v1/records`, `/v1/ops/*` e `/metrics`: existem e exigem token.
- **200** em `/health`, que e publico de proposito.

Um `401` na ingestao livre significaria que a rota existe e so esta protegida — e nao e
isso que queremos.

## 3. Semear o acervo

Pelo painel, depois de publicado. Antes disso, invocando a Lambda com credenciais de
operador — o que evita usar a senha do convidado:

```bash
aws lambda invoke --function-name nexus-dev-api --cli-binary-format raw-in-base64-out --payload '{"version":"2.0","routeKey":"POST /v1/demo/seed","rawPath":"/v1/demo/seed","rawQueryString":"","headers":{"content-type":"application/json"},"requestContext":{"accountId":"op","apiId":"d","domainName":"d","requestId":"op","stage":"$default","time":"","timeEpoch":0,"http":{"method":"POST","path":"/v1/demo/seed","protocol":"HTTP/1.1","sourceIp":"127.0.0.1","userAgent":"op"}},"body":"{\"count\": 200}","isBase64Encoded":false}' /tmp/seed.json && cat /tmp/seed.json
```

Depois drenar:

```bash
aws lambda invoke --function-name nexus-dev-worker --cli-binary-format raw-in-base64-out --payload '{"max_messages": 10, "max_batches": 20}' /tmp/worker.json && cat /tmp/worker.json
```

## 4. Publicar o painel na Vercel

Projeto apontando para este repositorio, com **Root Directory** em `control-center`.
Build `npm run build`, saida `dist`.

Variaveis de ambiente:

| Variavel | Valor |
|---|---|
| `VITE_API_URL` | `https://1vsn0kmtx8.execute-api.us-east-1.amazonaws.com` |
| `VITE_AUTH_MODE` | `cognito` |
| `VITE_COGNITO_USER_POOL_ID` | `us-east-1_BxjLFFGO2` |
| `VITE_COGNITO_CLIENT_ID` | `4aplfc048l861nflf5f1n5lltt` |
| `VITE_AWS_REGION` | `us-east-1` |
| `VITE_DEMO_MODE` | `true` |
| `VITE_POLL_INTERVAL_MS` | `30000` |
| `VITE_DEMO_GUEST_USERNAME` | `convidado` |
| `VITE_DEMO_GUEST_PASSWORD` | a senha de `demo_guest_password` |

Nenhum desses valores e segredo, **incluindo a senha**: tudo isso vai para o JavaScript
que qualquer visitante baixa. O que protege a plataforma esta em [SECURITY.md](../SECURITY.md),
e nao e o sigilo de nada disto.

O intervalo de 30s nao e detalhe. No desenvolvimento ele e 3s, e uma unica aba visivel
esquecida aberta geraria na ordem de 140.000 requisicoes por dia — mais que todos os
visitantes somados.

## 4b. Os enderecos da Vercel sao mais de um

A Vercel atribui **varios** apelidos ao mesmo projeto — neste caso
`nexus-architecture-buenno.vercel.app` e `nexus-architecture-one.vercel.app`, os dois
servindo a mesma aplicacao. **Settings -> Domains** mostra qual ela considera o de
producao, e nao e necessariamente o que voce usou primeiro.

Isso importa porque CORS compara a origem **exata**. Um apelido que serve o painel mas
nao esta na lista produz um painel que carrega e falha em todas as chamadas — e no
console o erro aponta para CORS, nao para "endereco faltando na lista".

```bash
AWS_PROFILE=... aws apigatewayv2 get-api --api-id <id> --region us-east-1 --query 'CorsConfiguration.AllowOrigins'
```

Confira contra a lista de Domains da Vercel sempre que adicionar ou trocar um endereco.

## 5. Dominio proprio (opcional)

**Nao exige Route 53.** Uma versao anterior deste documento dava a hosted zone
(US$ 0,50/mes) como custo inevitavel de ter dominio proprio — nao e. O DNS pode
continuar no registrador, e a Vercel emite o certificado TLS sozinha. Com dominio
proprio pela Vercel, o custo fixo continua **US$ 0,00**.

O projeto usa `mateus-bueno.dev`, com DNS no name.com.

1. Vercel: **Settings -> Domains -> Add**, informando `nexus.mateus-bueno.dev`. Ela
   devolve o alvo de CNAME.
2. No registrador: criar **CNAME** `nexus` apontando para esse alvo.
3. Esperar a propagacao. O certificado e emitido automaticamente.

```bash
dig +short CNAME nexus.mateus-bueno.dev && curl -s -o /dev/null -w "%{http_code}\n" https://nexus.mateus-bueno.dev
```

**A alteracao de DNS e sempre do dono da conta.** Este runbook descreve o passo; nao o
executa.

## 6. Corrigir a origem do CORS

A URL da Vercel so existe depois do passo 4, entao sao **dois applies**, nao um. Entre
eles, o painel nao fala com a API — o navegador recusa a resposta por origem.

`cors_allowed_origins` e uma **lista**, nao uma origem unica, e a razao e operacional:
com uma origem so, apontar para o dominio novo derrubaria o antigo no instante do
apply — e entre o apply e a propagacao do DNS nao haveria endereco nenhum funcionando.
Com a lista, os dois valem ao mesmo tempo e a troca nao tem janela cega.

```bash
cd infra/terraform && terraform plan -out=tfplan && terraform apply tfplan
```

O valor fica em `terraform.tfvars`, nunca em `-var` na linha de comando: o estado nao
deve depender de alguem lembrar da flag na proxima vez.

Curinga e recusado por validacao. Com `"*"`, qualquer pagina da internet chamaria a API
pelo navegador de quem a visita — e as rotas `/v1/ops/*` disparam trabalho.

## 7. Destruir

```bash
cd infra/terraform && terraform destroy
```

Procedimento de verificacao em dez categorias no [runbook-deploy.md](runbook-deploy.md).
A Vercel se apaga pelo painel dela.

## O nome do dominio

`nexus-architecture.vercel.app` **nao e deste projeto**. Subdominios `*.vercel.app` sao
globais e esse ja estava tomado por outra pessoa; a Vercel entao atribui o nome com o
sufixo da conta. O endereco publico e
`https://nexus-architecture-buenno.vercel.app`.

Confundir os dois nao e inofensivo: o CORS chegou a ser apontado para o dominio alheio
por alguns minutos. Nao houve exposicao — a API exige JWT em tudo menos `/health`, e
aquele site nao tinha token —, mas a configuracao estava errada.

Como confirmar de quem e um dominio antes de confiar nele:

```bash
curl -s https://nexus-architecture-buenno.vercel.app | grep -o '<title>[^<]*</title>'
```

O `<title>` do painel e `Nexus Control Center`. Se vier outra coisa, o dominio e de
outro projeto.

## Deployment Protection

Ligada por padrao. Com ela, o dominio responde `302` para `vercel.com/sso-api` e so
abre para quem esta logado na sua conta — um visitante bate na tela de login da Vercel.

Settings -> Deployment Protection -> Vercel Authentication -> Disabled.

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://nexus-architecture-buenno.vercel.app
```

`200` significa publico; `302` significa protegido.

## Defeitos encontrados neste deploy

**`USER_PASSWORD_AUTH` nao estava habilitado no client do Cognito.** O painel autentica
com esse flow; o login falharia com `USER_PASSWORD_AUTH flow not enabled for this
client`. Defeito latente desde a Fase 4, cujo relatorio registrava que o modo Cognito
tinha teste de componente e nunca fora exercitado contra a AWS.

Encontrado sondando com uma senha **deliberadamente errada**: `InvalidParameterException`
significa flow desabilitado, `NotAuthorizedException` significa que o flow funciona e a
senha e que esta errada. A distincao identifica o defeito sem usar a credencial real, e
serve como verificacao depois da correcao.


**As rotas de observabilidade nao existiam no API Gateway.** O mapa de rotas foi escrito
na Fase 3; a Fase 6 criou `/v1/observability/*` na aplicacao com a infraestrutura ja
destruida, entao o gateway nunca foi exercitado com elas. Os testes de integracao batem
no FastAPI direto, e `terraform validate` valida sintaxe, nao cobertura de rotas.

**`ANY` quebra o preflight de CORS.** `ANY /v1/ops/{proxy+}` casa tambem com `OPTIONS`,
entao o preflight do navegador cai no authorizer JWT — e navegador **nunca** envia
`Authorization` num preflight. Resposta `401`, preflight reprovado, requisicao real nem
sai. Com metodo explicito (`GET` e `POST` separados), `OPTIONS` nao casa com rota nenhuma
e o proprio API Gateway responde `204`.

Os dois aparecem no console como **erro de CORS**, o que manda investigar a configuracao
de CORS — que estava correta nas duas vezes. O sintoma aponta para o lugar errado.

A verificacao que distingue os casos:

```bash
API=https://1vsn0kmtx8.execute-api.us-east-1.amazonaws.com; for r in /v1/ops/queue /v1/resolution/stats /v1/observability/alerts; do printf "%-34s preflight %s | real %s\n" "$r" "$(curl -s -o /dev/null -w '%{http_code}' -X OPTIONS "$API$r" -H 'Origin: https://nexus-architecture-buenno.vercel.app' -H 'Access-Control-Request-Method: GET' -H 'Access-Control-Request-Headers: authorization')" "$(curl -s -o /dev/null -w '%{http_code}' "$API$r")"; done
```

Esperado: preflight `204` e real `401`. Preflight `401` e rota `ANY`; real `404` e rota
ausente.
