"""Testes do dispatcher do outbox — ADR-003."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from nexus.persistence.models import OutboxEvent, OutboxStatus, RecordType, StoredRecord
from nexus.queue.client import QueueMessage
from nexus.queue.dispatcher import OutboxDispatcher
from nexus.queue.sqlite import SqliteQueue
from nexus.shared.clock import utcnow
from nexus.shared.config import Settings
from nexus.shared.errors import QueuePublishError
from tests.fakes import FakeRepository, RecordingQueueClient


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        env="local",
        queue_path=str(tmp_path / "fila.db"),
        outbox_shards=2,
        outbox_max_attempts=3,
        outbox_backoff_base_seconds=0.01,
        outbox_dispatch_batch_size=25,
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
    return FakeRepository()


def seed(
    repo: FakeRepository, count: int, shard: str = "PENDING#0", prefix: str = "a"
) -> list[str]:
    ids: list[str] = []
    now = utcnow()
    for i in range(count):
        record_id, event_id = f"rec-{prefix}-{i}", f"evt-{prefix}-{i}"
        repo.records[record_id] = StoredRecord(
            record_id=record_id,
            record_type=RecordType.PERSON,
            source="testes",
            natural_key=f"nk-{i}",
            record_fingerprint=f"fp-{i}",
            payload={},
            normalized={},
            correlation_id=f"corr-{i}",
            created_at=now,
        )
        repo.events[event_id] = OutboxEvent(
            event_id=event_id,
            record_id=record_id,
            correlation_id=f"corr-{i}",
            created_at=now,
            next_attempt_at=now,
            pending_shard=shard,
        )
        ids.append(event_id)
    return ids


class TestDespacho:
    def test_publica_pendentes(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        seed(repo, 5)
        relatorio = OutboxDispatcher(repo, queue, settings).dispatch_once()

        assert relatorio.scanned == 5
        assert relatorio.dispatched == 5
        assert queue.stats().pending == 5

    def test_remove_do_indice_esparso(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        """O evento despachado precisa sair do indice, senao sera tentado para sempre."""
        seed(repo, 3)
        OutboxDispatcher(repo, queue, settings).dispatch_once()

        assert repo.count_pending_outbox() == 0
        assert all(e.status == OutboxStatus.DISPATCHED for e in repo.events.values())
        assert all(e.pending_shard is None for e in repo.events.values())

    def test_segunda_passada_nao_encontra_nada(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        seed(repo, 3)
        dispatcher = OutboxDispatcher(repo, queue, settings)
        dispatcher.dispatch_once()
        assert dispatcher.dispatch_once().scanned == 0

    def test_respeita_o_limite(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        seed(repo, 10)
        assert OutboxDispatcher(repo, queue, settings).dispatch_once(limit=4).dispatched == 4
        assert queue.stats().pending == 4

    def test_varre_todos_os_shards(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        """Um shard nao varrido deixa eventos permanentemente orfaos — ADR-003."""
        seed(repo, 2, shard="PENDING#0", prefix="s0")
        seed(repo, 3, shard="PENDING#1", prefix="s1")

        relatorio = OutboxDispatcher(repo, queue, settings).dispatch_once()

        assert relatorio.dispatched == 5
        assert repo.count_pending_outbox() == 0

    def test_propaga_correlation_id(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        seed(repo, 1)
        OutboxDispatcher(repo, queue, settings).dispatch_once()
        assert queue.receive(max_messages=1)[0].correlation_id == "corr-0"


class TestCasosDeBorda:
    def test_republicacao_conta_como_duplicata(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        """ADR-003 admite republicacao apos crash; ela nao pode virar mensagem nova."""
        seed(repo, 1)
        queue.publish(QueueMessage("evt-a-0", "rec-a-0", "corr-0"))

        relatorio = OutboxDispatcher(repo, queue, settings).dispatch_once()
        assert relatorio.duplicates == 1
        assert relatorio.dispatched == 0
        assert queue.stats().pending == 1

    def test_evento_ausente_e_registrado(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        seed(repo, 1)
        repo.events.clear()
        # O indice ainda lista o evento, mas a tabela base nao o tem.
        repo.events["fantasma"] = OutboxEvent(
            "fantasma", "rec-x", "corr", utcnow(), utcnow(), pending_shard="PENDING#0"
        )
        dispatcher = OutboxDispatcher(repo, queue, settings)
        del repo.events["fantasma"]
        assert dispatcher.dispatch_once().scanned == 0

    def test_falha_de_publicacao_reagenda(self, repo: FakeRepository, settings: Settings) -> None:
        seed(repo, 2)
        fila_quebrada = RecordingQueueClient(fail=True)

        relatorio = OutboxDispatcher(repo, fila_quebrada, settings).dispatch_once()

        assert relatorio.rescheduled == 2
        assert relatorio.dispatched == 0
        # Continuam pendentes: nada foi perdido, serao tentados de novo.
        assert all(e.attempts == 1 for e in repo.events.values())

    def test_tentativas_esgotadas_saem_do_indice(
        self, repo: FakeRepository, settings: Settings
    ) -> None:
        seed(repo, 1)
        dispatcher = OutboxDispatcher(repo, RecordingQueueClient(fail=True), settings)
        for _ in range(settings.outbox_max_attempts):
            dispatcher.dispatch_once()

        evento = next(iter(repo.events.values()))
        assert evento.status == OutboxStatus.FAILED
        assert repo.count_pending_outbox() == 0

    def test_sem_fila_nao_faz_nada(self, repo: FakeRepository, settings: Settings) -> None:
        from nexus.queue.client import NullQueueClient

        seed(repo, 5)
        relatorio = OutboxDispatcher(repo, NullQueueClient(), settings).dispatch_once()

        assert relatorio.scanned == 0
        assert repo.count_pending_outbox() == 5
        # Nenhuma tentativa consumida: nao ha fila, nao e falha.
        assert all(e.attempts == 0 for e in repo.events.values())


class TestPublicacaoQueFalhaERecupera:
    def test_erro_inesperado_nao_derruba_o_lote(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        seed(repo, 3)

        class FilaIntermitente(SqliteQueue):
            chamadas = 0

            def publish(self, message: QueueMessage) -> bool:
                FilaIntermitente.chamadas += 1
                if FilaIntermitente.chamadas == 2:
                    raise QueuePublishError("falha transitoria")
                return super().publish(message)

        fila = FilaIntermitente(settings=settings)
        try:
            relatorio = OutboxDispatcher(repo, fila, settings).dispatch_once()
        finally:
            fila.close()

        assert relatorio.dispatched == 2
        assert relatorio.rescheduled == 1
        assert repo.count_pending_outbox() == 1
