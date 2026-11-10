"""Testes da janela deslizante e dos alertas calculados — ADR-010."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest

from nexus.observability.alerts import AlertEvaluator, Origin, Severity
from nexus.observability.metrics import registry
from nexus.observability.series import PLATFORM_SERIES, MetricSampler
from nexus.persistence.models import OutboxEvent, OutboxStatus
from nexus.shared.clock import utcnow
from nexus.shared.config import Settings
from tests.fakes import FakeRepository, RecordingQueueClient


@pytest.fixture
def repo() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def obs_settings() -> Settings:
    return Settings(
        env="local",
        series_interval_seconds=15,
        series_retention_days=7,
        alert_outbox_backlog=5,
        alert_outbox_age_minutes=10,
        alert_error_rate=0.05,
        resolution_max_cluster_size=50,
    )


def pendente(repo: FakeRepository, event_id: str, *, idade_minutos: int = 0) -> None:
    quando = utcnow() - timedelta(minutes=idade_minutos)
    repo.events[event_id] = OutboxEvent(
        event_id=event_id,
        record_id=f"rec-{event_id}",
        correlation_id="corr",
        created_at=quando,
        next_attempt_at=quando,
        status=OutboxStatus.PENDING,
        pending_shard="PENDING#0",
    )


class TestBaldes:
    def test_instantes_do_mesmo_intervalo_caem_no_mesmo_balde(
        self, repo: FakeRepository, obs_settings: Settings
    ) -> None:
        """E o arredondamento que faz a escrita condicional colidir de proposito.

        Com o carimbo exato de cada observador, duas amostras nunca colidiriam e a
        densidade da serie mediria quantas abas do dashboard estao abertas.
        """
        sampler = MetricSampler(repo, RecordingQueueClient(enabled=True), obs_settings)
        base = datetime.fromtimestamp(1_800_000_000, tz=utcnow().tzinfo)

        baldes = {sampler.bucket_for(base + timedelta(seconds=s)) for s in range(15)}
        assert len(baldes) == 1

    def test_intervalos_diferentes_caem_em_baldes_diferentes(
        self, repo: FakeRepository, obs_settings: Settings
    ) -> None:
        sampler = MetricSampler(repo, RecordingQueueClient(enabled=True), obs_settings)
        base = datetime.fromtimestamp(1_800_000_000, tz=utcnow().tzinfo)

        assert sampler.bucket_for(base) != sampler.bucket_for(base + timedelta(seconds=15))


class TestAmostragem:
    def test_primeira_amostra_grava_a_profundidade(
        self, repo: FakeRepository, obs_settings: Settings
    ) -> None:
        pendente(repo, "e1")
        pendente(repo, "e2")
        fila = RecordingQueueClient(enabled=True)
        resultado = MetricSampler(repo, fila, obs_settings).sample()

        assert resultado.written is True
        assert resultado.values["outbox_pending"] == 2.0
        assert "queue_pending" in resultado.values

    def test_segunda_amostra_no_mesmo_balde_nao_grava(
        self, repo: FakeRepository, obs_settings: Settings
    ) -> None:
        sampler = MetricSampler(repo, RecordingQueueClient(enabled=True), obs_settings)
        assert sampler.sample().written is True

        segunda = sampler.sample()
        assert segunda.written is False
        assert "este processo" in segunda.reason
        assert len(repo.samples) == 1

    def test_force_ignora_a_memoria_local_mas_nao_a_condicao(
        self, repo: FakeRepository, obs_settings: Settings
    ) -> None:
        """``force`` serve ao Scheduler, que nao deve depender da memoria do processo.

        Mesmo assim o balde continua unico: a garantia e a escrita condicional, nunca
        a lembranca local.
        """
        sampler = MetricSampler(repo, RecordingQueueClient(enabled=True), obs_settings)
        sampler.sample()

        forcada = sampler.sample(force=True)
        assert forcada.written is False
        assert "outro observador" in forcada.reason
        assert len(repo.samples) == 1

    def test_observadores_concorrentes_produzem_uma_amostra(
        self, repo: FakeRepository, obs_settings: Settings
    ) -> None:
        """Oito processos distintos amostrando ao mesmo tempo — oito memorias locais
        vazias. So a escrita condicional impede oito amostras no mesmo instante."""
        pendente(repo, "e1")
        amostradores = [
            MetricSampler(repo, RecordingQueueClient(enabled=True), obs_settings) for _ in range(8)
        ]

        with ThreadPoolExecutor(max_workers=8) as pool:
            resultados = list(pool.map(lambda s: s.sample(), amostradores))

        assert sum(1 for r in resultados if r.written) == 1
        assert len(repo.samples) == 1

    def test_fonte_indisponivel_nao_vira_zero(
        self, repo: FakeRepository, obs_settings: Settings
    ) -> None:
        """Zero e um numero; "nao medido" nao e. Gravar zero por falha de leitura
        desenharia um vale no grafico onde houve apenas cegueira."""

        class SemContagem(FakeRepository):
            def count_pending_outbox(self) -> int:
                raise RuntimeError("tabela indisponivel")

        resultado = MetricSampler(
            SemContagem(), RecordingQueueClient(enabled=True), obs_settings
        ).sample()

        assert "outbox_pending" not in resultado.values
        assert resultado.written is True

    def test_serie_lida_vem_em_ordem(self, repo: FakeRepository, obs_settings: Settings) -> None:
        sampler = MetricSampler(repo, RecordingQueueClient(enabled=True), obs_settings)
        sampler.sample()
        serie = sampler.read(window_minutes=60)

        assert [s.metric for s in serie] == [PLATFORM_SERIES]
        assert serie[0].expires_at > int(utcnow().timestamp())


class TestAlertas:
    def test_plataforma_saudavel_nao_acende_nada(
        self, repo: FakeRepository, obs_settings: Settings
    ) -> None:
        ativos = AlertEvaluator(repo, RecordingQueueClient(enabled=True), obs_settings).evaluate()
        assert ativos == []

    def test_dlq_nao_vazia_acende_erro(self, repo: FakeRepository, obs_settings: Settings) -> None:
        fila = RecordingQueueClient(enabled=True)
        fila.dead_count = 3
        ativos = AlertEvaluator(repo, fila, obs_settings).evaluate()

        assert [a.id for a in ativos] == ["dlq_not_empty"]
        assert ativos[0].severity is Severity.ERROR
        assert ativos[0].value == 3.0

    def test_dlq_esvaziada_apaga_o_alerta(
        self, repo: FakeRepository, obs_settings: Settings
    ) -> None:
        fila = RecordingQueueClient(enabled=True)
        avaliador = AlertEvaluator(repo, fila, obs_settings)
        fila.dead_count = 1
        assert avaliador.evaluate() != []

        fila.dead_count = 0
        assert avaliador.evaluate() == []

    def test_backlog_acima_do_limite_acende_atencao(
        self, repo: FakeRepository, obs_settings: Settings
    ) -> None:
        for i in range(6):
            pendente(repo, f"e{i}")
        ativos = AlertEvaluator(repo, RecordingQueueClient(enabled=True), obs_settings).evaluate()

        assert [a.id for a in ativos] == ["outbox_backlog"]
        assert ativos[0].severity is Severity.WARNING
        assert ativos[0].threshold == 5.0

    def test_evento_parado_acende_mesmo_com_backlog_pequeno(
        self, repo: FakeRepository, obs_settings: Settings
    ) -> None:
        """Backlog grande e backlog parado sao problemas diferentes. Um evento parado
        ha meia hora nao dispara o alerta de volume e e o que perde dados pelo TTL."""
        pendente(repo, "e1", idade_minutos=30)
        ativos = AlertEvaluator(repo, RecordingQueueClient(enabled=True), obs_settings).evaluate()

        assert [a.id for a in ativos] == ["outbox_stalled"]
        assert ativos[0].value is not None and ativos[0].value >= 29

    def test_persistencia_indisponivel_e_o_unico_alerta_derivado_dela(
        self, repo: FakeRepository, obs_settings: Settings
    ) -> None:
        """Sem persistencia, backlog e idade nao sao avaliaveis. Acompanhar o erro de
        numeros inventados seria pior que nao os mostrar."""

        class Morto(FakeRepository):
            def ping(self) -> bool:
                return False

            def count_pending_outbox(self) -> int:
                raise AssertionError("nao deveria ser consultado")

        ativos = AlertEvaluator(
            Morto(), RecordingQueueClient(enabled=True), obs_settings
        ).evaluate()
        assert [a.id for a in ativos] == ["persistence_unavailable"]

    def test_teto_de_cluster_recusado_acende(
        self, repo: FakeRepository, obs_settings: Settings
    ) -> None:
        repo.increment_resolution_stats(refused_too_large=2)
        ativos = AlertEvaluator(repo, RecordingQueueClient(enabled=True), obs_settings).evaluate()

        assert [a.id for a in ativos] == ["cluster_cap_refusals"]

    def test_taxa_de_erro_declara_que_vive_no_processo(
        self, repo: FakeRepository, obs_settings: Settings
    ) -> None:
        for _ in range(30):
            registry.increment("http_requests_total", method="POST", path="/x", status="202")
        for _ in range(5):
            registry.increment("http_requests_total", method="POST", path="/x", status="500")

        ativos = AlertEvaluator(repo, RecordingQueueClient(enabled=True), obs_settings).evaluate()
        alerta = next(a for a in ativos if a.id == "http_error_rate")

        assert alerta.origin is Origin.PROCESS
        assert alerta.context == {"errors": 5, "requests": 35}

    def test_amostra_pequena_nao_acende_taxa_de_erro(
        self, repo: FakeRepository, obs_settings: Settings
    ) -> None:
        """Uma 500 em tres requisicoes daria 33% e nao significaria nada."""
        registry.increment("http_requests_total", method="POST", path="/x", status="202")
        registry.increment("http_requests_total", method="POST", path="/x", status="500")

        ativos = AlertEvaluator(repo, RecordingQueueClient(enabled=True), obs_settings).evaluate()
        assert [a.id for a in ativos] == []

    def test_erros_vem_antes_de_atencoes(
        self, repo: FakeRepository, obs_settings: Settings
    ) -> None:
        for i in range(6):
            pendente(repo, f"e{i}")
        fila = RecordingQueueClient(enabled=True)
        fila.dead_count = 1

        ativos = AlertEvaluator(repo, fila, obs_settings).evaluate()
        assert [a.severity for a in ativos] == [Severity.ERROR, Severity.WARNING]
