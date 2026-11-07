"""Fixtures compartilhadas.

Testes unitarios nao tocam em Docker nem em rede: usam o repositorio falso em
``tests/fakes.py``. Testes de integracao criam uma tabela propria no DynamoDB Local e a
destroem ao final, garantindo isolamento real entre casos.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

# Credenciais falsas antes de qualquer importacao de boto3.
os.environ.setdefault("AWS_ACCESS_KEY_ID", "local")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "local")

from nexus.observability.metrics import registry
from nexus.shared.config import Settings
from nexus.shared.logging import set_correlation_id

DYNAMO_ENDPOINT = os.environ.get("NEXUS_TEST_DYNAMO_ENDPOINT", "http://localhost:8000")


@pytest.fixture(autouse=True)
def _isolated_metrics() -> Iterator[None]:
    """Metricas sao estado global do processo: zerar entre testes evita contaminacao."""
    registry.reset()
    set_correlation_id("test-correlation")
    yield
    registry.reset()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Configuracao de teste com tabela e fila unicas por caso.

    ``queue_path`` aponta para o diretorio temporario: sem isso os testes gravariam na
    fila real de desenvolvimento em ``./data``.
    """
    return Settings(
        env="local",
        dynamo_endpoint=DYNAMO_ENDPOINT,
        dynamo_table=f"nexus-test-{uuid.uuid4().hex[:12]}",
        outbox_shards=2,
        outbox_max_attempts=3,
        outbox_backoff_base_seconds=0.01,
        idempotency_ttl_seconds=3600,
        queue_path=str(tmp_path / "fila.db"),
        queue_max_receive=3,
        queue_retry_backoff_base_seconds=0.01,
        worker_batch_size=10,
        worker_id="worker-teste",
    )
