# Rede de seguranca.
#
# O acionamento normal e manual, pelo Control Center — e disso que a plataforma trata.
# Mas a garantia de retentativa da Fase 2 so vale se alguem consumir de novo: uma
# mensagem que falha quando ninguem esta olhando o dashboard ficaria parada
# indefinidamente.
#
# Este agendamento drena retentativas. NAO e event source mapping: continua sendo
# invocacao explicita, apenas disparada pelo relogio em vez do operador.
#
# Custo: ~2.880 invocacoes/mes a cada 15 minutos, dentro da franquia.

data "aws_iam_policy_document" "scheduler_assume" {
  count = var.enable_safety_net ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

data "aws_iam_policy_document" "scheduler_invoke" {
  count = var.enable_safety_net ? 1 : 0

  statement {
    effect  = "Allow"
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.this["dispatcher"].arn,
      aws_lambda_function.this["worker"].arn,
    ]
  }
}

resource "aws_iam_role" "scheduler" {
  count              = var.enable_safety_net ? 1 : 0
  name               = "${local.prefix}-scheduler-role"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume[0].json
}

resource "aws_iam_role_policy" "scheduler" {
  count  = var.enable_safety_net ? 1 : 0
  name   = "${local.prefix}-scheduler-policy"
  role   = aws_iam_role.scheduler[0].id
  policy = data.aws_iam_policy_document.scheduler_invoke[0].json
}

resource "aws_scheduler_schedule" "dispatcher" {
  count                        = var.enable_safety_net ? 1 : 0
  name                         = "${local.prefix}-dispatcher-safety-net"
  schedule_expression          = var.safety_net_schedule
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.this["dispatcher"].arn
    role_arn = aws_iam_role.scheduler[0].arn
    input    = jsonencode({ limit = 100 })

    retry_policy {
      maximum_retry_attempts = 1
    }
  }
}

resource "aws_scheduler_schedule" "worker" {
  count                        = var.enable_safety_net ? 1 : 0
  name                         = "${local.prefix}-worker-safety-net"
  schedule_expression          = var.safety_net_schedule
  schedule_expression_timezone = "UTC"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.this["worker"].arn
    role_arn = aws_iam_role.scheduler[0].arn
    # Teto de lotes: a Lambda tem tempo limitado e um laco sem fim seria cortado
    # no meio, deixando mensagens em voo ate expirarem.
    input = jsonencode({ max_messages = 10, max_batches = 5 })

    retry_policy {
      maximum_retry_attempts = 1
    }
  }
}
