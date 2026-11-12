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
    # Exigido pelo painel, que autentica com InitiateAuth do SDK v3.
    #
    # Sem este flow o login responde "USER_PASSWORD_AUTH flow not enabled for this
    # client" e o dashboard nunca entra. Era um defeito latente desde a Fase 4: o modo
    # Cognito tinha teste de componente e nunca foi exercitado contra a AWS, e o
    # relatorio daquela fase registrava isso como limitacao conhecida. Apareceu no
    # primeiro deploy que tentou usa-lo.
    #
    # Troca aceita: SRP nao envia a senha, este flow envia (sob TLS). O SDK v3 nao
    # implementa SRP — exigiria amazon-cognito-identity-js e mais bundle. Para uma
    # conta de convidado cuja senha e publica por construcao, a diferenca e nenhuma;
    # para um operador real, SRP seria preferivel.
    "ALLOW_USER_PASSWORD_AUTH",
    # Fluxo iniciado por administrador: exige credenciais AWS com
    # cognito-idp:AdminInitiateAuth para ser usado, alem da senha do usuario. Nao e
    # superficie publica — serve para script de verificacao e automacao do operador.
    "ALLOW_ADMIN_USER_PASSWORD_AUTH",
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

# ---------------------------------------------------------------- demonstracao

# Convidado da demonstracao publica.
#
# A senha deste usuario viaja no bundle JavaScript, para que o visitante nao veja tela
# de login. Isso nao e descuido: uma SPA nao guarda segredo, como o comentario no topo
# deste arquivo ja dizia, e fingir o contrario seria pior do que assumir.
#
# A consequencia precisa ser levada a serio: qualquer pessoa extrai o token e chama a
# API direto, sem passar pela interface. Portanto **a interface nao e uma protecao**.
# O que protege e, nesta ordem:
#
#   1. As rotas de ingestao livre nao existem no roteamento (apigateway.tf).
#   2. Os tetos por chamada e acumulado sao avaliados no servidor.
#   3. O throttle do stage limita a taxa.
#   4. O convidado nao recebe nenhuma credencial da AWS — apenas um JWT que o
#      API Gateway aceita. Nao ha identity pool, entao nao ha acesso a servicos.
resource "aws_cognito_user" "guest" {
  count = var.demo_mode ? 1 : 0

  user_pool_id = aws_cognito_user_pool.main.id
  username     = var.demo_guest_username
  password     = var.demo_guest_password

  # Sem e-mail e sem convite: este usuario nao pertence a ninguem.
  message_action = "SUPPRESS"

  lifecycle {
    precondition {
      condition     = length(var.demo_guest_password) >= 12
      error_message = "demo_mode exige demo_guest_password com no minimo 12 caracteres (politica do pool: maiuscula, minuscula, numero e simbolo)."
    }
  }
}
