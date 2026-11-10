# Dois alertas, nao um.
#
# O primeiro avisa cedo. O segundo existe porque o primeiro pode passar despercebido —
# e a diferenca entre descobrir no dia seguinte e descobrir na fatura.

# A tag precisa estar ATIVADA para alocacao de custo, senao o cost_filter abaixo nao
# casa com nada e o budget nunca dispara.
#
# Descoberto ao medir o custo real do deploy de 07/11/2026: a consulta filtrada por
# tag devolvia US$ 0,00 nao porque nao houve gasto, mas porque nenhuma tag estava
# ativada. O budget teria ficado silencioso diante de qualquer valor.
#
# Duas ressalvas da AWS:
#   1. A ativacao leva ate 24 horas para refletir no Cost Explorer.
#   2. Vale apenas para uso POSTERIOR a ativacao — gasto anterior nao e reclassificado.
#
# Ou seja: no primeiro dia o budget ainda nao protege. Por isso tambem existe o alerta
# por PREVISAO mais abaixo, que nao depende de historico acumulado.
resource "aws_ce_cost_allocation_tag" "project" {
  tag_key = "Project"
  status  = "Active"
}

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

  # Sem a tag ativada, o filtro acima nao casa com nada.
  depends_on = [aws_ce_cost_allocation_tag.project]

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
