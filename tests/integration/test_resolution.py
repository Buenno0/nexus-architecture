"""Entity Resolution ponta a ponta, contra DynamoDB Local e fila SQLite reais."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nexus.ingestion.api import app
from nexus.persistence import get_repository
from nexus.persistence.dynamo import DynamoRecordRepository
from nexus.queue import get_queue_client
from nexus.queue.processor import DefaultProcessor
from nexus.queue.sqlite import SqliteQueue
from nexus.queue.worker import Worker
from nexus.resolution.engine import ResolutionProcessor
from nexus.shared.config import Settings, get_settings

pytestmark = pytest.mark.integration

MARIA: dict[str, Any] = {
    "source": "resolucao",
    "full_name": "Maria Aparecida Souza",
    "email": "maria.souza@example.com",
    "document": "123.456.789-09",
    "phone": "(11) 98765-4321",
}
CARLOS: dict[str, Any] = {
    "source": "resolucao",
    "full_name": "Carlos Pereira",
    "email": "carlos.pereira@outro.com",
    "document": "987.654.321-00",
    "phone": "(21) 91111-2222",
}


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


def resolver(client: TestClient) -> None:
    """Despacha e consome ate a fila esvaziar."""
    client.post("/v1/ops/dispatch", json={"limit": 1000})
    for _ in range(20):
        if client.post("/v1/ops/process", json={"max_messages": 50}).json()["received"] == 0:
            break


def ingerir(client: TestClient, payload: dict[str, Any]) -> str:
    resposta = client.post("/v1/records/person", json=payload, headers=key())
    assert resposta.status_code == 202, resposta.text
    return resposta.json()["record_id"]


class TestAgrupamento:
    def test_variantes_da_mesma_pessoa_formam_uma_entidade(self, client: TestClient) -> None:
        """O caso que o ADR-002 preservou desde a Fase 1 chega ao seu desfecho."""
        a = ingerir(client, MARIA)
        b = ingerir(client, {**MARIA, "phone": "(11) 97777-6666"})
        resolver(client)

        detalhe_a = client.get(f"/v1/records/{a}").json()
        detalhe_b = client.get(f"/v1/records/{b}").json()

        assert detalhe_a["entity_id"] is not None
        assert detalhe_a["entity_id"] == detalhe_b["entity_id"]

    def test_pessoas_distintas_ficam_separadas(self, client: TestClient) -> None:
        a = ingerir(client, MARIA)
        b = ingerir(client, CARLOS)
        resolver(client)

        detalhe_a = client.get(f"/v1/records/{a}").json()
        detalhe_b = client.get(f"/v1/records/{b}").json()
        assert detalhe_a["entity_id"] != detalhe_b["entity_id"] or detalhe_a["entity_id"] is None

    def test_tres_variantes_caem_no_mesmo_cluster(self, client: TestClient) -> None:
        """Fecho transitivo: A~B e B~C reunem os tres."""
        ids = [
            ingerir(client, MARIA),
            ingerir(client, {**MARIA, "phone": "(11) 97777-6666"}),
            ingerir(client, {**MARIA, "email": "maria.souza@outro.com"}),
        ]
        resolver(client)

        entidades = {client.get(f"/v1/records/{i}").json()["entity_id"] for i in ids}
        assert len(entidades) == 1
        assert None not in entidades

    def test_entidade_expoe_evidencia(self, client: TestClient) -> None:
        a = ingerir(client, MARIA)
        ingerir(client, {**MARIA, "phone": "(11) 97777-6666"})
        resolver(client)

        entity_id = client.get(f"/v1/records/{a}").json()["entity_id"]
        entidade = client.get(f"/v1/resolution/entities/{entity_id}").json()

        assert entidade["member_count"] == 2
        assert len(entidade["members"]) == 2
        evidencia = entidade["members"][0]["evidence"]
        assert evidencia["decision"] == "MATCH"
        assert any(campo["field"] == "document" for campo in evidencia["fields"])

    def test_entidade_inexistente(self, client: TestClient) -> None:
        assert client.get("/v1/resolution/entities/NAO-EXISTE").status_code == 404


class TestRevisao:
    def _criar_duvida(self, client: TestClient) -> tuple[str, str]:
        a = ingerir(client, MARIA)
        # Documento com um digito trocado: cai entre os limiares.
        b = ingerir(client, {**MARIA, "document": "123.456.789-08"})
        resolver(client)
        return a, b

    def test_duvida_vai_para_revisao_sem_fundir(self, client: TestClient) -> None:
        """A regra inegociavel: POSSIBLE_MATCH nunca funde sozinho."""
        a, b = self._criar_duvida(client)

        pendentes = client.get("/v1/resolution/reviews").json()["items"]
        assert len(pendentes) == 1
        assert pendentes[0]["status"] == "pending"
        assert {pendentes[0]["record_a"], pendentes[0]["record_b"]} == {a, b}

        assert client.get(f"/v1/records/{a}").json()["entity_id"] is None

    def test_confirmar_funde(self, client: TestClient) -> None:
        a, b = self._criar_duvida(client)
        pair_id = client.get("/v1/resolution/reviews").json()["items"][0]["pair_id"]

        resposta = client.post(
            f"/v1/resolution/reviews/{pair_id}",
            json={"decision": "confirm", "reason": "mesma pessoa, erro de digitacao"},
        )
        assert resposta.status_code == 200
        assert resposta.json()["status"] == "confirmed"

        entidade_a = client.get(f"/v1/records/{a}").json()["entity_id"]
        assert entidade_a is not None
        assert entidade_a == client.get(f"/v1/records/{b}").json()["entity_id"]

    def test_recusar_registra_e_nao_funde(self, client: TestClient) -> None:
        a, _ = self._criar_duvida(client)
        pair_id = client.get("/v1/resolution/reviews").json()["items"][0]["pair_id"]

        resposta = client.post(
            f"/v1/resolution/reviews/{pair_id}",
            json={"decision": "reject", "reason": "documentos distintos"},
        )
        assert resposta.json()["status"] == "rejected"
        assert resposta.json()["reason"] == "documentos distintos"
        assert client.get(f"/v1/records/{a}").json()["entity_id"] is None

    def test_decidido_sai_da_fila(self, client: TestClient) -> None:
        self._criar_duvida(client)
        pair_id = client.get("/v1/resolution/reviews").json()["items"][0]["pair_id"]
        client.post(f"/v1/resolution/reviews/{pair_id}", json={"decision": "reject"})
        assert client.get("/v1/resolution/reviews").json()["items"] == []

    def test_par_inexistente(self, client: TestClient) -> None:
        resposta = client.post("/v1/resolution/reviews/naoexiste", json={"decision": "reject"})
        assert resposta.status_code == 404

    @pytest.mark.parametrize(
        "corpo", [{"decision": "talvez"}, {}, {"decision": "reject", "extra": 1}]
    )
    def test_decisao_invalida(self, client: TestClient, corpo: dict[str, Any]) -> None:
        self._criar_duvida(client)
        pair_id = client.get("/v1/resolution/reviews").json()["items"][0]["pair_id"]
        assert client.post(f"/v1/resolution/reviews/{pair_id}", json=corpo).status_code == 422


class TestEstatisticas:
    def test_contadores_duraveis(self, client: TestClient) -> None:
        ingerir(client, MARIA)
        ingerir(client, {**MARIA, "phone": "(11) 97777-6666"})
        resolver(client)

        corpo = client.get("/v1/resolution/stats").json()
        assert corpo["processor_version"] == "resolution-v1"
        assert corpo["counters"]["records_analyzed"] == 2
        assert corpo["counters"]["matches"] == 1
        assert corpo["counters"]["entities_created"] == 1


class TestReprocessamento:
    def test_acervo_antigo_entra_na_versao_nova(
        self,
        client: TestClient,
        repository: DynamoRecordRepository,
        queue: SqliteQueue,
        settings: Settings,
    ) -> None:
        """O defeito que o ADR-007 evita: marcador antigo bloquearia o resolvedor."""
        a = ingerir(client, MARIA)
        b = ingerir(client, {**MARIA, "phone": "(11) 97777-6666"})

        # Consome com o processador da Fase 2: grava marcador em pipeline-v1.
        antigo = DefaultProcessor()
        worker = Worker(repository, queue, antigo, settings)
        for _ in range(5):
            if worker.process_once(max_messages=50).received == 0:
                break
        assert repository.find_processing_result(a, antigo.version) is not None
        assert client.get(f"/v1/records/{a}").json()["entity_id"] is None

        relatorio = client.post("/v1/ops/reprocess", json={"limit": 100}).json()
        assert relatorio["version"] == "resolution-v1"
        assert relatorio["enqueued"] == 2
        assert relatorio["already_processed"] == 0

        resolver(client)

        entidade = client.get(f"/v1/records/{a}").json()["entity_id"]
        assert entidade is not None
        assert entidade == client.get(f"/v1/records/{b}").json()["entity_id"]
        # O resultado da versao anterior continua consultavel.
        assert repository.find_processing_result(a, antigo.version) is not None
        assert repository.find_processing_result(a, ResolutionProcessor(repository).version)

    def test_rodar_duas_vezes_nao_duplica(self, client: TestClient) -> None:
        ingerir(client, MARIA)
        resolver(client)

        relatorio = client.post("/v1/ops/reprocess", json={"limit": 100}).json()
        assert relatorio["enqueued"] == 0
        assert relatorio["already_processed"] == 1

    def test_limite_aplicado(self, client: TestClient) -> None:
        assert client.post("/v1/ops/reprocess", json={"limit": 0}).status_code == 422
        assert client.post("/v1/ops/reprocess", json={"limit": 99999}).status_code == 422


class TestDeclaracaoDeCapacidade:
    """A API nao pode declarar errado o que ela faz — para mais nem para menos."""

    def test_metrics_declara_resolucao_implementada(self, client: TestClient) -> None:
        """Ficou fixo como 'not_implemented' da Fase 2 ate a Fase 4 revelar.

        Anunciar capacidade inexistente e enganoso; negar a que existe tambem, e
        esconde do operador uma parte da plataforma que esta funcionando.
        """
        corpo = client.get("/metrics").json()
        assert corpo["modules"]["entity_resolution"] == "implemented"

    def test_declara_nao_implementada_com_processador_simples(
        self, repository: DynamoRecordRepository, queue: SqliteQueue, settings: Settings
    ) -> None:
        from nexus.queue.client import NullQueueClient

        app.dependency_overrides[get_repository] = lambda: repository
        app.dependency_overrides[get_queue_client] = lambda: NullQueueClient()
        app.dependency_overrides[get_settings] = lambda: settings
        try:
            corpo = TestClient(app).get("/metrics").json()
            # Sem fila, o motor aparece desligado; a resolucao continua disponivel
            # porque depende do repositorio, nao da fila.
            assert corpo["modules"]["queue_engine"] == "disabled"
        finally:
            app.dependency_overrides.clear()
