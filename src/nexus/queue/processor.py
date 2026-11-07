"""Processadores de registro.

O worker nao sabe o que significa "processar" — ele conhece apenas este contrato. E o
que permite a Fase 5 substituir o Entity Resolution sem tocar numa linha do motor de
filas: troca-se a implementacao, nao o mecanismo.
"""

from __future__ import annotations

import random
from typing import Any, Protocol, runtime_checkable

from nexus.persistence.models import StoredRecord
from nexus.shared.config import Settings, get_settings
from nexus.shared.logging import get_logger

logger = get_logger(__name__)


class ProcessingError(Exception):
    """Falha ao processar um registro. Leva a retentativa e, no limite, a DLQ."""


@runtime_checkable
class RecordProcessor(Protocol):
    """Unidade de trabalho aplicada a uma observacao."""

    def process(self, record: StoredRecord) -> dict[str, Any]:
        """Processa a observacao e devolve um resumo serializavel.

        :raises ProcessingError: falha recuperavel; a mensagem sera retentada.
        """
        ...


class DefaultProcessor:
    """Processador da Fase 2 — apenas mecanica de pipeline.

    **Nao resolve identidade.** Entity Resolution e escopo da Fase 5, e fingir aqui que
    ela existe seria anunciar uma capacidade nao implementada. O que este processador
    faz e real e verificavel: descreve a observacao e produz o resumo que fica gravado
    junto ao marcador.

    A Fase 5 substitui esta classe por um resolvedor que recebe o mesmo ``StoredRecord``
    e devolve correspondencias pontuadas, sem alterar worker, fila ou persistencia.
    """

    stage = "pipeline-only"

    def process(self, record: StoredRecord) -> dict[str, Any]:
        normalized = record.normalized
        return {
            "stage": self.stage,
            "entity_resolution": "not_implemented",
            "record_type": record.record_type.value,
            "source": record.source,
            "normalized_field_count": len(normalized),
            "has_document": bool(normalized.get("document")),
            "has_email": bool(normalized.get("email")),
            "has_phone": bool(normalized.get("phone")),
            "natural_key": record.natural_key,
        }


class FailureInjectingProcessor:
    """Envolve outro processador e falha a uma taxa configurada.

    Existe para exercitar retentativa, backoff e DLQ **sem adulterar os dados de
    entrada**. A alternativa comum — um campo magico no payload que dispara falha —
    mistura preocupacao de teste com contrato de dados e acaba vazando para producao.

    E tambem o mecanismo por tras do botao "Simular falhas" do Control Center.
    """

    def __init__(
        self,
        wrapped: RecordProcessor,
        rate: float,
        rng: random.Random | None = None,
    ) -> None:
        if not 0.0 <= rate <= 1.0:
            raise ValueError(f"taxa de injecao de falhas fora da faixa: {rate}")
        self._wrapped = wrapped
        self._rate = rate
        self._rng = rng or random.Random()

    @property
    def rate(self) -> float:
        return self._rate

    def process(self, record: StoredRecord) -> dict[str, Any]:
        if self._rng.random() < self._rate:
            logger.warning("failure_injected", extra={"record_id": record.record_id})
            raise ProcessingError(f"falha injetada deliberadamente (taxa={self._rate})")
        return self._wrapped.process(record)


def build_processor(settings: Settings | None = None) -> RecordProcessor:
    """Monta o processador configurado para o ambiente."""
    settings = settings or get_settings()
    base = DefaultProcessor()
    if settings.failure_injection_rate > 0:
        logger.warning(
            "failure_injection_enabled",
            extra={"rate": settings.failure_injection_rate},
        )
        return FailureInjectingProcessor(base, settings.failure_injection_rate)
    return base
