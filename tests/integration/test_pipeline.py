"""Pipeline completo — ingestao, dispatch e consumo.

Contra DynamoDB Local e fila SQLite reais. E o teste que prova que a Fase 2 fecha o
ciclo que a Fase 1 deixou aberto.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nexus.ingestion.api import app
from nexus.persistence import get_repository
from nexus.persistence.dynamo import DynamoRecordRepository
from nexus.queue import get_queue_client
from nexus.queue.client import QueueMessage
from nexus.queue.dispatcher import OutboxDispatcher
from nexus.queue.processor import DefaultProcessor, ProcessingError
from nexus.queue.sqlite import SqliteQueue
from nexus.queue.worker import Worker
from nexus.resolution.engine import ResolutionProcessor
from nexus.shared.config import Settings, get_settings

pytestmark = pytest.mark.integration

PESSOA: dict[str, Any] = {
    "source": "pipeline",
    "full_name": "Maria Aparecida Souza",
    "email": "maria.souza@example.com",
    "document": "123.456.789-09",
    "phone": "(11) 98765-4321",
}


#: Versao do processador que o worker usa quando ha repositorio disponivel.
RESOLUTION_VERSION = ResolutionProcessor(None).version  # type: ignore[arg-type]


def key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


@pytest.fixture
def queue(settings: Settings) -> Iterator[SqliteQueue]:
    fila = SqliteQueue(settings=settings)
    try:
        yield fila
    finally:
        fila.close()


@pytest.fixture
def client(
    repository: DynamoRecordRepository, queue: SqliteQueue, settings: Settings
) -> Iterator[TestClient]:
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_queue_client] = lambda: queue
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


class TestCicloCompleto:
    def test_ingestao_publica_inline(self, client: TestClient, queue: SqliteQueue) -> None:
        """Com fila configurada, a publicacao best-effort da Fase 1 passa a funcionar."""
        resposta = client.post("/v1/records/person", json=PESSOA, headers=key())

        assert resposta.status_code == 202
        assert queue.stats().pending == 1
        assert client.get("/v1/ops/queue").json()["outbox_pending"] == 0

    def test_post_dispatch_process(
        self, client: TestClient, repository: DynamoRecordRepository
    ) -> None:
        record_id = client.post("/v1/records/person", json=PESSOA, headers=key()).json()[
            "record_id"
        ]

        client.post("/v1/ops/dispatch", json={"limit": 100})
        relatorio = client.post("/v1/ops/process", json={"max_messages": 10}).json()

        assert relatorio["processed"] == 1
        resultado = repository.find_processing_result(record_id, RESOLUTION_VERSION)
        assert resultado is not None
        # A Fase 5 substituiu o processador: o resumo agora descreve a resolucao.
        assert resultado.summary["stage"] == "entity-resolution"
        assert resultado.processor_version == RESOLUTION_VERSION
        assert resultado.correlation_id

    def test_lote_grande_percorre_o_pipeline(self, client: TestClient, queue: SqliteQueue) -> None:
        for i in range(25):
            client.post(
                "/v1/records/person",
                json={**PESSOA, "phone": f"(11) 98765-{i:04d}"},
                headers=key(),
            )

        client.post("/v1/ops/dispatch", json={"limit": 1000})
        total = 0
        for _ in range(10):
            relatorio = client.post("/v1/ops/process", json={"max_messages": 10}).json()
            total += relatorio["processed"]
            if relatorio["received"] == 0:
                break

        assert total == 25
        stats = client.get("/v1/ops/queue").json()
        assert stats["pending"] == 0
        assert stats["dead"] == 0
        assert stats["outbox_pending"] == 0


class TestDispatcherContraDynamo:
    def test_recupera_eventos_que_a_ingestao_nao_publicou(
        self, repository: DynamoRecordRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        """A rede de seguranca do ADR-003, contra o indice esparso real."""
        from nexus.queue.client import NullQueueClient

        app.dependency_overrides[get_repository] = lambda: repository
        app.dependency_overrides[get_queue_client] = lambda: NullQueueClient()
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            cliente = TestClient(app, raise_server_exceptions=False)
            for i in range(5):
                cliente.post(
                    "/v1/records/person",
                    json={**PESSOA, "phone": f"(11) 91111-{i:04d}"},
                    headers=key(),
                )
            assert repository.count_pending_outbox() == 5
        finally:
            app.dependency_overrides.clear()

        relatorio = OutboxDispatcher(repository, queue, settings).dispatch_once(limit=100)

        assert relatorio.dispatched == 5
        assert repository.count_pending_outbox() == 0
        assert queue.stats().pending == 5


class TestIdempotenciaNoConsumo:
    def test_reentrega_produz_um_unico_resultado(
        self,
        client: TestClient,
        repository: DynamoRecordRepository,
        queue: SqliteQueue,
        settings: Settings,
    ) -> None:
        """Criterio de aceite central da Fase 2, contra DynamoDB real."""
        resposta = client.post("/v1/records/person", json=PESSOA, headers=key()).json()
        record_id = resposta["record_id"]

        # Processador explicito e simples: o foco do teste e a reentrega, nao a
        # resolucao de identidade. O marcador e lido na versao desse processador.
        processador = DefaultProcessor()
        worker = Worker(repository, queue, processador, settings)
        assert worker.process_once().processed == 1
        primeiro = repository.find_processing_result(record_id, processador.version)

        # O outbox republica apos crash — ADR-003 admite explicitamente.
        queue.publish(QueueMessage("evento-republicado", record_id, "corr-bis"))
        segundo_relatorio = worker.process_once()

        assert segundo_relatorio.skipped_duplicate == 1
        assert segundo_relatorio.processed == 0

        atual = repository.find_processing_result(record_id, processador.version)
        assert atual is not None and primeiro is not None
        assert atual.processed_at == primeiro.processed_at
        assert atual.event_id == primeiro.event_id

    def test_processar_duas_vezes_e_seguro(self, client: TestClient) -> None:
        for i in range(5):
            client.post(
                "/v1/records/person",
                json={**PESSOA, "phone": f"(11) 92222-{i:04d}"},
                headers=key(),
            )
        client.post("/v1/ops/dispatch", json={"limit": 100})

        primeira = client.post("/v1/ops/process", json={"max_messages": 100}).json()
        segunda = client.post("/v1/ops/process", json={"max_messages": 100}).json()

        assert primeira["processed"] == 5
        assert segunda["received"] == 0


class TestFalhasEDlq:
    def test_falha_injetada_leva_a_dlq(
        self,
        client: TestClient,
        repository: DynamoRecordRepository,
        queue: SqliteQueue,
        settings: Settings,
    ) -> None:
        client.post("/v1/records/person", json=PESSOA, headers=key())

        class SempreFalha:
            version = "teste-v1"

            def process(self, record: Any) -> dict[str, Any]:
                raise ProcessingError("falha deliberada")

        worker = Worker(repository, queue, SempreFalha(), settings)
        for _ in range(settings.queue_max_receive):
            worker.process_once()
            time.sleep(0.05)

        stats = client.get("/v1/ops/queue").json()
        assert stats["dead"] == 1
        assert stats["pending"] == 0

    def test_redrive_e_reprocessamento(
        self,
        client: TestClient,
        repository: DynamoRecordRepository,
        queue: SqliteQueue,
        settings: Settings,
    ) -> None:
        record_id = client.post("/v1/records/person", json=PESSOA, headers=key()).json()[
            "record_id"
        ]

        class SempreFalha:
            version = "teste-v1"

            def process(self, record: Any) -> dict[str, Any]:
                raise ProcessingError("falha deliberada")

        falho = Worker(repository, queue, SempreFalha(), settings)
        for _ in range(settings.queue_max_receive):
            falho.process_once()
            time.sleep(0.05)
        assert client.get("/v1/ops/queue").json()["dead"] == 1

        assert client.post("/v1/ops/redrive", json={"limit": 10}).json()["redriven"] == 1
        assert client.post("/v1/ops/process", json={"max_messages": 10}).json()["processed"] == 1
        assert repository.find_processing_result(record_id, RESOLUTION_VERSION) is not None


class TestEndpointsDeOps:
    def test_queue_reporta_backend(self, client: TestClient) -> None:
        corpo = client.get("/v1/ops/queue").json()
        assert corpo["backend"] == "sqlite"
        assert corpo["enabled"] is True

    def test_metrics_inclui_profundidade_da_fila(self, client: TestClient) -> None:
        client.post("/v1/records/person", json=PESSOA, headers=key())
        corpo = client.get("/metrics").json()

        assert corpo["queue"]["pending"] == 1
        assert corpo["modules"]["queue_engine"] == "implemented"
        # Era "not_implemented" fixo no codigo desde a Fase 2; a Fase 5
        # implementou a resolucao e o campo so foi corrigido na Fase 4,
        # quando o Control Center o exibiu numa tela.
        assert corpo["modules"]["entity_resolution"] == "implemented"

    @pytest.mark.parametrize(
        ("rota", "corpo"),
        [
            ("/v1/ops/dispatch", {"limit": 0}),
            ("/v1/ops/dispatch", {"limit": 99999}),
            ("/v1/ops/process", {"max_messages": 0}),
            ("/v1/ops/process", {"max_messages": 99999}),
            ("/v1/ops/redrive", {"limit": 0}),
            ("/v1/ops/dispatch", {"campo_extra": 1}),
        ],
    )
    def test_limites_sao_aplicados(
        self, client: TestClient, rota: str, corpo: dict[str, Any]
    ) -> None:
        """Teto de lote e protecao de custo, nao detalhe de validacao."""
        assert client.post(rota, json=corpo).status_code == 422

    def test_endpoints_funcionam_sem_corpo(self, client: TestClient) -> None:
        assert client.post("/v1/ops/dispatch").status_code == 200
        assert client.post("/v1/ops/process").status_code == 200
        assert client.post("/v1/ops/redrive").status_code == 200
