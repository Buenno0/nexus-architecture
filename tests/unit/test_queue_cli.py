"""Testes da fabrica de fila e dos pontos de entrada de linha de comando.

Sao os caminhos que ``make dispatch`` e ``make process`` executam em producao: deixa-los
sem teste significaria descobrir uma quebra so na operacao.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import nexus.persistence as persistence_pkg
import nexus.queue as queue_pkg
from nexus.persistence.models import OutboxEvent, RecordType, StoredRecord
from nexus.queue import dispatcher as dispatcher_module
from nexus.queue import get_queue_client
from nexus.queue import worker as worker_module
from nexus.queue.client import NullQueueClient
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
        worker_batch_size=5,
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
    for i in range(3):
        record_id, event_id = f"rec-{i}", f"evt-{i}"
        repositorio.records[record_id] = StoredRecord(
            record_id=record_id,
            record_type=RecordType.PERSON,
            source="cli",
            natural_key=f"nk-{i}",
            record_fingerprint=f"fp-{i}",
            payload={},
            normalized={"document": "1"},
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
    monkeypatch.setattr(persistence_pkg, "get_repository", lambda: repo)
    monkeypatch.setattr(queue_pkg, "get_queue_client", lambda: queue)
    monkeypatch.setattr(dispatcher_module, "get_settings", lambda: settings)
    monkeypatch.setattr(worker_module, "get_settings", lambda: settings)


class TestFabrica:
    def test_backend_none_devolve_implementacao_nula(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(queue_pkg, "get_settings", lambda: Settings(queue_backend="none"))
        get_queue_client.cache_clear()
        try:
            assert isinstance(get_queue_client(), NullQueueClient)
        finally:
            get_queue_client.cache_clear()

    def test_backend_sqlite_devolve_fila_real(
        self, monkeypatch: pytest.MonkeyPatch, settings: Settings
    ) -> None:
        monkeypatch.setattr(queue_pkg, "get_settings", lambda: settings)
        get_queue_client.cache_clear()
        try:
            cliente = get_queue_client()
            assert isinstance(cliente, SqliteQueue)
            cliente.close()
        finally:
            get_queue_client.cache_clear()


class TestDispatcherCli:
    def test_despacha_pendentes(
        self, wired: None, queue: SqliteQueue, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert dispatcher_module.main([]) == 0
        assert "despachados=3" in capsys.readouterr().out
        assert queue.stats().pending == 3

    def test_respeita_o_limite(
        self, wired: None, queue: SqliteQueue, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert dispatcher_module.main(["--limit", "2"]) == 0
        assert "despachados=2" in capsys.readouterr().out
        assert queue.stats().pending == 2


class TestWorkerCli:
    def test_consome_um_lote(
        self,
        wired: None,
        queue: SqliteQueue,
        repo: FakeRepository,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        dispatcher_module.main([])
        capsys.readouterr()

        assert worker_module.main([]) == 0
        assert "processadas=3" in capsys.readouterr().out
        assert len(repo.processing) == 3

    def test_drain_esvazia_a_fila(
        self,
        wired: None,
        queue: SqliteQueue,
        repo: FakeRepository,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        dispatcher_module.main([])
        capsys.readouterr()

        assert worker_module.main(["--drain", "--batch-size", "1"]) == 0
        assert "processadas=3" in capsys.readouterr().out
        assert queue.stats().total == 0

    def test_fila_vazia_nao_falha(self, wired: None, capsys: pytest.CaptureFixture[str]) -> None:
        assert worker_module.main([]) == 0
        assert "recebidas=0" in capsys.readouterr().out
