"""Testes do tratamento de erro da API.

Separados dos testes de integracao porque nao precisam de persistencia real: o foco e
o que a API **devolve** quando algo falha, nao onde falhou.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from nexus.ingestion.api import app
from nexus.persistence import get_repository
from nexus.queue import get_queue_client
from nexus.shared.config import Settings, get_settings
from nexus.shared.errors import PersistenceError
from tests.fakes import FakeRepository, RecordingQueueClient

PESSOA = {"source": "t", "full_name": "Maria Souza", "document": "12345678909"}
CHAVE = {"Idempotency-Key": "k-erros"}


class QuebradoRepository(FakeRepository):
    """Repositorio que falha de forma inesperada, para exercitar o handler generico."""

    def find_idempotency(self, source: str, idempotency_key: str) -> None:
        raise RuntimeError("segredo interno: tabela nexus-prod-12345, ARN arn:aws:...")


@pytest.fixture
def client_quebrado() -> Iterator[TestClient]:
    app.dependency_overrides[get_repository] = lambda: QuebradoRepository()
    app.dependency_overrides[get_queue_client] = lambda: RecordingQueueClient()
    app.dependency_overrides[get_settings] = lambda: Settings()
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


class TestErroInesperado:
    def test_responde_500_sem_vazar_detalhe(self, client_quebrado: TestClient) -> None:
        """Stack trace, nome de tabela e ARN nunca podem chegar ao cliente."""
        resposta = client_quebrado.post("/v1/records/person", json=PESSOA, headers=CHAVE)

        assert resposta.status_code == 500
        corpo = resposta.json()
        assert corpo["code"] == "internal_error"
        assert corpo["message"] == "Erro interno"

        texto = resposta.text
        assert "nexus-prod-12345" not in texto
        assert "arn:aws" not in texto
        assert "Traceback" not in texto
        assert "RuntimeError" not in texto

    def test_devolve_correlation_id_rastreavel(self, client_quebrado: TestClient) -> None:
        """O cliente recebe algo citavel sem que nada interno seja exposto."""
        resposta = client_quebrado.post("/v1/records/person", json=PESSOA, headers=CHAVE)
        assert resposta.json()["correlation_id"]


class TestPersistenciaIndisponivel:
    def test_responde_503(self) -> None:
        class Indisponivel(FakeRepository):
            def find_idempotency(self, source: str, idempotency_key: str) -> None:
                raise PersistenceError("Falha ao acessar a camada de persistencia")

        app.dependency_overrides[get_repository] = lambda: Indisponivel()
        app.dependency_overrides[get_queue_client] = lambda: RecordingQueueClient()
        app.dependency_overrides[get_settings] = lambda: Settings()
        try:
            cliente = TestClient(app, raise_server_exceptions=False)
            resposta = cliente.post("/v1/records/person", json=PESSOA, headers=CHAVE)
            assert resposta.status_code == 503
            assert resposta.json()["code"] == "persistence_unavailable"
        finally:
            app.dependency_overrides.clear()

    def test_health_degradado(self) -> None:
        repo = FakeRepository()
        repo.ping_result = False
        app.dependency_overrides[get_repository] = lambda: repo
        app.dependency_overrides[get_queue_client] = lambda: RecordingQueueClient()
        app.dependency_overrides[get_settings] = lambda: Settings()
        try:
            corpo = TestClient(app).get("/health").json()
            assert corpo["status"] == "degraded"
            assert corpo["persistence"] == "unavailable"
        finally:
            app.dependency_overrides.clear()

    def test_metrics_sobrevive_a_falha_de_backlog(self) -> None:
        """Metricas nunca podem derrubar o endpoint que as expoe."""

        class SemBacklog(FakeRepository):
            def count_pending_outbox(self) -> int:
                raise PersistenceError("indisponivel")

        app.dependency_overrides[get_repository] = lambda: SemBacklog()
        app.dependency_overrides[get_queue_client] = lambda: RecordingQueueClient()
        app.dependency_overrides[get_settings] = lambda: Settings()
        try:
            resposta = TestClient(app).get("/metrics")
            assert resposta.status_code == 200
            assert resposta.json()["outbox_pending"] is None
        finally:
            app.dependency_overrides.clear()
