"""Testes das rotas de observabilidade — ADR-010."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from nexus.ingestion.api import app
from nexus.persistence import get_repository
from nexus.persistence.models import OutboxEvent, OutboxStatus, TrailEvent, TrailStage
from nexus.queue import get_queue_client
from nexus.shared.clock import utcnow
from nexus.shared.config import Settings, get_settings
from tests.fakes import FakeRepository, RecordingQueueClient

PESSOA = {"source": "t", "full_name": "Maria Souza", "document": "12345678909"}


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def fila() -> RecordingQueueClient:
    return RecordingQueueClient(enabled=True)


@pytest.fixture
def obs_settings() -> Settings:
    return Settings(
        env="local",
        series_interval_seconds=15,
        alert_outbox_backlog=5,
        alert_outbox_age_minutes=10,
    )


@pytest.fixture
def client(
    repo: FakeRepository, fila: RecordingQueueClient, obs_settings: Settings
) -> Iterator[TestClient]:
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_queue_client] = lambda: fila
    app.dependency_overrides[get_settings] = lambda: obs_settings
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def marco(repo: FakeRepository, stage: TrailStage, *, offset_ms: int, service: str) -> None:
    repo.record_trail(
        TrailEvent(
            record_id="rec-1",
            stage=stage,
            occurred_at=utcnow() + timedelta(milliseconds=offset_ms),
            correlation_id="corr-1",
            service=service,
            detail={},
            event_id=f"evt-{offset_ms}",
        )
    )


class TestTrail:
    def test_devolve_a_jornada_em_ordem_com_deltas(
        self, client: TestClient, repo: FakeRepository
    ) -> None:
        marco(repo, TrailStage.ACCEPTED, offset_ms=0, service="api")
        marco(repo, TrailStage.PUBLISHED, offset_ms=40, service="api")
        marco(repo, TrailStage.CONSUMED, offset_ms=7000, service="worker")
        marco(repo, TrailStage.RESOLVED, offset_ms=7060, service="worker")

        corpo = client.get("/v1/observability/trail/rec-1").json()

        assert [e["stage"] for e in corpo["events"]] == [
            "accepted",
            "published",
            "consumed",
            "resolved",
        ]
        assert corpo["events"][0]["delta_ms"] is None
        assert corpo["total_ms"] == pytest.approx(7060, abs=1)

    def test_o_delta_localiza_o_gargalo_que_o_total_esconde(
        self, client: TestClient, repo: FakeRepository
    ) -> None:
        """Sete dos sete segundos foram espera na fila, nao processamento.

        O total nao distingue os dois; otimizar o processador nao recuperaria nada.
        """
        marco(repo, TrailStage.ACCEPTED, offset_ms=0, service="api")
        marco(repo, TrailStage.PUBLISHED, offset_ms=40, service="api")
        marco(repo, TrailStage.CONSUMED, offset_ms=7000, service="worker")
        marco(repo, TrailStage.RESOLVED, offset_ms=7060, service="worker")

        eventos = client.get("/v1/observability/trail/rec-1").json()["events"]
        espera = next(e for e in eventos if e["stage"] == "consumed")["delta_ms"]

        assert espera == pytest.approx(6960, abs=1)

    def test_declara_os_processos_que_contribuiram(
        self, client: TestClient, repo: FakeRepository
    ) -> None:
        marco(repo, TrailStage.ACCEPTED, offset_ms=0, service="api")
        marco(repo, TrailStage.CONSUMED, offset_ms=10, service="worker")

        assert client.get("/v1/observability/trail/rec-1").json()["services"] == ["api", "worker"]

    def test_registro_sem_trilha_responde_200_vazio(self, client: TestClient) -> None:
        """A trilha e best-effort e expira em sete dias. Um 404 sugeriria que o
        registro nao existe, o que e outra afirmacao — e provavelmente falsa."""
        resposta = client.get("/v1/observability/trail/rec-sem-trilha")

        assert resposta.status_code == 200
        assert resposta.json() == {
            "record_id": "rec-sem-trilha",
            "events": [],
            "total_ms": None,
            "services": [],
        }


class TestSeries:
    def test_declara_origem_persistida(self, client: TestClient) -> None:
        corpo = client.get("/v1/observability/series?window=60").json()

        assert corpo["origin"] == "persistido"
        assert corpo["interval_seconds"] == 15

    def test_janela_sem_amostra_declara_o_buraco(self, client: TestClient) -> None:
        """Amostragem oportunista: plataforma parada, serie vazia. O numero de
        buracos existe para a interface explicar, em vez de interpolar uma reta."""
        corpo = client.get("/v1/observability/series?window=15").json()

        assert corpo["points"] == []
        assert corpo["gaps"] == (15 * 60) // 15

    def test_amostra_gravada_aparece_na_serie(self, client: TestClient) -> None:
        client.get("/metrics")  # amostragem oportunista
        corpo = client.get("/v1/observability/series?window=60").json()

        assert len(corpo["points"]) == 1
        assert "outbox_pending" in corpo["points"][0]["values"]

    def test_serie_sobrevive_a_novo_cliente(
        self, repo: FakeRepository, fila: RecordingQueueClient, obs_settings: Settings
    ) -> None:
        """O equivalente a recarregar a pagina: a Fase 4 perdia o historico aqui."""
        app.dependency_overrides[get_repository] = lambda: repo
        app.dependency_overrides[get_queue_client] = lambda: fila
        app.dependency_overrides[get_settings] = lambda: obs_settings
        try:
            with TestClient(app) as primeiro:
                primeiro.get("/metrics")
            with TestClient(app) as segundo:
                corpo = segundo.get("/v1/observability/series?window=60").json()
        finally:
            app.dependency_overrides.clear()

        assert len(corpo["points"]) == 1


class TestAlerts:
    def test_plataforma_saudavel_devolve_lista_vazia(self, client: TestClient) -> None:
        corpo = client.get("/v1/observability/alerts").json()

        assert corpo["alerts"] == []
        assert "evaluated_at" in corpo

    def test_dlq_acende_e_apaga(self, client: TestClient, fila: RecordingQueueClient) -> None:
        fila.dead_count = 2
        acesos = client.get("/v1/observability/alerts").json()["alerts"]
        assert [a["id"] for a in acesos] == ["dlq_not_empty"]
        assert acesos[0]["severity"] == "error"

        fila.dead_count = 0
        assert client.get("/v1/observability/alerts").json()["alerts"] == []

    def test_cada_alerta_declara_a_origem_do_numero(
        self, client: TestClient, repo: FakeRepository
    ) -> None:
        """Regra do ADR-009: numero sem origem nao vai para a tela."""
        agora = utcnow()
        for i in range(6):
            repo.events[f"e{i}"] = OutboxEvent(
                event_id=f"e{i}",
                record_id=f"rec-{i}",
                correlation_id="c",
                created_at=agora,
                next_attempt_at=agora,
                status=OutboxStatus.PENDING,
                pending_shard="PENDING#0",
            )

        alertas = client.get("/v1/observability/alerts").json()["alerts"]
        assert all(a["origin"] in {"persistido", "processo"} for a in alertas)
        assert [a["id"] for a in alertas] == ["outbox_backlog"]


class TestOpsSample:
    def test_forca_amostra_e_informa_o_balde(self, client: TestClient) -> None:
        corpo = client.post("/v1/ops/sample").json()

        assert corpo["written"] is True
        assert "outbox_pending" in corpo["values"]

    def test_segunda_amostra_no_mesmo_balde_e_recusada_com_motivo(self, client: TestClient) -> None:
        """``force`` dribla a memoria do processo, nunca a condicao de escrita."""
        client.post("/v1/ops/sample")
        corpo = client.post("/v1/ops/sample").json()

        assert corpo["written"] is False
        assert "ocupado" in corpo["reason"]


class TestMetricsDeclaraObservabilidade:
    def test_modulo_passa_a_implementado(self, client: TestClient) -> None:
        """Era "partial" enquanto a trilha nao existia. Derivar o status do que de
        fato esta montado e o que impede a repeticao do defeito da Fase 4."""
        corpo = client.get("/metrics").json()

        assert corpo["modules"]["observability"] == "implemented"
        assert corpo["series_sampled"] is True


class TestSaudeDeclaraAConfiguracao:
    """`/health` diz se a trilha esta gravando — e o rotulo de toda corrida de carga.

    Um resultado de desempenho que nao diz se a instrumentacao estava ligada nao pode
    ser comparado com nenhum outro. O valor e derivado da configuracao efetiva, nunca
    de um rotulo informado por quem mede.
    """

    def test_reflete_a_trilha_ligada(self, client: TestClient) -> None:
        assert client.get("/health").json()["trail_enabled"] is True

    def test_reflete_a_trilha_desligada(
        self, repo: FakeRepository, fila: RecordingQueueClient
    ) -> None:
        desligado = Settings(env="local", trail_enabled=False)
        app.dependency_overrides[get_repository] = lambda: repo
        app.dependency_overrides[get_queue_client] = lambda: fila
        app.dependency_overrides[get_settings] = lambda: desligado
        try:
            with TestClient(app) as cliente:
                assert cliente.get("/health").json()["trail_enabled"] is False
        finally:
            app.dependency_overrides.clear()
