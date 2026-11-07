variable "aws_region" {
  description = "Regiao da AWS. us-east-1 concentra as franquias gratuitas mais amplas."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Identificador do ambiente, usado como sufixo nos nomes."
  type        = string
  default     = "dev"
}

variable "project_name" {
  description = "Prefixo dos recursos."
  type        = string
  default     = "nexus"
}

variable "dynamodb_billing_mode" {
  description = <<-EOT
    PAY_PER_REQUEST (On-Demand) ou PROVISIONED.

    On-Demand cobra por requisicao e NAO tem franquia gratuita: ~US$ 0,15 por 10.000
    registros. PROVISIONED com 25 WCU/RCU fica integralmente na franquia permanente
    (custo zero), mas estrangula acima de 25 escritas por segundo — o que inviabiliza
    os testes de carga da Fase 7.

    Ver COSTS.md.
  EOT
  type        = string
  default     = "PAY_PER_REQUEST"

  validation {
    condition     = contains(["PAY_PER_REQUEST", "PROVISIONED"], var.dynamodb_billing_mode)
    error_message = "Use PAY_PER_REQUEST ou PROVISIONED."
  }
}

variable "dynamodb_provisioned_capacity" {
  description = "WCU/RCU quando PROVISIONED. 25 e o teto da franquia gratuita."
  type        = number
  default     = 25
}

variable "queue_max_receive_count" {
  description = "Entregas antes de a mensagem ir para a DLQ. No SQS, quem decide e o redrive_policy."
  type        = number
  default     = 3
}

variable "queue_visibility_timeout_seconds" {
  description = "Tempo que a mensagem fica invisivel apos ser entregue."
  type        = number
  default     = 30
}

variable "lambda_zip_path" {
  description = "Pacote gerado por scripts/build_lambda.sh."
  type        = string
  default     = "../../dist/nexus-lambda.zip"
}

variable "lambda_memory_mb" {
  description = "Memoria por funcao. Na Lambda, memoria e CPU andam juntas."
  type        = number
  default     = 512
}

variable "lambda_timeout_seconds" {
  description = "Timeout curto e protecao de custo: uma funcao em laco custa dinheiro real."
  type        = number
  default     = 30
}

variable "lambda_reserved_concurrency" {
  description = <<-EOT
    Concorrencia reservada por funcao. E o principal freio contra fatura inesperada:
    sem teto, uma rajada de requisicoes vira invocacoes paralelas sem limite.
  EOT
  type        = number
  default     = 5
}

variable "log_retention_days" {
  description = "Retencao no CloudWatch. Sem retencao, os logs acumulam indefinidamente."
  type        = number
  default     = 7
}

variable "budget_alert_usd" {
  description = "Primeiro alerta de orcamento."
  type        = number
  default     = 5
}

variable "budget_hard_alert_usd" {
  description = "Segundo alerta, para o caso de o primeiro passar despercebido."
  type        = number
  default     = 10
}

variable "budget_notification_email" {
  description = "E-mail que recebe os alertas de orcamento. Obrigatorio."
  type        = string
}

variable "cors_allowed_origin" {
  description = "Origem do Control Center. Nunca use '*' com credenciais."
  type        = string
  default     = "https://nexus.mateus-bueno.dev"
}

variable "safety_net_schedule" {
  description = <<-EOT
    Expressao do EventBridge Scheduler para a rede de seguranca.

    O acionamento normal e manual, pelo Control Center. Este agendamento existe para
    drenar retentativas quando ninguem esta olhando o dashboard — sem ele, a garantia
    de retentativa da Fase 2 so vale enquanto alguem clica.
  EOT
  type        = string
  default     = "rate(15 minutes)"
}

variable "enable_safety_net" {
  description = "Desligue para uma demonstracao estritamente sob demanda."
  type        = bool
  default     = true
}
