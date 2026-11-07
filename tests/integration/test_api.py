"""Testes ponta a ponta da API contra DynamoDB Local.

Exercitam o contrato HTTP completo descrito em ADR-002.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from fastapi.testclient import TestClient

from nexus.ingestion.api import app
from nexus.persistence import get_repository
from nexus.persistence.dynamo import DynamoRecordRepository
from nexus.queue import get_queue_client
from nexus.shared.config import Settings, get_settings
from tests.fakes import RecordingQueueClient

pytestmark = pytest.mark.integration

PESSOA: dict[str, Any] = {
    "source": "testes",
    "full_name": "Maria Aparecida Souza",
    "email": "maria.souza@example.com",
    "document": "123.456.789-09",
    "phone": "(11) 98765-4321",
}
ORGANIZACAO: dict[str, Any] = {
    "source": "testes",
    "legal_name": "Acme Servicos Ltda",
    "trade_name": "Acme",
    "email": "contato@example.com",
    "document": "12.345.678/0001-95",
    "country": "BR",
}


def key() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


@pytest.fixture
def queue() -> RecordingQueueClient:
    return RecordingQueueClient(enabled=True)


@pytest.fixture
def client(
    repository: DynamoRecordRepository, queue: RecordingQueueClient, settings: Settings
) -> Iterator[TestClient]:
    # A configuracao e injetada junto: ingestao e repositorio precisam concordar sobre
    # o numero de shards do outbox (ADR-003).
    app.dependency_overrides[get_repository] = lambda: repository
    app.dependency_overrides[get_queue_client] = lambda: queue
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.clear()


class TestIngestaoFelizCaminho:
    def test_pessoa_aceita_com_202(self, client: TestClient) -> None:
        resposta = client.post("/v1/records/person", json=PESSOA, headers=key())
        assert resposta.status_code == 202
        corpo = resposta.json()
        assert corpo["status"] == "accepted"
        assert corpo["record_type"] == "person"
        assert len(corpo["record_id"]) == 26
        assert corpo["correlation_id"]

    def test_organizacao_aceita_com_202(self, client: TestClient) -> None:
        resposta = client.post("/v1/records/organization", json=ORGANIZACAO, headers=key())
        assert resposta.status_code == 202
        assert resposta.json()["record_type"] == "organization"

    def test_normaliza_antes_de_persistir(self, client: TestClient) -> None:
        record_id = client.post("/v1/records/person", json=PESSOA, headers=key()).json()[
            "record_id"
        ]
        detalhe = client.get(f"/v1/records/{record_id}").json()

        assert detalhe["normalized"]["email"] == "maria.souza@example.com"
        assert detalhe["normalized"]["document"] == "12345678909"
        assert detalhe["normalized"]["phone"] == "11987654321"
        # O payload original e preservado: normalizacao nao destroi o que chegou.
        assert detalhe["payload"]["document"] == "123.456.789-09"

    def test_devolve_correlation_id_no_header(self, client: TestClient) -> None:
        resposta = client.post("/v1/records/person", json=PESSOA, headers=key())
        assert resposta.headers["X-Correlation-ID"]

    def test_respeita_correlation_id_do_cliente(self, client: TestClient) -> None:
        """Permite correlacionar com o sistema de origem."""
        headers = {**key(), "X-Correlation-ID": "trilha-externa-123"}
        resposta = client.post("/v1/records/person", json=PESSOA, headers=headers)
        assert resposta.headers["X-Correlation-ID"] == "trilha-externa-123"
        assert resposta.json()["correlation_id"] == "trilha-externa-123"


class TestIdempotencyKey:
    def test_header_ausente_e_400(self, client: TestClient) -> None:
        resposta = client.post("/v1/records/person", json=PESSOA)
        assert resposta.status_code == 400
        assert resposta.json()["code"] == "missing_idempotency_key"

    def test_header_vazio_e_400(self, client: TestClient) -> None:
        resposta = client.post(
            "/v1/records/person", json=PESSOA, headers={"Idempotency-Key": "   "}
        )
        assert resposta.status_code == 400

    def test_header_longo_demais_e_400(self, client: TestClient) -> None:
        resposta = client.post(
            "/v1/records/person", json=PESSOA, headers={"Idempotency-Key": "x" * 200}
        )
        assert resposta.status_code == 400

    def test_replay_devolve_mesma_resposta(self, client: TestClient) -> None:
        h = key()
        primeira = client.post("/v1/records/person", json=PESSOA, headers=h)
        segunda = client.post("/v1/records/person", json=PESSOA, headers=h)

        assert segunda.status_code == 202
        assert segunda.headers["Idempotency-Replayed"] == "true"
        assert segunda.json()["record_id"] == primeira.json()["record_id"]

    def test_chave_reusada_com_corpo_diferente_e_409(self, client: TestClient) -> None:
        h = key()
        client.post("/v1/records/person", json=PESSOA, headers=h)
        resposta = client.post(
            "/v1/records/person", json={**PESSOA, "phone": "(11) 90000-0000"}, headers=h
        )
        assert resposta.status_code == 409
        assert resposta.json()["code"] == "idempotency_conflict"


class TestDeduplicacaoDeConteudo:
    def test_conteudo_identico_e_marcado_duplicata(self, client: TestClient) -> None:
        client.post("/v1/records/person", json=PESSOA, headers=key())
        resposta = client.post("/v1/records/person", json=PESSOA, headers=key())

        assert resposta.status_code == 200
        assert resposta.json()["status"] == "duplicate"
        assert resposta.json()["seen_count"] == 2

    def test_variacao_de_formatacao_e_duplicata(self, client: TestClient) -> None:
        client.post("/v1/records/person", json=PESSOA, headers=key())
        ruidoso = {
            **PESSOA,
            "email": "MARIA.SOUZA@EXAMPLE.COM",
            "document": "12345678909",
            "phone": "11987654321",
            "full_name": "  Maria   Aparecida  Souza  ",
        }
        resposta = client.post("/v1/records/person", json=ruidoso, headers=key())
        assert resposta.json()["status"] == "duplicate"


class TestAtualizacaoLegitima:
    """Regressao do defeito corrigido pelo ADR-002."""

    def test_telefone_novo_gera_nova_observacao(self, client: TestClient) -> None:
        primeira = client.post("/v1/records/person", json=PESSOA, headers=key())
        segunda = client.post(
            "/v1/records/person", json={**PESSOA, "phone": "(11) 97777-6666"}, headers=key()
        )

        assert segunda.status_code == 202, "atualizacao legitima nao pode virar duplicata"
        assert segunda.json()["record_id"] != primeira.json()["record_id"]

    def test_as_duas_observacoes_ficam_consultaveis(self, client: TestClient) -> None:
        primeira = client.post("/v1/records/person", json=PESSOA, headers=key()).json()
        segunda = client.post(
            "/v1/records/person", json={**PESSOA, "phone": "(11) 97777-6666"}, headers=key()
        ).json()

        antiga = client.get(f"/v1/records/{primeira['record_id']}").json()
        nova = client.get(f"/v1/records/{segunda['record_id']}").json()

        assert antiga["normalized"]["phone"] == "11987654321"
        assert nova["normalized"]["phone"] == "11977776666"


class TestValidacao:
    @pytest.mark.parametrize(
        "corpo",
        [
            pytest.param({}, id="vazio"),
            pytest.param({"source": "testes"}, id="sem-nome"),
            pytest.param({**PESSOA, "full_name": ""}, id="nome-vazio"),
            pytest.param({**PESSOA, "email": "nao-eh-email"}, id="email-invalido"),
            pytest.param({**PESSOA, "campo_extra": 1}, id="campo-desconhecido"),
            pytest.param({**PESSOA, "full_name": 12345}, id="tipo-errado"),
            pytest.param({**PESSOA, "source": "fonte invalida!"}, id="fonte-invalida"),
            pytest.param({**PESSOA, "birth_date": "nao-eh-data"}, id="data-invalida"),
            pytest.param({**PESSOA, "full_name": "x" * 600}, id="campo-longo-demais"),
            pytest.param({**PESSOA, "full_name": "Ma\x00ria"}, id="byte-nulo"),
        ],
    )
    def test_payload_invalido_e_422(self, client: TestClient, corpo: dict[str, Any]) -> None:
        resposta = client.post("/v1/records/person", json=corpo, headers=key())
        assert resposta.status_code == 422
        assert resposta.json()["code"] == "validation_error"

    def test_resposta_de_erro_aponta_o_campo(self, client: TestClient) -> None:
        resposta = client.post("/v1/records/person", json={"source": "t"}, headers=key())
        campos = [item["field"] for item in resposta.json()["details"]["fields"]]
        assert "full_name" in campos

    def test_payload_gigante_nao_derruba(self, client: TestClient) -> None:
        """10 MB em um campo: deve ser recusado por validacao, nunca com 500."""
        resposta = client.post(
            "/v1/records/person", json={**PESSOA, "full_name": "a" * 10_000_000}, headers=key()
        )
        assert resposta.status_code == 422

    def test_texto_com_aparencia_de_injecao_e_tratado_como_dado(self, client: TestClient) -> None:
        malicioso = "Robert'); DROP TABLE records;--"
        resposta = client.post(
            "/v1/records/person", json={**PESSOA, "full_name": malicioso}, headers=key()
        )
        assert resposta.status_code == 202
        detalhe = client.get(f"/v1/records/{resposta.json()['record_id']}").json()
        assert detalhe["normalized"]["full_name"] == malicioso
        assert client.get("/health").json()["persistence"] == "ok"

    def test_unicode_e_emoji_sao_preservados(self, client: TestClient) -> None:
        nome = "José 🏪 Müller-Ávila"
        resposta = client.post(
            "/v1/records/person", json={**PESSOA, "full_name": nome}, headers=key()
        )
        assert resposta.status_code == 202
        detalhe = client.get(f"/v1/records/{resposta.json()['record_id']}").json()
        assert detalhe["normalized"]["full_name"] == nome


class TestConsulta:
    def test_inexistente_e_404(self, client: TestClient) -> None:
        resposta = client.get("/v1/records/01NAOEXISTE0000000000000AA")
        assert resposta.status_code == 404
        assert resposta.json()["code"] == "record_not_found"

    def test_listagem_pagina(self, client: TestClient) -> None:
        for i in range(5):
            client.post(
                "/v1/records/person",
                json={**PESSOA, "phone": f"(11) 98765-000{i}"},
                headers=key(),
            )

        primeira = client.get("/v1/records?limit=2").json()
        assert len(primeira["items"]) == 2
        assert primeira["next_cursor"]

        segunda = client.get(f"/v1/records?limit=2&cursor={primeira['next_cursor']}").json()
        ids_primeira = {i["record_id"] for i in primeira["items"]}
        ids_segunda = {i["record_id"] for i in segunda["items"]}
        assert not (ids_primeira & ids_segunda)

    def test_cursor_adulterado_e_400(self, client: TestClient) -> None:
        assert client.get("/v1/records?cursor=xxx-invalido").status_code == 400

    def test_limite_fora_da_faixa_e_422(self, client: TestClient) -> None:
        assert client.get("/v1/records?limit=0").status_code == 422
        assert client.get("/v1/records?limit=9999").status_code == 422


class TestObservabilidade:
    def test_health(self, client: TestClient) -> None:
        corpo = client.get("/health").json()
        assert corpo["status"] == "ok"
        assert corpo["persistence"] == "ok"
        assert corpo["environment"] == "local"

    def test_metrics_declara_escopo_e_modulos(self, client: TestClient) -> None:
        """Metricas nao podem se passar por agregadas de plataforma.

        O estado de cada modulo acompanha a realidade: a Fase 2 implementou o motor de
        filas, Entity Resolution continua sendo Fase 5.
        """
        client.post("/v1/records/person", json=PESSOA, headers=key())
        corpo = client.get("/metrics").json()

        assert corpo["scope"] == "in_process"
        assert corpo["modules"]["queue_engine"] == "implemented"
        assert corpo["modules"]["entity_resolution"] == "not_implemented"

    def test_metrics_declara_fila_desligada(
        self, repository: DynamoRecordRepository, settings: Settings
    ) -> None:
        app.dependency_overrides[get_repository] = lambda: repository
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_queue_client] = lambda: RecordingQueueClient(enabled=False)
        try:
            corpo = TestClient(app).get("/metrics").json()
            assert corpo["modules"]["queue_engine"] == "disabled"
        finally:
            app.dependency_overrides.clear()

    def test_metrics_expoe_percentis(self, client: TestClient) -> None:
        for _ in range(5):
            client.post("/v1/records/person", json=PESSOA, headers=key())
        latencias = client.get("/metrics").json()["latency_ms"]
        amostra = next(iter(latencias.values()))
        assert {"p50", "p95", "p99"} <= set(amostra)

    def test_metrics_agrupa_por_template_de_rota(self, client: TestClient) -> None:
        """Cada identificador nao pode virar uma serie propria."""
        for _ in range(3):
            rid = client.post(
                "/v1/records/person", json={**PESSOA, "phone": f"(11) 9{_}765-4321"}, headers=key()
            ).json()["record_id"]
            client.get(f"/v1/records/{rid}")

        chaves = client.get("/metrics").json()["counters"].keys()
        assert any("{record_id}" in chave for chave in chaves)


class TestOutbox:
    def test_evento_e_publicado_na_ingestao(
        self, client: TestClient, queue: RecordingQueueClient
    ) -> None:
        resposta = client.post("/v1/records/person", json=PESSOA, headers=key())
        assert len(queue.published) == 1
        assert queue.published[0].record_id == resposta.json()["record_id"]

    def test_backlog_zera_apos_publicacao(self, client: TestClient) -> None:
        client.post("/v1/records/person", json=PESSOA, headers=key())
        assert client.get("/metrics").json()["outbox_pending"] == 0

    def test_sem_fila_backlog_cresce(
        self, repository: DynamoRecordRepository, settings: Settings
    ) -> None:
        """Fase 1 sem fila: o evento fica pendente e o backlog fica visivel."""
        app.dependency_overrides[get_repository] = lambda: repository
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_queue_client] = lambda: RecordingQueueClient(enabled=False)
        try:
            cliente = TestClient(app, raise_server_exceptions=False)
            cliente.post("/v1/records/person", json=PESSOA, headers=key())
            assert cliente.get("/metrics").json()["outbox_pending"] == 1
        finally:
            app.dependency_overrides.clear()

    def test_falha_de_publicacao_nao_perde_o_registro(
        self, repository: DynamoRecordRepository, settings: Settings
    ) -> None:
        """A observacao esta persistida; o dispatcher recupera depois — ADR-003."""
        app.dependency_overrides[get_repository] = lambda: repository
        app.dependency_overrides[get_settings] = lambda: settings
        app.dependency_overrides[get_queue_client] = lambda: RecordingQueueClient(fail=True)
        try:
            cliente = TestClient(app, raise_server_exceptions=False)
            resposta = cliente.post("/v1/records/person", json=PESSOA, headers=key())
            assert resposta.status_code == 202
            assert cliente.get(f"/v1/records/{resposta.json()['record_id']}").status_code == 200
            assert cliente.get("/metrics").json()["outbox_pending"] == 1
        finally:
            app.dependency_overrides.clear()


class TestConcorrencia:
    def test_mesma_chave_em_paralelo_produz_uma_observacao(self, client: TestClient) -> None:
        """Criterio de aceite: 50 requisicoes simultaneas, exatamente uma observacao."""
        headers = key()

        def enviar(_: int) -> Any:
            return client.post("/v1/records/person", json=PESSOA, headers=headers)

        with ThreadPoolExecutor(max_workers=16) as pool:
            respostas = list(pool.map(enviar, range(50)))

        assert all(r.status_code in (200, 202) for r in respostas)
        ids = {r.json()["record_id"] for r in respostas}
        assert len(ids) == 1, f"esperava 1 observacao, obteve {len(ids)}"

        listagem = client.get("/v1/records?limit=100").json()
        assert len(listagem["items"]) == 1

    def test_chaves_distintas_em_paralelo_nao_quebram(self, client: TestClient) -> None:
        """Deduplicacao por conteudo e best-effort sob concorrencia.

        A busca por fingerprint le um indice secundario global, que e eventualmente
        consistente: requisicoes simultaneas podem nao enxergar a observacao uma da
        outra e criar mais de uma. Isso e aceito por desenho — a resolucao autoritativa
        de identidade e do Entity Resolution (ADR-002), nao da ingestao.

        O teste garante que nada falha e que o numero nao explode, nao que seja 1.
        """

        def enviar(_: int) -> Any:
            return client.post("/v1/records/person", json=PESSOA, headers=key())

        with ThreadPoolExecutor(max_workers=10) as pool:
            respostas = list(pool.map(enviar, range(20)))

        assert all(r.status_code in (200, 202) for r in respostas)
        total = len(client.get("/v1/records?limit=100").json()["items"])
        assert 1 <= total <= 20
