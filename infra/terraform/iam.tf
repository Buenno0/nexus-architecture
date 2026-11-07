# Privilegio minimo por funcao.
#
# Nenhuma politica usa "*" em Action ou Resource. Uma funcao unica com roteamento
# interno precisaria da uniao de todas as permissoes — e por isso que as tres Lambdas
# sao separadas.

locals {
  # A tabela e seus indices. Consultar um GSI exige permissao no ARN do indice,
  # nao apenas no da tabela — omitir isso e um erro comum que so aparece em runtime.
  table_resources = [
    aws_dynamodb_table.records.arn,
    "${aws_dynamodb_table.records.arn}/index/*",
  ]
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# Escrita de logs, restrita aos grupos deste projeto.
data "aws_iam_policy_document" "logs" {
  statement {
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.prefix}-*:*",
    ]
  }
}

# ------------------------------------------------------------------ funcao: api

data "aws_iam_policy_document" "api" {
  statement {
    sid    = "DadosDaPlataforma"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:Query",
      "dynamodb:TransactWriteItems",
    ]
    resources = local.table_resources
  }

  statement {
    sid    = "PublicarEConsultarFila"
    effect = "Allow"
    actions = [
      "sqs:SendMessage",
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes",
    ]
    # A API expoe /v1/ops/process e /v1/ops/redrive, entao precisa das duas filas.
    resources = [aws_sqs_queue.main.arn, aws_sqs_queue.dlq.arn]
  }
}

# ----------------------------------------------------------- funcao: dispatcher

data "aws_iam_policy_document" "dispatcher" {
  statement {
    sid    = "LerEMarcarOutbox"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:UpdateItem",
      "dynamodb:Query",
    ]
    resources = local.table_resources
  }

  statement {
    sid       = "PublicarNaFila"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.main.arn]
  }
}

# --------------------------------------------------------------- funcao: worker

data "aws_iam_policy_document" "worker" {
  statement {
    sid    = "ProcessarRegistros"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
      "dynamodb:TransactWriteItems",
    ]
    resources = local.table_resources
  }

  statement {
    sid    = "ConsumirFila"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes",
      # Necessario para dead_letter explicito: registro inexistente nao deve
      # consumir tentativas.
      "sqs:SendMessage",
    ]
    resources = [aws_sqs_queue.main.arn, aws_sqs_queue.dlq.arn]
  }
}

# ------------------------------------------------------------------ papeis

locals {
  functions = {
    api        = data.aws_iam_policy_document.api.json
    dispatcher = data.aws_iam_policy_document.dispatcher.json
    worker     = data.aws_iam_policy_document.worker.json
  }
}

resource "aws_iam_role" "lambda" {
  for_each           = local.functions
  name               = "${local.prefix}-${each.key}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "lambda" {
  for_each = local.functions
  name     = "${local.prefix}-${each.key}-policy"
  role     = aws_iam_role.lambda[each.key].id
  policy   = each.value
}

resource "aws_iam_role_policy" "logs" {
  for_each = local.functions
  name     = "${local.prefix}-${each.key}-logs"
  role     = aws_iam_role.lambda[each.key].id
  policy   = data.aws_iam_policy_document.logs.json
}
