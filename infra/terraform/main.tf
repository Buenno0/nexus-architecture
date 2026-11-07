data "aws_caller_identity" "current" {}

locals {
  prefix = "${var.project_name}-${var.environment}"

  table_name = "${local.prefix}-records"
  queue_name = "${local.prefix}-queue"
  dlq_name   = "${local.prefix}-dlq"

  # Variaveis comuns a todas as funcoes. NEXUS_ENV=aws faz build_client ignorar o
  # endpoint local e usar a IAM Role — comportamento ja implementado na Fase 1.
  common_env = {
    NEXUS_ENV                              = "aws"
    NEXUS_LOG_LEVEL                        = "INFO"
    NEXUS_DYNAMO_TABLE                     = aws_dynamodb_table.records.name
    NEXUS_AWS_REGION                       = var.aws_region
    NEXUS_QUEUE_BACKEND                    = "sqs"
    NEXUS_SQS_QUEUE_URL                    = aws_sqs_queue.main.url
    NEXUS_SQS_DLQ_URL                      = aws_sqs_queue.dlq.url
    NEXUS_QUEUE_VISIBILITY_TIMEOUT_SECONDS = tostring(var.queue_visibility_timeout_seconds)
  }
}
