"""Definicao e criacao da tabela single-table.

Executavel como modulo (``python -m nexus.persistence.tables``): aguarda o DynamoDB
ficar disponivel e cria a tabela de forma idempotente. Usado pelo ``docker compose``
antes de subir a API.

A definicao de indices deriva de ``docs/architecture/access-patterns.md``.
"""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING, Any

import boto3
from botocore.exceptions import ClientError, EndpointConnectionError

from nexus.shared.config import Settings, get_settings
from nexus.shared.logging import configure_logging, get_logger

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.client import DynamoDBClient

logger = get_logger(__name__)

GSI_NATURAL = "gsi_natural"
GSI_RECENCY = "gsi_recency"
GSI_OUTBOX_PENDING = "gsi_outbox_pending"

TTL_ATTRIBUTE = "expires_at"

#: Credencial falsa do ambiente local. Nao e segredo — ver SECURITY.md.
LOCAL_FAKE_CREDENTIAL = "local"


def build_client(settings: Settings | None = None) -> DynamoDBClient:
    """Cria um cliente DynamoDB apontado para o ambiente configurado.

    No ambiente local, credenciais fixas e falsas sao passadas explicitamente. Isso tem
    duas razoes:

    1. O DynamoDB Local exige credenciais sintaticamente validas, mas nao as verifica.
    2. **Impede que o ambiente local alcance a AWS real por acidente.** Sem credenciais
       explicitas, o SDK procuraria perfis em ``~/.aws`` e variaveis de ambiente — e uma
       configuracao errada de endpoint escreveria numa conta real.

    Com ``NEXUS_ENV=aws``, nenhuma credencial e passada: o SDK resolve a cadeia padrao e
    usa a IAM Role da Lambda, conforme SECURITY.md.
    """
    settings = settings or get_settings()
    kwargs: dict[str, Any] = {"region_name": settings.aws_region}
    if not settings.is_aws:
        if settings.dynamo_endpoint:
            kwargs["endpoint_url"] = settings.dynamo_endpoint
        kwargs["aws_access_key_id"] = LOCAL_FAKE_CREDENTIAL
        kwargs["aws_secret_access_key"] = LOCAL_FAKE_CREDENTIAL
    client: DynamoDBClient = boto3.client("dynamodb", **kwargs)
    return client


def table_definition(table_name: str) -> dict[str, Any]:
    """Schema da tabela. On-Demand (PAY_PER_REQUEST) — ver COSTS.md."""
    return {
        "TableName": table_name,
        "BillingMode": "PAY_PER_REQUEST",
        "KeySchema": [
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        # Apenas atributos usados em chaves sao declarados. Os demais sao livres:
        # DynamoDB nao impoe schema fora das chaves.
        "AttributeDefinitions": [
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
            {"AttributeName": "natural_key", "AttributeType": "S"},
            {"AttributeName": "record_fingerprint", "AttributeType": "S"},
            {"AttributeName": "recency_pk", "AttributeType": "S"},
            {"AttributeName": "record_id", "AttributeType": "S"},
            {"AttributeName": "pending_shard", "AttributeType": "S"},
            {"AttributeName": "next_attempt_at", "AttributeType": "S"},
        ],
        "GlobalSecondaryIndexes": [
            {
                # Padroes 3 e 4: observacoes da mesma entidade candidata.
                "IndexName": GSI_NATURAL,
                "KeySchema": [
                    {"AttributeName": "natural_key", "KeyType": "HASH"},
                    {"AttributeName": "record_fingerprint", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                # Padrao 2: listagem cronologica. ULID ordena por tempo de criacao.
                "IndexName": GSI_RECENCY,
                "KeySchema": [
                    {"AttributeName": "recency_pk", "KeyType": "HASH"},
                    {"AttributeName": "record_id", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            },
            {
                # Padrao 6: outbox pendente. ESPARSO — ver ADR-003.
                # KEYS_ONLY mantem o indice pequeno; o conteudo vem da tabela base.
                "IndexName": GSI_OUTBOX_PENDING,
                "KeySchema": [
                    {"AttributeName": "pending_shard", "KeyType": "HASH"},
                    {"AttributeName": "next_attempt_at", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "KEYS_ONLY"},
            },
        ],
    }


def wait_for_dynamodb(client: DynamoDBClient, *, timeout_seconds: float = 60.0) -> None:
    """Aguarda o DynamoDB aceitar conexoes.

    O container do DynamoDB Local responde na porta antes de estar pronto para servir;
    por isso a espera verifica uma operacao real, nao apenas o socket.
    """
    deadline = time.monotonic() + timeout_seconds
    attempt = 0
    while True:
        attempt += 1
        try:
            client.list_tables(Limit=1)
            logger.info("dynamodb_ready", extra={"attempts": attempt})
            return
        except (EndpointConnectionError, ClientError) as exc:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"DynamoDB nao respondeu em {timeout_seconds}s apos {attempt} tentativas"
                ) from exc
            time.sleep(1.0)


def ensure_table(client: DynamoDBClient | None = None, settings: Settings | None = None) -> str:
    """Cria a tabela se nao existir. Idempotente.

    Devolve o nome da tabela.
    """
    settings = settings or get_settings()
    client = client or build_client(settings)
    table_name = settings.dynamo_table

    try:
        client.describe_table(TableName=table_name)
        logger.info("table_already_exists", extra={"table": table_name})
        return table_name
    except client.exceptions.ResourceNotFoundException:
        pass

    logger.info("creating_table", extra={"table": table_name})
    try:
        client.create_table(**table_definition(table_name))
    except client.exceptions.ResourceInUseException:
        # Corrida entre processos subindo ao mesmo tempo: a tabela ja foi criada.
        logger.info("table_created_concurrently", extra={"table": table_name})
        return table_name

    client.get_waiter("table_exists").wait(
        TableName=table_name, WaiterConfig={"Delay": 1, "MaxAttempts": 30}
    )

    # TTL so pode ser habilitado depois que a tabela esta ACTIVE.
    # Nao suportado por todas as versoes do DynamoDB Local — falha e tolerada.
    try:
        client.update_time_to_live(
            TableName=table_name,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": TTL_ATTRIBUTE},
        )
        logger.info("ttl_enabled", extra={"table": table_name, "attribute": TTL_ATTRIBUTE})
    except ClientError as exc:
        logger.warning(
            "ttl_not_enabled",
            extra={"table": table_name, "reason": str(exc)},
        )

    logger.info("table_created", extra={"table": table_name})
    return table_name


def main() -> int:
    settings = get_settings()
    configure_logging(settings.log_level, "nexus-tables")
    client = build_client(settings)
    try:
        wait_for_dynamodb(client)
        ensure_table(client, settings)
    except Exception as exc:
        logger.error("table_setup_failed", extra={"reason": str(exc)})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
