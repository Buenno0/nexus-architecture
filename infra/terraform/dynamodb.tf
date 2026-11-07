# Tabela unica, com os quatro indices de docs/architecture/access-patterns.md.
# O schema espelha src/nexus/persistence/tables.py — divergir faria o codigo local e a
# nuvem consultarem indices diferentes.

resource "aws_dynamodb_table" "records" {
  name         = local.table_name
  billing_mode = var.dynamodb_billing_mode
  hash_key     = "pk"
  range_key    = "sk"

  read_capacity  = var.dynamodb_billing_mode == "PROVISIONED" ? var.dynamodb_provisioned_capacity : null
  write_capacity = var.dynamodb_billing_mode == "PROVISIONED" ? var.dynamodb_provisioned_capacity : null

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
    read_capacity   = var.dynamodb_billing_mode == "PROVISIONED" ? var.dynamodb_provisioned_capacity : null
    write_capacity  = var.dynamodb_billing_mode == "PROVISIONED" ? var.dynamodb_provisioned_capacity : null
  }

  # Listagem cronologica: o ULID ordena por tempo de criacao (padrao 2).
  global_secondary_index {
    name            = "gsi_recency"
    hash_key        = "recency_pk"
    range_key       = "record_id"
    projection_type = "ALL"
    read_capacity   = var.dynamodb_billing_mode == "PROVISIONED" ? var.dynamodb_provisioned_capacity : null
    write_capacity  = var.dynamodb_billing_mode == "PROVISIONED" ? var.dynamodb_provisioned_capacity : null
  }

  # ESPARSO: pending_shard so existe enquanto o evento esta pendente (ADR-003).
  # KEYS_ONLY mantem o indice pequeno; o conteudo vem da tabela base.
  global_secondary_index {
    name            = "gsi_outbox_pending"
    hash_key        = "pending_shard"
    range_key       = "next_attempt_at"
    projection_type = "KEYS_ONLY"
    read_capacity   = var.dynamodb_billing_mode == "PROVISIONED" ? var.dynamodb_provisioned_capacity : null
    write_capacity  = var.dynamodb_billing_mode == "PROVISIONED" ? var.dynamodb_provisioned_capacity : null
  }

  # ESPARSO: review_shard so existe enquanto o par aguarda decisao (ADR-006).
  global_secondary_index {
    name            = "gsi_review"
    hash_key        = "review_shard"
    range_key       = "created_at"
    projection_type = "KEYS_ONLY"
    read_capacity   = var.dynamodb_billing_mode == "PROVISIONED" ? var.dynamodb_provisioned_capacity : null
    write_capacity  = var.dynamodb_billing_mode == "PROVISIONED" ? var.dynamodb_provisioned_capacity : null
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
