# HTTP API: mais barato e mais simples que REST API, e suficiente aqui.

resource "aws_apigatewayv2_api" "main" {
  name          = "${local.prefix}-api"
  protocol_type = "HTTP"

  cors_configuration {
    # Nunca "*": a origem e exatamente a do Control Center.
    allow_origins     = [var.cors_allowed_origin]
    allow_methods     = ["GET", "POST", "OPTIONS"]
    allow_headers     = ["content-type", "authorization", "idempotency-key", "x-correlation-id"]
    expose_headers    = ["x-correlation-id", "idempotency-replayed"]
    allow_credentials = false
    max_age           = 300
  }
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.main.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.this["api"].invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = var.lambda_timeout_seconds * 1000
}

resource "aws_apigatewayv2_authorizer" "jwt" {
  api_id           = aws_apigatewayv2_api.main.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "${local.prefix}-jwt"

  jwt_configuration {
    audience = [aws_cognito_user_pool_client.dashboard.id]
    issuer   = "https://${aws_cognito_user_pool.main.endpoint}"
  }
}

locals {
  # /health fica aberto: um health check que exige token nao serve para monitoramento
  # externo, e ele nao revela nada alem de estar no ar.
  public_routes = {
    health = "GET /health"
  }

  # Todo o resto exige token. Inclui /v1/ops/*, que dispara trabalho, e as rotas de
  # consulta, que leem dados.
  base_routes = {
    get_record   = "GET /v1/records/{record_id}"
    list_records = "GET /v1/records"
    metrics      = "GET /metrics"
    # Metodo explicito, nunca ANY — e a diferenca entre o painel funcionar e nao.
    #
    # `ANY /v1/ops/{proxy+}` casa tambem com OPTIONS. O preflight do navegador passa
    # a cair no authorizer JWT, e navegador **nunca** envia Authorization num
    # preflight: a resposta e 401, o preflight reprova e a requisicao real nem sai.
    # No console aparece como erro de CORS, o que manda investigar a configuracao de
    # CORS — que esta correta. O problema e a rota.
    #
    # Com metodo explicito, OPTIONS nao casa com rota nenhuma e o proprio API Gateway
    # responde o preflight com 204, que e como `GET /v1/records` sempre funcionou.
    #
    # Encontrado em 12/11/2026, na primeira vez que o painel falou com o gateway.
    ops_read  = "GET /v1/ops/{proxy+}"
    ops_write = "POST /v1/ops/{proxy+}"
    res_read  = "GET /v1/resolution/{proxy+}"
    res_write = "POST /v1/resolution/{proxy+}"

    # Fase 6, ausente ate 12/11/2026. O mapa foi escrito na Fase 3; a Fase 6 criou as
    # rotas na aplicacao com a infraestrutura ja destruida, entao o gateway nunca foi
    # exercitado com elas. Os testes de integracao batem no FastAPI direto, e
    # `terraform validate` valida sintaxe, nao cobertura de rotas.
    observability = "GET /v1/observability/{proxy+}"
  }

  # Ingestao livre: o cliente escolhe o CONTEUDO do registro.
  #
  # Fora do roteamento na demonstracao publica. Nao e questao de autenticacao — o
  # convidado tem token valido —, e de superficie: uma rota alcancavel pela internet
  # que aceita texto arbitrario grava o que qualquer pessoa quiser no painel que serve
  # de portfolio. Retirar a rota e mais forte que validar o conteudo, porque nao
  # depende de eu ter previsto o que filtrar.
  ingest_routes = {
    ingest_person = "POST /v1/records/person"
    ingest_org    = "POST /v1/records/organization"
  }

  # Semeadura: o cliente escolhe QUANTOS registros, nunca o que eles dizem.
  demo_routes = {
    demo_seed = "POST /v1/demo/seed"
  }

  protected_routes = merge(
    local.base_routes,
    var.demo_mode ? local.demo_routes : local.ingest_routes,
  )
}

resource "aws_apigatewayv2_route" "public" {
  for_each  = local.public_routes
  api_id    = aws_apigatewayv2_api.main.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_route" "protected" {
  for_each           = local.protected_routes
  api_id             = aws_apigatewayv2_api.main.id
  route_key          = each.value
  target             = "integrations/${aws_apigatewayv2_integration.api.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.main.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    # Teto de taxa: protege contra rajada acidental virar fatura.
    throttling_burst_limit = 20
    throttling_rate_limit  = 10
  }

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access.arn
    format = jsonencode({
      requestId     = "$context.requestId"
      ip            = "$context.identity.sourceIp"
      method        = "$context.httpMethod"
      path          = "$context.path"
      status        = "$context.status"
      latency       = "$context.responseLatency"
      correlationId = "$context.authorizer.error"
    })
  }
}

resource "aws_cloudwatch_log_group" "api_access" {
  name              = "/aws/apigateway/${local.prefix}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.this["api"].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.main.execution_arn}/*/*"
}
