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

    PAY_PER_REQUEST e o padrao e quase sempre a resposta certa aqui: ~US$ 0,08 por
    10.000 registros, sem teto de throughput.

    PROVISIONED so faz sentido se o total couber na franquia gratuita, e a franquia
    e de 25 RCU e 25 WCU **POR CONTA, somando a tabela e TODOS os indices**. Esta
    tabela tem 4 GSIs, entao sao 5 componentes dividindo as mesmas 25 unidades.

    Provisionar 25 em cada componente daria 125/125 — 100 acima da franquia, o que
    custa US$ 56,94/mes. Por isso a capacidade aqui e um ORCAMENTO TOTAL, dividido
    automaticamente (ver dynamodb.tf), e nao a capacidade de cada componente.

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
  description = <<-EOT
    Orcamento TOTAL de WCU/RCU quando PROVISIONED, dividido entre a tabela e os 4 GSIs.

    NAO e a capacidade de cada componente. 25 e o teto da franquia gratuita por conta;
    dividido por 5 componentes, da 5 unidades para cada — cerca de 5 escritas por
    segundo, suficiente para demonstrar e insuficiente para teste de carga.

    Acima de 25 o custo e US$ 0,00065 por WCU-hora e US$ 0,00013 por RCU-hora, ou seja
    ~US$ 0,57 por unidade excedente por mes.
  EOT
  type        = number
  default     = 25

  validation {
    condition     = var.dynamodb_provisioned_capacity >= 5
    error_message = "Minimo de 5 unidades no total (1 por componente)."
  }
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
    Concorrencia reservada por funcao, ou -1 para nao reservar.

    Reservar e o freio preferido contra fatura inesperada: sem teto, uma rajada vira
    invocacoes paralelas sem limite.

    PORENM: a AWS exige que sobrem no minimo 10 execucoes NAO reservadas na conta.
    Contas novas tem cota total de 10, entao qualquer reserva e recusada com
    "decreases account's UnreservedConcurrentExecution below its minimum value of 10".

    Nesse caso use -1. A protecao nao desaparece: a propria cota da conta passa a ser
    o teto, e 10 execucoes simultaneas e um limite bem mais apertado do que qualquer
    reserva que definiriamos. Ao elevar a cota (Service Quotas, "Concurrent
    executions"), volte a reservar por funcao.
  EOT
  type        = number
  default     = -1

  validation {
    condition     = var.lambda_reserved_concurrency == -1 || var.lambda_reserved_concurrency >= 1
    error_message = "Use -1 para nao reservar, ou um inteiro positivo."
  }
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

# ------------------------------------------------------------------ demonstracao

variable "demo_mode" {
  description = <<-EOT
    Liga a demonstracao publica.

    Com ela ligada, as rotas de ingestao livre (POST /v1/records/*) SAEM do roteamento
    do API Gateway e a unica entrada e POST /v1/demo/seed, que gera no servidor.

    A razao nao e economia de codigo. Uma rota de ingestao alcancavel pela internet
    aceita o conteudo que qualquer pessoa queira gravar, e esse conteudo aparece no
    painel que serve de portfolio. O visitante escolhe quantos registros, nunca o que
    eles dizem.
  EOT
  type        = bool
  default     = false
}

variable "demo_max_per_call" {
  description = "Teto de registros por chamada de semeadura. Limite de fatura: a escrita no DynamoDB e linear no volume."
  type        = number
  default     = 200

  validation {
    condition     = var.demo_max_per_call >= 1 && var.demo_max_per_call <= 1000
    error_message = "Entre 1 e 1000."
  }
}

variable "demo_max_total" {
  description = <<-EOT
    Teto ACUMULADO de registros que a demonstracao pode criar.

    O teto por chamada nao limita nada sozinho: basta chamar de novo. Com ~12 WRU por
    registro a US$ 0,625 por milhao, 5.000 registros custam cerca de US$ 0,04 — este
    numero e o pior caso de abuso, em dinheiro.
  EOT
  type        = number
  default     = 5000
}

variable "demo_guest_username" {
  description = "Usuario de convidado da demonstracao."
  type        = string
  default     = "convidado"
}

variable "demo_guest_password" {
  description = <<-EOT
    Senha do convidado. Obrigatoria quando demo_mode = true.

    **Esta credencial e publica por construcao**: ela viaja no bundle JavaScript para
    que o visitante nao veja tela de login, e uma SPA nao guarda segredo (ver
    cognito.tf). Marcar como sensitive evita que ela apareca em log do Terraform, nao
    que ela seja secreta.

    O que protege a plataforma nao e esta senha: sao os tetos do servidor, o throttle
    do API Gateway e o fato de o convidado nao receber nenhuma credencial da AWS.
  EOT
  type        = string
  default     = ""
  sensitive   = true
}
