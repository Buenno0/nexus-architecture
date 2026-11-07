# Autenticacao do Control Center.
#
# Uma SPA nao guarda segredo: qualquer chave embutida no JavaScript esta publica. Por
# isso a escolha e JWT via Cognito, e nao um segredo compartilhado.
#
# Franquia: 50.000 usuarios ativos por mes.

resource "aws_cognito_user_pool" "main" {
  name = "${local.prefix}-users"

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 3
  }

  admin_create_user_config {
    # Plataforma experimental: operadores sao criados por voce, nao por auto-cadastro.
    allow_admin_create_user_only = true
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }
}

resource "aws_cognito_user_pool_client" "dashboard" {
  name         = "${local.prefix}-dashboard"
  user_pool_id = aws_cognito_user_pool.main.id

  # Cliente publico: sem segredo, porque um navegador nao consegue proteger um.
  generate_secret = false

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  access_token_validity  = 1
  id_token_validity      = 1
  refresh_token_validity = 30

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "days"
  }

  prevent_user_existence_errors = "ENABLED"
}
