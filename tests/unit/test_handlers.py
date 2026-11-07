"""Testes dos handlers Lambda.

Invocam os handlers com eventos como o Lambda os entregaria, usando o repositorio falso
e a fila SQLite. Nenhuma chamada sai da maquina.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from nexus.handlers import dispatcher as dispatcher_handler
from nexus.handlers import worker as worker_handler
from nexus.persistence.models import OutboxEvent, RecordType, StoredRecord
from nexus.queue.sqlite import SqliteQueue
from nexus.shared.clock import utcnow
from nexus.shared.config import Settings
from tests.fakes import FakeRepository


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        env="local",
        queue_path=str(tmp_path / "fila.db"),
        outbox_shards=1,
        outbox_dispatch_batch_size=10,
        worker_batch_size=5,
        max_batch_records=1000,
    )


@pytest.fixture
def queue(settings: Settings) -> Iterator[SqliteQueue]:
    fila = SqliteQueue(settings=settings)
    try:
        yield fila
    finally:
        fila.close()


@pytest.fixture
def repo() -> FakeRepository:
    repositorio = FakeRepository()
    now = utcnow()
    for i in range(6):
        record_id, event_id = f"rec-{i}", f"evt-{i}"
        repositorio.records[record_id] = StoredRecord(
            record_id=record_id,
            record_type=RecordType.PERSON,
            source="lambda",
            natural_key=f"nk-{i}",
            record_fingerprint=f"fp-{i}",
            payload={},
            normalized={"document": f"{i}"},
            correlation_id=f"corr-{i}",
            created_at=now,
        )
        repositorio.events[event_id] = OutboxEvent(
            event_id=event_id,
            record_id=record_id,
            correlation_id=f"corr-{i}",
            created_at=now,
            next_attempt_at=now,
            pending_shard="PENDING#0",
        )
    return repositorio


@pytest.fixture
def wired(
    monkeypatch: pytest.MonkeyPatch,
    repo: FakeRepository,
    queue: SqliteQueue,
    settings: Settings,
) -> None:
    # Os handlers importam as fabricas no topo do modulo, como convem ao Lambda
    # (resolvidas uma vez no cold start). O patch precisa ser onde o nome esta ligado.
    for modulo in (dispatcher_handler, worker_handler):
        monkeypatch.setattr(modulo, "get_repository", lambda: repo)
        monkeypatch.setattr(modulo, "get_queue_client", lambda: queue)
        monkeypatch.setattr(modulo, "_settings", settings)


class TestDispatcherHandler:
    def test_despacha_pendentes(self, wired: None, queue: SqliteQueue) -> None:
        resultado = dispatcher_handler.handler({}, None)
        assert resultado["dispatched"] == 6
        assert queue.stats().pending == 6

    def test_respeita_o_limite_do_evento(self, wired: None, queue: SqliteQueue) -> None:
        assert dispatcher_handler.handler({"limit": 2}, None)["dispatched"] == 2
        assert queue.stats().pending == 2

    def test_teto_de_seguranca_prevalece(self, wired: None, settings: Settings) -> None:
        """A Lambda pode ser invocada direto; o teto nao pode viver so na API."""
        resultado = dispatcher_handler.handler({"limit": 999_999}, None)
        assert resultado["dispatched"] <= settings.max_batch_records

    def test_evento_nulo(self, wired: None) -> None:
        assert dispatcher_handler.handler(None, None)["dispatched"] == 6

    def test_aceita_correlation_id_do_invocador(self, wired: None, repo: FakeRepository) -> None:
        """Sem eventos pendentes, a trilha e a que o invocador informou.

        Com eventos, o dispatcher passa a usar o correlation_id de cada um — e o
        comportamento correto: a trilha pertence ao registro, nao a invocacao.
        """
        from nexus.shared.logging import get_correlation_id

        repo.events.clear()
        dispatcher_handler.handler({"correlation_id": "trilha-externa"}, None)
        assert get_correlation_id() == "trilha-externa"

    def test_trilha_de_cada_evento_prevalece(self, wired: None) -> None:
        from nexus.shared.logging import get_correlation_id

        dispatcher_handler.handler({"correlation_id": "trilha-externa", "limit": 1}, None)
        assert get_correlation_id() != "trilha-externa"
        assert str(get_correlation_id()).startswith("corr-")

    def test_resposta_serializavel(self, wired: None) -> None:
        import json

        json.dumps(dispatcher_handler.handler({}, None))


class TestWorkerHandler:
    def test_consome_um_lote(self, wired: None, repo: FakeRepository) -> None:
        dispatcher_handler.handler({}, None)
        resultado = worker_handler.handler({"max_messages": 10}, None)

        assert resultado["received"] == 6
        assert resultado["processed"] == 6
        assert resultado["batches"] == 1
        assert len(repo.processing) == 6

    def test_fila_vazia(self, wired: None) -> None:
        resultado = worker_handler.handler({}, None)
        assert resultado["received"] == 0
        assert resultado["processed"] == 0

    def test_drain_percorre_varios_lotes(self, wired: None, queue: SqliteQueue) -> None:
        dispatcher_handler.handler({}, None)
        resultado = worker_handler.handler({"max_messages": 2, "max_batches": 10}, None)

        assert resultado["processed"] == 6
        assert resultado["batches"] > 1
        assert queue.stats().total == 0

    def test_teto_de_lotes(self, wired: None) -> None:
        """Lambda tem tempo limitado: um laco sem teto seria cortado no meio."""
        dispatcher_handler.handler({}, None)
        resultado = worker_handler.handler({"max_messages": 1, "max_batches": 2}, None)
        assert resultado["batches"] == 2
        assert resultado["processed"] == 2

    def test_reprocessar_nao_duplica(self, wired: None, repo: FakeRepository) -> None:
        dispatcher_handler.handler({}, None)
        worker_handler.handler({"max_messages": 10}, None)
        segundo = worker_handler.handler({"max_messages": 10}, None)

        assert segundo["received"] == 0
        assert len(repo.processing) == 6

    def test_resposta_serializavel(self, wired: None) -> None:
        import json

        json.dumps(worker_handler.handler({}, None))


class TestApiHandler:
    def test_mangum_envolve_o_mesmo_app(self) -> None:
        """O handler da API nao pode ser um app diferente do que roda local."""
        from nexus.handlers.api import handler
        from nexus.ingestion.api import app

        assert handler.app is app

    def test_lifespan_desligado(self) -> None:
        from nexus.handlers.api import handler

        assert handler.lifespan == "off"

    def test_responde_a_evento_do_api_gateway(self) -> None:
        from nexus.handlers.api import handler

        evento: dict[str, Any] = {
            "version": "2.0",
            "routeKey": "GET /health",
            "rawPath": "/health",
            "rawQueryString": "",
            "headers": {"host": "api.exemplo.dev"},
            "requestContext": {
                "http": {
                    "method": "GET",
                    "path": "/health",
                    "protocol": "HTTP/1.1",
                    "sourceIp": "127.0.0.1",
                },
                "stage": "$default",
                "requestId": "req-1",
            },
            "isBase64Encoded": False,
        }
        resposta = handler(evento, None)
        assert resposta["statusCode"] in (200, 503)
