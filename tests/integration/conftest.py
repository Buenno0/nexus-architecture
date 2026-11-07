"""Fixtures de integracao.

Cada teste recebe uma **tabela propria**, criada e destruida no escopo do caso. Isso
custa alguns milissegundos e elimina a classe de falha mais corrosiva em suite de
integracao: teste que passa isolado e falha em conjunto por residuo de outro.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

import pytest
from botocore.exceptions import BotoCoreError, ClientError

from nexus.persistence.dynamo import DynamoRecordRepository
from nexus.persistence.tables import build_client, ensure_table, wait_for_dynamodb
from nexus.shared.config import Settings

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def dynamo_available() -> bool:
    """Falha cedo e com mensagem clara se o DynamoDB Local nao estiver no ar."""
    from tests.conftest import DYNAMO_ENDPOINT

    probe = Settings(env="local", dynamo_endpoint=DYNAMO_ENDPOINT, dynamo_table="probe")
    try:
        wait_for_dynamodb(build_client(probe), timeout_seconds=5)
    except (TimeoutError, ClientError, BotoCoreError):
        pytest.skip(
            "DynamoDB Local indisponivel. Execute 'make up' ou "
            "'docker compose up -d dynamodb' antes dos testes de integracao."
        )
    return True


@pytest.fixture
def repository(settings: Settings, dynamo_available: bool) -> Iterator[DynamoRecordRepository]:
    client = build_client(settings)
    ensure_table(client, settings)
    try:
        yield DynamoRecordRepository(client, settings)
    finally:
        with contextlib.suppress(ClientError, BotoCoreError):
            client.delete_table(TableName=settings.dynamo_table)
