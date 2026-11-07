"""Testes dos processadores de registro."""

from __future__ import annotations

import random

import pytest

from nexus.persistence.models import RecordType, StoredRecord
from nexus.queue.processor import (
    DefaultProcessor,
    FailureInjectingProcessor,
    ProcessingError,
    build_processor,
)
from nexus.shared.clock import utcnow
from nexus.shared.config import Settings


def record(**extra: object) -> StoredRecord:
    normalized = {"document": "123", "email": "a@b.com", **extra}
    return StoredRecord(
        record_id="01REC",
        record_type=RecordType.PERSON,
        source="testes",
        natural_key="person|document|abc",
        record_fingerprint="fp",
        payload=normalized,
        normalized=normalized,
        correlation_id="corr",
        created_at=utcnow(),
    )


class TestDefaultProcessor:
    def test_descreve_a_observacao(self) -> None:
        resumo = DefaultProcessor().process(record())
        assert resumo["record_type"] == "person"
        assert resumo["normalized_field_count"] == 2
        assert resumo["has_document"] is True
        assert resumo["has_phone"] is False

    def test_declara_que_nao_resolve_identidade(self) -> None:
        """O resumo nao pode sugerir uma capacidade que so existe na Fase 5."""
        resumo = DefaultProcessor().process(record())
        assert resumo["entity_resolution"] == "not_implemented"
        assert resumo["stage"] == "pipeline-only"

    def test_resumo_e_serializavel(self) -> None:
        import json

        json.dumps(DefaultProcessor().process(record()))


class TestFailureInjectingProcessor:
    def test_taxa_zero_nunca_falha(self) -> None:
        processador = FailureInjectingProcessor(DefaultProcessor(), 0.0)
        for _ in range(50):
            processador.process(record())

    def test_taxa_um_sempre_falha(self) -> None:
        processador = FailureInjectingProcessor(DefaultProcessor(), 1.0)
        with pytest.raises(ProcessingError, match="injetada"):
            processador.process(record())

    def test_taxa_intermediaria_e_aproximada(self) -> None:
        processador = FailureInjectingProcessor(DefaultProcessor(), 0.5, random.Random(42))
        falhas = 0
        for _ in range(400):
            try:
                processador.process(record())
            except ProcessingError:
                falhas += 1
        assert 150 < falhas < 250

    @pytest.mark.parametrize("taxa", [-0.1, 1.1])
    def test_taxa_invalida(self, taxa: float) -> None:
        with pytest.raises(ValueError, match="fora da faixa"):
            FailureInjectingProcessor(DefaultProcessor(), taxa)


class TestBuildProcessor:
    def test_padrao_nao_injeta_falhas(self) -> None:
        assert isinstance(build_processor(Settings()), DefaultProcessor)

    def test_taxa_configurada_envolve_o_processador(self) -> None:
        processador = build_processor(Settings(failure_injection_rate=0.5))
        assert isinstance(processador, FailureInjectingProcessor)
        assert processador.rate == 0.5
