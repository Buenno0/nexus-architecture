# Dois alertas, nao um.
#
# O primeiro avisa cedo. O segundo existe porque o primeiro pode passar despercebido —
# e a diferenca entre descobrir no dia seguinte e descobrir na fatura.

resource "aws_budgets_budget" "monthly" {
  name         = "${local.prefix}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.budget_hard_alert_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Project$nexus-architecture"]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = var.budget_alert_usd
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_notification_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = var.budget_hard_alert_usd
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_notification_email]
  }

  # Alerta tambem sobre a PREVISAO: avisa antes de o dinheiro ser gasto, nao depois.
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = var.budget_hard_alert_usd
    threshold_type             = "ABSOLUTE_VALUE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_notification_email]
  }
}
