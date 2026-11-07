"""Testes de metricas, logging estruturado e erros."""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor

import pytest

from nexus.observability.metrics import MetricsRegistry, _percentile
from nexus.shared.errors import (
    IdempotencyConflictError,
    MissingIdempotencyKeyError,
    NexusError,
    PersistenceError,
    RecordNotFoundError,
)
from nexus.shared.logging import (
    JsonFormatter,
    get_correlation_id,
    new_correlation_id,
    set_correlation_id,
)


class TestMetricsRegistry:
    def test_conta(self) -> None:
        reg = MetricsRegistry()
        reg.increment("req")
        reg.increment("req", 4)
        assert reg.snapshot()["counters"]["req"] == 5

    def test_rotulos_geram_series_distintas(self) -> None:
        reg = MetricsRegistry()
        reg.increment("req", status="200")
        reg.increment("req", status="500")
        chaves = reg.snapshot()["counters"].keys()
        assert "req{status=200}" in chaves
        assert "req{status=500}" in chaves

    def test_rotulos_sao_ordenados(self) -> None:
        """Ordem estavel: a mesma combinacao nunca pode virar duas series."""
        reg = MetricsRegistry()
        reg.increment("r", a="1", b="2")
        reg.increment("r", b="2", a="1")
        assert reg.snapshot()["counters"]["r{a=1,b=2}"] == 2

    def test_resumo_de_latencia(self) -> None:
        reg = MetricsRegistry()
        for valor in range(1, 101):
            reg.observe("lat", float(valor))
        resumo = reg.snapshot()["latency_ms"]["lat"]
        assert resumo["count"] == 100
        assert resumo["min"] == 1.0
        assert resumo["max"] == 100.0
        assert resumo["p50"] <= resumo["p95"] <= resumo["p99"]

    def test_percentil_expoe_a_cauda(self) -> None:
        """A razao de usar percentil: a media esconde o que P99 revela."""
        reg = MetricsRegistry()
        for _ in range(95):
            reg.observe("lat", 10.0)
        for _ in range(5):
            reg.observe("lat", 2_000.0)
        resumo = reg.snapshot()["latency_ms"]["lat"]
        assert resumo["mean"] < 150
        assert resumo["p99"] == 2_000.0

    def test_memoria_limitada(self) -> None:
        """O registro nao pode crescer com o trafego."""
        reg = MetricsRegistry(max_samples=10)
        for valor in range(1_000):
            reg.observe("lat", float(valor))
        assert reg.snapshot()["latency_ms"]["lat"]["count"] == 10

    def test_reset(self) -> None:
        reg = MetricsRegistry()
        reg.increment("a")
        reg.observe("b", 1.0)
        reg.reset()
        assert reg.snapshot() == {"counters": {}, "latency_ms": {}}

    def test_serie_vazia_nao_quebra(self) -> None:
        assert _percentile([], 0.5) == 0.0

    def test_seguro_sob_concorrencia(self) -> None:
        reg = MetricsRegistry()
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: reg.increment("c"), range(2_000)))
        assert reg.snapshot()["counters"]["c"] == 2_000


class TestCorrelationId:
    def test_define_e_recupera(self) -> None:
        set_correlation_id("abc")
        assert get_correlation_id() == "abc"

    def test_identificadores_novos_sao_unicos(self) -> None:
        assert len({new_correlation_id() for _ in range(100)}) == 100


class TestJsonFormatter:
    def _formatar(self, record: logging.LogRecord) -> dict[str, object]:
        return json.loads(JsonFormatter("nexus-test").format(record))

    def _record(self, **extra: object) -> logging.LogRecord:
        record = logging.LogRecord("t", logging.INFO, "f.py", 1, "evento", None, None)
        record.__dict__.update(extra)
        return record

    def test_produz_json_valido(self) -> None:
        saida = self._formatar(self._record())
        assert saida["event"] == "evento"
        assert saida["level"] == "INFO"
        assert saida["service"] == "nexus-test"

    def test_inclui_correlation_id(self) -> None:
        set_correlation_id("corr-9")
        assert self._formatar(self._record())["correlation_id"] == "corr-9"

    def test_inclui_campos_extras(self) -> None:
        saida = self._formatar(self._record(record_id="01ABC", duration_ms=12.5))
        assert saida["record_id"] == "01ABC"
        assert saida["duration_ms"] == 12.5

    def test_valor_nao_serializavel_nao_quebra(self) -> None:
        """Log nunca pode derrubar a requisicao que ele descreve."""
        saida = self._formatar(self._record(objeto=object()))
        assert isinstance(saida["objeto"], str)

    def test_excecao_vai_para_o_log(self) -> None:
        try:
            raise ValueError("falha")
        except ValueError:
            import sys

            record = logging.LogRecord("t", logging.ERROR, "f.py", 1, "erro", None, sys.exc_info())
        assert "ValueError" in str(self._formatar(record)["exception"])


class TestErros:
    @pytest.mark.parametrize(
        ("erro", "status", "code"),
        [
            (MissingIdempotencyKeyError, 400, "missing_idempotency_key"),
            (IdempotencyConflictError, 409, "idempotency_conflict"),
            (RecordNotFoundError, 404, "record_not_found"),
            (PersistenceError, 503, "persistence_unavailable"),
            (NexusError, 500, "internal_error"),
        ],
    )
    def test_status_e_codigo(self, erro: type[NexusError], status: int, code: str) -> None:
        instancia = erro("mensagem")
        assert instancia.status_code == status
        assert instancia.code == code

    def test_payload_inclui_detalhes(self) -> None:
        erro = RecordNotFoundError("nao achei", details={"record_id": "x"})
        assert erro.to_payload() == {
            "code": "record_not_found",
            "message": "nao achei",
            "details": {"record_id": "x"},
        }

    def test_payload_omite_detalhes_vazios(self) -> None:
        assert "details" not in NexusError("x").to_payload()


class TestConfigureLogging:
    """O formato de uma linha JSON e o que torna os logs utilizaveis em Docker e
    CloudWatch. Uvicorn traz handlers proprios que quebram esse formato."""

    def test_instala_formatador_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        from nexus.shared.logging import configure_logging, get_logger

        configure_logging("INFO", "nexus-teste")
        set_correlation_id("corr-log")
        get_logger("t.unit").info("evento_de_teste", extra={"record_id": "01X"})

        linha = capsys.readouterr().out.strip().splitlines()[-1]
        payload = json.loads(linha)
        assert payload["event"] == "evento_de_teste"
        assert payload["service"] == "nexus-teste"
        assert payload["correlation_id"] == "corr-log"
        assert payload["record_id"] == "01X"

    def test_substitui_handlers_do_uvicorn(self) -> None:
        from nexus.shared.logging import configure_logging

        logging.getLogger("uvicorn.access").addHandler(logging.StreamHandler())
        configure_logging("INFO", "nexus-teste")
        assert logging.getLogger("uvicorn.access").handlers == []
        assert logging.getLogger("uvicorn.access").propagate is True

    def test_idempotente(self) -> None:
        from nexus.shared.logging import configure_logging

        configure_logging("INFO", "nexus-teste")
        configure_logging("DEBUG", "nexus-teste")
        assert len(logging.getLogger().handlers) == 1
        assert logging.getLogger().level == logging.DEBUG
