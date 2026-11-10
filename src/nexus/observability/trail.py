"""Emissao de marcos da trilha — ADR-010.

Um objeto fino sobre o repositorio, com duas responsabilidades:

1. **Carimbar quem emitiu.** O valor da trilha esta em atravessar processos; saber que
   `consumed` veio do worker e `accepted` da API e parte da informacao.
2. **Garantir que a trilha nunca derruba o que observa.** O repositorio ja engole
   falhas de I/O; aqui tambem se engole erro de programacao, como um detalhe que nao
   serializa. Observabilidade que quebra a operacao observada e pior que nenhuma.
"""

from __future__ import annotations

from typing import Any

from nexus.persistence.models import TrailEvent, TrailStage
from nexus.persistence.repository import RecordRepository
from nexus.shared.clock import utcnow
from nexus.shared.logging import get_correlation_id, get_logger

logger = get_logger(__name__)


class TrailRecorder:
    """Registra marcos da jornada de uma observacao."""

    def __init__(self, repository: RecordRepository, service: str) -> None:
        self._repo = repository
        self._service = service

    def marcar(
        self,
        record_id: str,
        stage: TrailStage,
        *,
        correlation_id: str | None = None,
        **detail: Any,
    ) -> None:
        """Registra um marco. Nunca levanta.

        ``correlation_id`` e explicito porque quem chama costuma te-lo em maos — veio
        no cabecalho da requisicao ou na mensagem da fila. A variavel de contexto e so
        o recurso de ultimo caso: ela acerta quando o middleware a preencheu e erra em
        silencio quando nao, gravando o identificador de outra requisicao.
        """
        try:
            evento = TrailEvent(
                record_id=record_id,
                stage=stage,
                occurred_at=utcnow(),
                correlation_id=correlation_id or get_correlation_id() or "",
                service=self._service,
                detail={k: v for k, v in detail.items() if v is not None},
            )
            self._repo.record_trail(evento)
        except Exception as exc:  # ver docstring do modulo
            logger.warning(
                "trail_record_failed",
                extra={"record_id": record_id, "stage": stage.value, "reason": str(exc)},
            )
