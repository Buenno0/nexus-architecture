output "api_endpoint" {
  description = "URL base da API. Use em NEXUS_API_URL no Control Center."
  value       = aws_apigatewayv2_api.main.api_endpoint
}

output "dynamodb_table" {
  value = aws_dynamodb_table.records.name
}

output "sqs_queue_url" {
  value = aws_sqs_queue.main.url
}

output "sqs_dlq_url" {
  value = aws_sqs_queue.dlq.url
}

output "cognito_user_pool_id" {
  value = aws_cognito_user_pool.main.id
}

output "cognito_client_id" {
  description = "Client ID publico do dashboard. Pode ir para o JavaScript — nao e segredo."
  value       = aws_cognito_user_pool_client.dashboard.id
}

output "lambda_functions" {
  description = "Nomes das funcoes, para invocacao manual pela CLI."
  value       = { for k, v in aws_lambda_function.this : k => v.function_name }
}

output "safety_net_enabled" {
  description = "Se false, nada processa sem acionamento explicito."
  value       = var.enable_safety_net
}

output "estimated_monthly_cost_usd" {
  description = <<-EOT
    Estimativa no volume previsto (~10.000 registros/mes). Ver COSTS.md.

    Nenhum recurso aqui tem custo fixo: a hosted zone do Route 53, unico custo fixo do
    projeto, NAO e criada por este Terraform.
  EOT
  value       = "~0.10 (DynamoDB On-Demand; demais servicos dentro da franquia)"
}
