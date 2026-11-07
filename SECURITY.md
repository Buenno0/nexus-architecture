# Seguranca — Nexus Architecture

## Dados

**Todos os dados sao sinteticos.** Gerados por Faker. Nenhum dado pessoal real e
utilizado, armazenado ou processado em qualquer etapa do projeto.

Documentos, e-mails, telefones e nomes nao correspondem a pessoas reais. Qualquer
coincidencia com dados reais e acidental e os dados nao devem ser tratados como validos.

## Segredos

- Nenhuma credencial no codigo-fonte.
- `.env` esta no `.gitignore`; apenas `.env.example` e versionado.
- As credenciais no `.env.example` (`local` / `local`) sao valores falsos exigidos pelo
  SDK para falar com o DynamoDB Local. Nao sao segredos.
- Na AWS, credenciais vem de IAM Roles — nunca de chaves estaticas em variaveis de
  ambiente.

## Validacao de entrada

- Todo payload e validado por Pydantic na borda. Entrada invalida resulta em `422` e
  **nunca** alcanca a persistencia ou a fila.
- Limites explicitos de tamanho por campo e por corpo da requisicao.
- Campos de texto sao tratados como dados opacos; nao ha interpolacao em consultas.
- DynamoDB nao usa linguagem de consulta textual na escrita, o que elimina a classe de
  injecao tipica de SQL. Mesmo assim, campos de texto sao validados por tamanho e tipo.

## Superficie exposta

Fase 1: a API escuta apenas em `localhost` via Docker. Nada publicamente acessivel.

Fase 3 em diante:
- CORS restrito a origem do Control Center. Nunca `*`.
- IAM com privilegio minimo: cada Lambda recebe permissao apenas sobre a tabela e a fila
  que efetivamente usa.
- Sem VPC privada (evita NAT Gateway); isolamento via IAM, nao via rede.
- Rate limiting no API Gateway.

## Tratamento de erros

- Respostas de erro nao expoem stack traces, nomes de tabela, ARNs ou detalhes internos.
- Logs internos contem o detalhe completo; a resposta HTTP contem apenas o necessario.
- `correlation_id` e devolvido ao cliente para permitir rastreio sem vazar interno.

## Endpoints operacionais

As rotas `/v1/ops/*` disparam trabalho: publicam eventos, consomem a fila e devolvem
mensagens da DLQ. **Nao ha autenticacao nelas.**

Mitigacoes atuais:

- A API escuta apenas em `localhost` via Docker; nada publicamente acessivel.
- Todo lote tem teto rigido validado na borda (`limit`, `max_messages`).
- Nenhuma rota apaga dados: `redrive` devolve mensagens, nao as descarta.

**Antes de qualquer exposicao publica na Fase 3, estas rotas exigem autenticacao.**
Expostas sem protecao, permitiriam a terceiros consumir recurso a vontade.

## Resolucao de identidade

Fundir registros de pessoas distintas e, neste projeto, o erro de maior consequencia:
dados se misturam de forma dificil de detectar e de reverter.

Protecoes implementadas:

- **Tres faixas de decisao.** Duvida vai para revisao humana, nunca para fusao.
- **Guarda de campos minimos.** Um unico campo em comum nao funde, salvo identificador
  forte exato.
- **Teto de tamanho de cluster.** Fusao em cadeia e recusada e sinalizada.
- **Evidencia por vinculo.** Cada fusao guarda o par e o score campo a campo.
- **Medicao com gabarito.** Precisao e recall sao reportados separadamente, antes de
  qualquer ajuste de peso.

Limitacao: **nao ha operacao de desfazer fusao**. A evidencia permite localizar a aresta
culpada, mas reverte-la e manual.

## Operacoes destrutivas

- Nenhuma rota de exclusao em massa na Fase 1.
- Registros de origem sao imutaveis por design ([ADR-002](docs/adr/ADR-002-identidade-e-idempotencia.md)).
- Operacoes caras no Control Center exigem confirmacao e possuem teto rigido.

## Limitacoes conhecidas

- **Nao ha autenticacao.** A API e aberta dentro do ambiente local, incluindo as rotas
  operacionais. Autenticacao e requisito da Fase 3, antes de qualquer exposicao publica.
- **A injecao de falhas e controlada por variavel de ambiente**
  (`NEXUS_FAILURE_INJECTION_RATE`). Em qualquer ambiente real ela deve permanecer em
  zero; ativa-la descarta trabalho de proposito.
- Nao ha criptografia em repouso configurada explicitamente no DynamoDB Local.
- Nao ha auditoria de acesso.

Este projeto e experimental e **nao** deve ser tratado como sistema de producao.
