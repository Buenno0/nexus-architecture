"""Fixtures de integracao.

Cada teste recebe uma **tabela propria**, criada e destruida no escopo do caso. Isso
custa alguns milissegundos e elimina a classe de falha mais corrosiva em suite de
integracao: teste que passa isolado e falha em conjunto por residuo de outro.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator

import pytest
from botocore.exceptions import BotoCoreError, ClientError

from nexus.persistence.dynamo import DynamoRecordRepository
from nexus.persistence.tables import build_client, ensure_table, wait_for_dynamodb
from nexus.shared.config import Settings

pytestmark = pytest.mark.integration


#: Transforma a ausencia do DynamoDB Local em falha, nao em teste pulado.
#:
#: Pular e o comportamento certo na maquina de quem desenvolve: quem roda a suite
#: inteira sem Docker no ar quer o retorno dos testes unitarios, nao um erro.
#:
#: No CI e o oposto, e a diferenca e perigosa: se o servico nao subir, a suite de
#: integracao inteira pula em silencio e o pipeline fica verde sem ter exercitado
#: nenhuma transacao, nenhum indice esparso e nenhuma escrita condicional. Um CI que
#: passa sem testar e pior que CI nenhum, porque gera confianca que nao corresponde
#: a nada. Fase 8.
REQUIRE_DYNAMO = os.environ.get("NEXUS_TEST_REQUIRE_DYNAMO", "").lower() in {"1", "true", "yes"}


@pytest.fixture(scope="session")
def dynamo_available() -> bool:
    """Falha cedo e com mensagem clara se o DynamoDB Local nao estiver no ar."""
    from tests.conftest import DYNAMO_ENDPOINT

    probe = Settings(env="local", dynamo_endpoint=DYNAMO_ENDPOINT, dynamo_table="probe")
    try:
        wait_for_dynamodb(build_client(probe), timeout_seconds=5)
    except (TimeoutError, ClientError, BotoCoreError) as exc:
        recado = (
            f"DynamoDB Local indisponivel em {DYNAMO_ENDPOINT}. Execute 'make up' ou "
            "'docker compose up -d dynamodb' antes dos testes de integracao."
        )
        if REQUIRE_DYNAMO:
            pytest.fail(f"{recado} NEXUS_TEST_REQUIRE_DYNAMO esta ligado: {exc}", pytrace=False)
        pytest.skip(recado)
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
