"""Testes da trilha de observabilidade — ADR-010.

O criterio que governa este arquivo nao e "a trilha registra os marcos", e sim **a
trilha nunca derruba o que observa**. Por isso quase metade dos casos aqui quebra a
gravacao de proposito e verifica que a ingestao e o processamento seguem intactos.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from nexus.ingestion.service import IngestionService
from nexus.observability.trail import TrailRecorder
from nexus.persistence.models import RecordType, StoredRecord, TrailStage
from nexus.queue.client import QueueMessage
from nexus.queue.dispatcher import OutboxDispatcher
from nexus.queue.processor import DefaultProcessor, ProcessingError
from nexus.queue.sqlite import SqliteQueue
from nexus.queue.worker import Worker
from nexus.shared.clock import utcnow
from nexus.shared.config import Settings
from tests.fakes import FakeRepository, RecordingQueueClient

PAYLOAD: dict[str, Any] = {
    "source": "testes",
    "full_name": "Maria Souza",
    "email": "maria@example.com",
    "document": "12345678909",
    "phone": "11999998888",
}


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def worker_settings(tmp_path: Path) -> Settings:
    return Settings(
        env="local",
        queue_path=str(tmp_path / "fila.db"),
        queue_max_receive=3,
        queue_retry_backoff_base_seconds=0.01,
        worker_batch_size=10,
        worker_id="worker-teste",
    )


@pytest.fixture
def queue(worker_settings: Settings) -> Iterator[SqliteQueue]:
    fila = SqliteQueue(settings=worker_settings)
    try:
        yield fila
    finally:
        fila.close()


def semear(repo: FakeRepository, queue: SqliteQueue, *, created_at: Any = None) -> str:
    repo.records["rec-0"] = StoredRecord(
        record_id="rec-0",
        record_type=RecordType.PERSON,
        source="testes",
        natural_key="nk-0",
        record_fingerprint="fp-0",
        payload={"document": "123"},
        normalized={"document": "123"},
        correlation_id="corr-0",
        created_at=created_at or utcnow(),
    )
    queue.publish(QueueMessage("evt-0", "rec-0", "corr-0"))
    return "rec-0"


def marcos(repo: FakeRepository, record_id: str) -> list[str]:
    return [e.stage.value for e in repo.get_trail(record_id)]


class SempreFalha:
    version = "teste-v1"

    def process(self, record: StoredRecord) -> dict[str, Any]:
        raise ProcessingError("falha deliberada")


class TestMarcosDaIngestao:
    def test_aceitacao_e_publicacao_entram_na_trilha(
        self, repo: FakeRepository, settings: Settings
    ) -> None:
        fila = RecordingQueueClient(enabled=True)
        servico = IngestionService(repo, fila, settings)
        resultado = servico.ingest(
            RecordType.PERSON,
            PAYLOAD,
            raw_body=json.dumps(PAYLOAD, sort_keys=True).encode(),
            idempotency_key="k1",
            correlation_id="corr-ingest",
        )

        record_id = resultado.body["record_id"]
        assert marcos(repo, record_id) == ["accepted", "published"]

    def test_o_marco_carrega_quem_emitiu_e_o_correlation_id(
        self, repo: FakeRepository, settings: Settings
    ) -> None:
        """Sem ``service`` a trilha nao responde "onde parou"; sem ``correlation_id``
        nao cruza com os logs. Os dois sao o motivo de a trilha existir."""
        servico = IngestionService(repo, RecordingQueueClient(enabled=True), settings)
        resultado = servico.ingest(
            RecordType.PERSON,
            PAYLOAD,
            raw_body=json.dumps(PAYLOAD, sort_keys=True).encode(),
            idempotency_key="k1",
            correlation_id="corr-ingest",
        )

        evento = repo.get_trail(resultado.body["record_id"])[0]
        assert evento.service == "api"
        assert evento.correlation_id == "corr-ingest"
        assert evento.detail["source"] == "testes"

    def test_duplicata_nao_gera_marco(self, repo: FakeRepository, settings: Settings) -> None:
        """Conteudo ja observado nao cria observacao nem enfileira — nada aconteceu
        com o registro, entao nada entra na trilha dele."""
        servico = IngestionService(repo, RecordingQueueClient(enabled=True), settings)
        corpo = json.dumps(PAYLOAD, sort_keys=True).encode()
        primeiro = servico.ingest(
            RecordType.PERSON,
            PAYLOAD,
            raw_body=corpo,
            idempotency_key="k1",
            correlation_id="c1",
        )
        servico.ingest(
            RecordType.PERSON,
            PAYLOAD,
            raw_body=corpo,
            idempotency_key="k2",
            correlation_id="c2",
        )

        assert marcos(repo, primeiro.body["record_id"]) == ["accepted", "published"]


class TestMarcosDoDispatcher:
    def test_publicacao_pelo_dispatcher_identifica_a_via(
        self, repo: FakeRepository, settings: Settings
    ) -> None:
        """Publicacao inline e publicacao pelo dispatcher produzem o mesmo marco. A
        diferenca — o caminho feliz ou a rede de seguranca — esta no detalhe."""
        servico = IngestionService(repo, RecordingQueueClient(enabled=False), settings)
        resultado = servico.ingest(
            RecordType.PERSON,
            PAYLOAD,
            raw_body=json.dumps(PAYLOAD, sort_keys=True).encode(),
            idempotency_key="k1",
            correlation_id="corr-ingest",
        )
        record_id = resultado.body["record_id"]
        assert marcos(repo, record_id) == ["accepted"]

        OutboxDispatcher(repo, RecordingQueueClient(enabled=True), settings).dispatch_once()

        trilha = repo.get_trail(record_id)
        assert [e.stage.value for e in trilha] == ["accepted", "published"]
        assert trilha[-1].service == "dispatcher"
        assert trilha[-1].detail["via"] == "dispatcher"


class TestMarcosDoWorker:
    def test_consumo_e_resolucao_entram_na_trilha(
        self, repo: FakeRepository, queue: SqliteQueue, worker_settings: Settings
    ) -> None:
        record_id = semear(repo, queue)
        Worker(repo, queue, DefaultProcessor(), worker_settings).process_once()

        assert marcos(repo, record_id) == ["consumed", "resolved"]

    def test_a_trilha_atravessa_processos(
        self,
        repo: FakeRepository,
        queue: SqliteQueue,
        settings: Settings,
        worker_settings: Settings,
    ) -> None:
        """O ponto da fase: um unico `record_id` reconstruindo API **e** worker.

        Antes disso a metade do worker so existia no terminal de quem rodou o comando.
        """
        servico = IngestionService(repo, RecordingQueueClient(enabled=True), settings)
        resultado = servico.ingest(
            RecordType.PERSON,
            PAYLOAD,
            raw_body=json.dumps(PAYLOAD, sort_keys=True).encode(),
            idempotency_key="k1",
            correlation_id="corr-ponta-a-ponta",
        )
        record_id = resultado.body["record_id"]
        queue.publish(QueueMessage("evt-0", record_id, "corr-ponta-a-ponta"))
        Worker(repo, queue, DefaultProcessor(), worker_settings).process_once()

        trilha = repo.get_trail(record_id)
        assert [e.stage.value for e in trilha] == [
            "accepted",
            "published",
            "consumed",
            "resolved",
        ]
        assert {e.service for e in trilha} == {"api", "worker"}
        assert all(e.correlation_id == "corr-ponta-a-ponta" for e in trilha)

    def test_falha_transitoria_vira_marco_failed(
        self, repo: FakeRepository, queue: SqliteQueue, worker_settings: Settings
    ) -> None:
        record_id = semear(repo, queue)
        Worker(repo, queue, SempreFalha(), worker_settings).process_once()

        assert marcos(repo, record_id) == ["consumed", "failed"]
        assert repo.get_trail(record_id)[-1].detail["reason"] == "falha deliberada"

    def test_esgotar_tentativas_vira_marco_dead_lettered(
        self, repo: FakeRepository, queue: SqliteQueue, worker_settings: Settings
    ) -> None:
        record_id = semear(repo, queue)
        worker = Worker(repo, queue, SempreFalha(), worker_settings)
        for _ in range(worker_settings.queue_max_receive):
            worker.process_once()
            time.sleep(0.05)

        assert marcos(repo, record_id)[-1] == "dead_lettered"

    def test_registro_inexistente_vira_marco_dead_lettered(
        self, repo: FakeRepository, queue: SqliteQueue, worker_settings: Settings
    ) -> None:
        queue.publish(QueueMessage("evt-orfao", "rec-fantasma", "corr"))
        Worker(repo, queue, DefaultProcessor(), worker_settings).process_once()

        assert marcos(repo, "rec-fantasma") == ["dead_lettered"]

    def test_reprocessamento_ja_feito_nao_gera_marco(
        self, repo: FakeRepository, queue: SqliteQueue, worker_settings: Settings
    ) -> None:
        """Reentrega e comportamento normal (ADR-005). Marcar `consumed` outra vez
        encheria a trilha de ruido sobre trabalho que nao aconteceu."""
        record_id = semear(repo, queue)
        worker = Worker(repo, queue, DefaultProcessor(), worker_settings)
        worker.process_once()
        queue.publish(QueueMessage("evt-0", record_id, "corr-0"))
        worker.process_once()

        assert marcos(repo, record_id) == ["consumed", "resolved"]


class TestLatenciaFimAFim:
    def test_resultado_registra_a_espera_na_fila(
        self, repo: FakeRepository, queue: SqliteQueue, worker_settings: Settings
    ) -> None:
        semear(repo, queue, created_at=utcnow() - timedelta(seconds=5))
        Worker(repo, queue, DefaultProcessor(), worker_settings).process_once()

        resultado = repo.processing[next(iter(repo.processing))]
        assert resultado.end_to_end_ms is not None
        # Cinco segundos parados na fila; o processamento em si leva milissegundos.
        assert resultado.end_to_end_ms >= 5000
        assert resultado.duration_ms < 1000

    def test_relogios_discordantes_nao_viram_latencia_zero(
        self, repo: FakeRepository, queue: SqliteQueue, worker_settings: Settings
    ) -> None:
        """Duas pontas carimbadas por processos diferentes; na AWS, duas Lambdas.

        Delta negativo e medicao invalida, nao latencia pequena. Gravar zero a
        esconderia dentro de um histograma plausivel.
        """
        semear(repo, queue, created_at=utcnow() + timedelta(seconds=30))
        Worker(repo, queue, DefaultProcessor(), worker_settings).process_once()

        resultado = repo.processing[next(iter(repo.processing))]
        assert resultado.end_to_end_ms is None


class TestObservabilidadeNaoDerrubaOObservado:
    """O criterio de aceite que governa a fase inteira."""

    def test_trilha_quebrada_nao_impede_a_ingestao(
        self, repo: FakeRepository, settings: Settings
    ) -> None:
        repo.trail_quebrada = True
        servico = IngestionService(repo, RecordingQueueClient(enabled=True), settings)
        resultado = servico.ingest(
            RecordType.PERSON,
            PAYLOAD,
            raw_body=json.dumps(PAYLOAD, sort_keys=True).encode(),
            idempotency_key="k1",
            correlation_id="corr",
        )

        assert resultado.status_code == 202
        assert len(repo.records) == 1
        assert repo.get_trail(resultado.body["record_id"]) == []

    def test_trilha_quebrada_nao_impede_o_processamento(
        self, repo: FakeRepository, queue: SqliteQueue, worker_settings: Settings
    ) -> None:
        record_id = semear(repo, queue)
        repo.trail_quebrada = True
        relatorio = Worker(repo, queue, DefaultProcessor(), worker_settings).process_once()

        assert relatorio.processed == 1
        assert record_id in repo.processed_ids
        assert queue.stats().total == 0

    def test_erro_de_programacao_na_trilha_tambem_e_engolido(self, repo: FakeRepository) -> None:
        """O repositorio devolve ``False`` em falha de I/O, mas um detalhe que nao
        serializa levantaria antes de chegar nele. Observabilidade que quebra o que
        observa e pior que observabilidade nenhuma — vale para os dois casos."""

        class RepositorioExplosivo(FakeRepository):
            def record_trail(self, event: Any) -> bool:
                raise RuntimeError("tabela inexistente")

        recorder = TrailRecorder(RepositorioExplosivo(), "teste")
        recorder.marcar("rec-0", TrailStage.ACCEPTED)  # nao levanta


class TestTrilhaDesligada:
    """`trail_enabled=False` — o controle que a Fase 7 usa para medir o custo."""

    def test_nao_grava_marco_nenhum(self, repo: FakeRepository) -> None:
        servico = IngestionService(
            repo,
            RecordingQueueClient(enabled=True),
            Settings(env="local", trail_enabled=False),
        )
        resultado = servico.ingest(
            RecordType.PERSON,
            PAYLOAD,
            raw_body=json.dumps(PAYLOAD, sort_keys=True).encode(),
            idempotency_key="k1",
            correlation_id="corr",
        )

        assert resultado.status_code == 202
        assert repo.get_trail(resultado.body["record_id"]) == []

    def test_nao_toca_o_repositorio(self, repo: FakeRepository) -> None:
        """Desligar precisa evitar a chamada, nao so descartar o resultado.

        A economia que a Fase 7 vai medir esta na escrita que nao acontece; um
        recorder que monta o evento e joga fora nao economizaria nada.
        """

        class RepositorioProibido(FakeRepository):
            def record_trail(self, event: Any) -> bool:
                raise AssertionError("record_trail nao deveria ser chamado")

        recorder = TrailRecorder(
            RepositorioProibido(), "teste", Settings(env="local", trail_enabled=False)
        )
        recorder.marcar("rec-0", TrailStage.ACCEPTED)

    def test_o_processamento_segue_igual(
        self, repo: FakeRepository, queue: SqliteQueue, worker_settings: Settings
    ) -> None:
        """Sem trilha o resultado do processamento nao muda — e o que torna a
        comparacao A/B da Fase 7 valida."""
        desligado = worker_settings.model_copy(update={"trail_enabled": False})
        record_id = semear(repo, queue)
        relatorio = Worker(repo, queue, DefaultProcessor(), desligado).process_once()

        assert relatorio.processed == 1
        assert record_id in repo.processed_ids
        assert marcos(repo, record_id) == []
