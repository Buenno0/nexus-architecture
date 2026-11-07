# No SQS, quem conta entregas e move para a DLQ e o redrive_policy — nao a aplicacao.
# Essa diferenca em relacao a fila SQLite esta documentada no ADR-008.

resource "aws_sqs_queue" "dlq" {
  name                      = local.dlq_name
  message_retention_seconds = 1209600 # 14 dias, o maximo: tempo para investigar
}

resource "aws_sqs_queue" "main" {
  name                       = local.queue_name
  visibility_timeout_seconds = var.queue_visibility_timeout_seconds
  message_retention_seconds  = 345600 # 4 dias
  # Long polling reduz chamadas vazias e, com isso, custo.
  receive_wait_time_seconds = 10

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = var.queue_max_receive_count
  })
}

# Permite que o redrive devolva mensagens da DLQ para a fila principal.
resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  queue_url = aws_sqs_queue.dlq.id

  redrive_allow_policy = jsonencode({
    redrivePermission = "byQueue"
    sourceQueueArns   = [aws_sqs_queue.main.arn]
  })
}
