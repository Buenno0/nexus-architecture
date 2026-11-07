# Tres funcoes do mesmo pacote, com handlers diferentes. O zip vem de
# scripts/build_lambda.sh.

locals {
  handlers = {
    api        = "nexus.handlers.api.handler"
    dispatcher = "nexus.handlers.dispatcher.handler"
    worker     = "nexus.handlers.worker.handler"
  }
}

resource "aws_cloudwatch_log_group" "lambda" {
  for_each = local.handlers
  name     = "/aws/lambda/${local.prefix}-${each.key}"
  # Sem retencao os logs acumulam indefinidamente e saem da franquia em silencio.
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "this" {
  for_each = local.handlers

  function_name = "${local.prefix}-${each.key}"
  role          = aws_iam_role.lambda[each.key].arn
  handler       = each.value
  runtime       = "python3.13"
  architectures = ["arm64"] # Graviton: ~20% mais barato por GB-segundo

  filename         = var.lambda_zip_path
  source_code_hash = filebase64sha256(var.lambda_zip_path)

  memory_size = var.lambda_memory_mb
  timeout     = var.lambda_timeout_seconds

  # O freio principal contra fatura inesperada.
  reserved_concurrent_executions = var.lambda_reserved_concurrency

  environment {
    variables = merge(
      local.common_env,
      { NEXUS_SERVICE_NAME = "${local.prefix}-${each.key}" },
    )
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
}
