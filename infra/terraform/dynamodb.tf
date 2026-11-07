# Tabela unica, com os quatro indices de docs/architecture/access-patterns.md.
# O schema espelha src/nexus/persistence/tables.py — divergir faria o codigo local e a
# nuvem consultarem indices diferentes.

locals {
  # A franquia gratuita do DynamoDB e de 25 RCU e 25 WCU POR CONTA, somando a tabela e
  # TODOS os indices. Nao e 25 por recurso.
  #
  # Com 1 tabela + 4 GSIs, provisionar 25 em cada daria 125/125 — 100 unidades acima da
  # franquia, a US$ 0,00065/WCU-hora e US$ 0,00013/RCU-hora: US$ 56,94 por mes, para
  # uma plataforma cuja alternativa On-Demand custa US$ 0,08.
  #
  # Por isso a variavel e um orcamento TOTAL, dividido aqui.
  dynamodb_components = 5 # a tabela + gsi_natural + gsi_recency + gsi_outbox_pending + gsi_review
  dynamodb_capacity_each = var.dynamodb_billing_mode == "PROVISIONED" ? floor(
    var.dynamodb_provisioned_capacity / local.dynamodb_components
  ) : null
}

resource "aws_dynamodb_table" "records" {
  name         = local.table_name
  billing_mode = var.dynamodb_billing_mode
  hash_key     = "pk"
  range_key    = "sk"

  read_capacity  = local.dynamodb_capacity_each
  write_capacity = local.dynamodb_capacity_each

  # Apenas atributos usados em chaves. O DynamoDB nao impoe schema fora delas, e
  # declarar um atributo sem usa-lo em chave e erro de validacao.
  attribute {
    name = "pk"
    type = "S"
  }
  attribute {
    name = "sk"
    type = "S"
  }
  attribute {
    name = "natural_key"
    type = "S"
  }
  attribute {
    name = "record_fingerprint"
    type = "S"
  }
  attribute {
    name = "recency_pk"
    type = "S"
  }
  attribute {
    name = "record_id"
    type = "S"
  }
  attribute {
    name = "pending_shard"
    type = "S"
  }
  attribute {
    name = "next_attempt_at"
    type = "S"
  }
  attribute {
    name = "review_shard"
    type = "S"
  }
  attribute {
    name = "created_at"
    type = "S"
  }

  # Observacoes da mesma entidade candidata (padroes 3 e 4).
  global_secondary_index {
    name            = "gsi_natural"
    hash_key        = "natural_key"
    range_key       = "record_fingerprint"
    projection_type = "ALL"
    read_capacity   = local.dynamodb_capacity_each
    write_capacity  = local.dynamodb_capacity_each
  }

  # Listagem cronologica: o ULID ordena por tempo de criacao (padrao 2).
  global_secondary_index {
    name            = "gsi_recency"
    hash_key        = "recency_pk"
    range_key       = "record_id"
    projection_type = "ALL"
    read_capacity   = local.dynamodb_capacity_each
    write_capacity  = local.dynamodb_capacity_each
  }

  # ESPARSO: pending_shard so existe enquanto o evento esta pendente (ADR-003).
  # KEYS_ONLY mantem o indice pequeno; o conteudo vem da tabela base.
  global_secondary_index {
    name            = "gsi_outbox_pending"
    hash_key        = "pending_shard"
    range_key       = "next_attempt_at"
    projection_type = "KEYS_ONLY"
    read_capacity   = local.dynamodb_capacity_each
    write_capacity  = local.dynamodb_capacity_each
  }

  # ESPARSO: review_shard so existe enquanto o par aguarda decisao (ADR-006).
  global_secondary_index {
    name            = "gsi_review"
    hash_key        = "review_shard"
    range_key       = "created_at"
    projection_type = "KEYS_ONLY"
    read_capacity   = local.dynamodb_capacity_each
    write_capacity  = local.dynamodb_capacity_each
  }

  # Registros de idempotencia sao a unica classe de item cujo valor e temporario.
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = false # dados sinteticos; backup seria custo sem beneficio
  }
}
