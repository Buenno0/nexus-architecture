"""Testes do worker — ADR-005.

Usam a ``SqliteQueue`` real em arquivo temporario. Um segundo motor de fila so para
teste poderia divergir do verdadeiro e dar testes verdes sobre comportamento que nao
existe em producao.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from nexus.persistence.models import RecordType, StoredRecord
from nexus.queue.client import QueueMessage
from nexus.queue.processor import DefaultProcessor, ProcessingError
from nexus.queue.sqlite import SqliteQueue
from nexus.queue.worker import Worker
from nexus.shared.clock import utcnow
from nexus.shared.config import Settings
from nexus.shared.logging import get_correlation_id
from tests.fakes import FakeRepository


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        env="local",
        queue_path=str(tmp_path / "fila.db"),
        queue_max_receive=3,
        queue_retry_backoff_base_seconds=0.01,
        worker_batch_size=10,
        worker_id="worker-teste",
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


def enqueue(repo: FakeRepository, queue: SqliteQueue, count: int = 1) -> list[str]:
    ids = []
    for i in range(count):
        record_id = f"rec-{i}"
        repo.records[record_id] = StoredRecord(
            record_id=record_id,
            record_type=RecordType.PERSON,
            source="testes",
            natural_key=f"nk-{i}",
            record_fingerprint=f"fp-{i}",
            payload={"document": "123"},
            normalized={"document": "123"},
            correlation_id=f"corr-{i}",
            created_at=utcnow(),
        )
        queue.publish(QueueMessage(f"evt-{i}", record_id, f"corr-{i}"))
        ids.append(record_id)
    return ids


class SempreFalha:
    def process(self, record: StoredRecord) -> dict[str, Any]:
        raise ProcessingError("falha deliberada")


class FalhaUmaVez:
    def __init__(self) -> None:
        self.chamadas = 0

    def process(self, record: StoredRecord) -> dict[str, Any]:
        self.chamadas += 1
        if self.chamadas == 1:
            raise ProcessingError("falha transitoria")
        return DefaultProcessor().process(record)


class TestCaminhoFeliz:
    def test_processa_e_grava_resultado(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        enqueue(repo, queue, 1)
        relatorio = Worker(repo, queue, DefaultProcessor(), settings).process_once()

        assert relatorio.received == 1
        assert relatorio.processed == 1
        assert "rec-0" in repo.processing

    def test_remove_a_mensagem_da_fila(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        enqueue(repo, queue, 1)
        Worker(repo, queue, DefaultProcessor(), settings).process_once()
        assert queue.stats().total == 0

    def test_processa_o_lote_inteiro(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        enqueue(repo, queue, 7)
        assert Worker(repo, queue, DefaultProcessor(), settings).process_once().processed == 7

    def test_respeita_o_tamanho_do_lote(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        enqueue(repo, queue, 10)
        relatorio = Worker(repo, queue, DefaultProcessor(), settings).process_once(max_messages=3)
        assert relatorio.received == 3
        assert queue.stats().pending == 7

    def test_fila_vazia(self, repo: FakeRepository, queue: SqliteQueue, settings: Settings) -> None:
        relatorio = Worker(repo, queue, DefaultProcessor(), settings).process_once()
        assert relatorio.received == 0
        assert relatorio.processed == 0

    def test_resultado_registra_metadados(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        enqueue(repo, queue, 1)
        Worker(repo, queue, DefaultProcessor(), settings).process_once()

        resultado = repo.processing["rec-0"]
        assert resultado.worker_id == "worker-teste"
        assert resultado.event_id == "evt-0"
        assert resultado.correlation_id == "corr-0"
        assert resultado.attempts == 1
        assert resultado.duration_ms >= 0


class TestIdempotenciaNoConsumo:
    """A propriedade central da Fase 2."""

    def test_reentrega_produz_um_unico_resultado(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        """Criterio de aceite: a mesma mensagem entregue duas vezes processa uma vez."""
        enqueue(repo, queue, 1)
        worker = Worker(repo, queue, DefaultProcessor(), settings)
        worker.process_once()

        # O outbox republica apos crash — ADR-003 admite isso explicitamente.
        queue.publish(QueueMessage("evt-0-bis", "rec-0", "corr-0"))
        segunda = worker.process_once()

        assert segunda.skipped_duplicate == 1
        assert segunda.processed == 0
        assert len(repo.processing) == 1

    def test_consulta_previa_evita_trabalho(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        """A consulta e otimizacao; a garantia vem da escrita condicional."""

        class Contador(DefaultProcessor):
            chamadas = 0

            def process(self, record: StoredRecord) -> dict[str, Any]:
                Contador.chamadas += 1
                return super().process(record)

        enqueue(repo, queue, 1)
        worker = Worker(repo, queue, Contador(), settings)
        worker.process_once()
        queue.publish(QueueMessage("evt-0-bis", "rec-0", "corr-0"))
        worker.process_once()

        assert Contador.chamadas == 1

    def test_corrida_na_escrita_e_tratada_como_duplicata(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        """Se outro worker gravou entre a consulta e a escrita, nao e erro."""

        class GravaAntes(DefaultProcessor):
            def __init__(self, repositorio: FakeRepository) -> None:
                self._repo = repositorio

            def process(self, record: StoredRecord) -> dict[str, Any]:
                resumo = super().process(record)
                # Simula outro worker vencendo a corrida logo apos a consulta previa.
                from nexus.persistence.models import ProcessingResult

                self._repo.commit_processing(
                    ProcessingResult(
                        record.record_id, "outro", "outro-worker", 1, 1.0, {}, "c", utcnow()
                    )
                )
                return resumo

        enqueue(repo, queue, 1)
        relatorio = Worker(repo, queue, GravaAntes(repo), settings).process_once()

        assert relatorio.skipped_duplicate == 1
        assert relatorio.processed == 0
        assert queue.stats().total == 0, "a mensagem deve sair da fila mesmo assim"
        assert repo.processing["rec-0"].worker_id == "outro-worker"

    def test_rodar_duas_vezes_nao_duplica(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        enqueue(repo, queue, 5)
        worker = Worker(repo, queue, DefaultProcessor(), settings)
        worker.process_once()
        worker.process_once()
        assert len(repo.processing) == 5


class TestFalhas:
    def test_falha_devolve_para_retentativa(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        enqueue(repo, queue, 1)
        relatorio = Worker(repo, queue, SempreFalha(), settings).process_once()

        assert relatorio.retried == 1
        assert relatorio.processed == 0
        assert repo.processing == {}
        assert queue.stats().dead == 0

    def test_retentativa_bem_sucedida_processa(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        enqueue(repo, queue, 1)
        worker = Worker(repo, queue, FalhaUmaVez(), settings)

        assert worker.process_once().retried == 1
        time.sleep(0.05)
        assert worker.process_once().processed == 1
        assert "rec-0" in repo.processing

    def test_vai_para_dlq_ao_esgotar(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        enqueue(repo, queue, 1)
        worker = Worker(repo, queue, SempreFalha(), settings)
        for _ in range(settings.queue_max_receive):
            worker.process_once()
            time.sleep(0.05)

        stats = queue.stats()
        assert stats.dead == 1
        assert stats.pending == 0
        assert repo.processing == {}

    def test_registro_inexistente_vai_direto_para_dlq(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        """Retentar nao traz de volta um registro que nao existe."""
        queue.publish(QueueMessage("evt-orfao", "rec-inexistente", "corr"))
        relatorio = Worker(repo, queue, DefaultProcessor(), settings).process_once()

        assert relatorio.dead_lettered == 1
        assert queue.stats().dead == 1
        assert queue.stats().pending == 0

    def test_mensagem_envenenada_nao_trava_as_demais(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        enqueue(repo, queue, 3)
        queue.publish(QueueMessage("evt-orfao", "rec-inexistente", "corr"))

        relatorio = Worker(repo, queue, DefaultProcessor(), settings).process_once()

        assert relatorio.processed == 3
        assert relatorio.dead_lettered == 1
        assert len(repo.processing) == 3

    def test_redrive_permite_reprocessar(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        enqueue(repo, queue, 1)
        falho = Worker(repo, queue, SempreFalha(), settings)
        for _ in range(settings.queue_max_receive):
            falho.process_once()
            time.sleep(0.05)
        assert queue.stats().dead == 1

        assert queue.redrive(limit=10) == 1
        assert Worker(repo, queue, DefaultProcessor(), settings).process_once().processed == 1
        assert "rec-0" in repo.processing


class TestObservabilidade:
    def test_propaga_correlation_id_da_ingestao(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        """A trilha de log continua no worker, que roda em outro processo."""
        visto: list[str | None] = []

        class Espia(DefaultProcessor):
            def process(self, record: StoredRecord) -> dict[str, Any]:
                visto.append(get_correlation_id())
                return super().process(record)

        enqueue(repo, queue, 1)
        Worker(repo, queue, Espia(), settings).process_once()
        assert visto == ["corr-0"]

    def test_relatorio_tem_duracao(
        self, repo: FakeRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        enqueue(repo, queue, 1)
        assert Worker(repo, queue, DefaultProcessor(), settings).process_once().duration_ms > 0
