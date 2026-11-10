"""Dispatcher do outbox — ADR-003.

Varre o indice esparso de eventos pendentes, publica na fila e remove o atributo que
mantem o item no indice. E a rede de seguranca da publicacao inline da ingestao: tudo
que nao foi publicado no caminho feliz passa por aqui.

Executa **sob demanda**, nunca em laco continuo. Um processo em polling consome recurso
com fila vazia — exatamente o que COSTS.md manda evitar.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from nexus.observability.metrics import registry
from nexus.observability.trail import TrailRecorder
from nexus.persistence.models import TrailStage
from nexus.persistence.repository import RecordRepository
from nexus.queue.client import QueueClient, QueueMessage
from nexus.shared.clock import utcnow
from nexus.shared.config import Settings, get_settings
from nexus.shared.logging import configure_logging, get_logger, set_correlation_id

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DispatchReport:
    """Resultado de uma passada do dispatcher."""

    scanned: int = 0
    dispatched: int = 0
    duplicates: int = 0
    rescheduled: int = 0
    missing: int = 0

    def render(self) -> str:
        return (
            f"varridos={self.scanned}  despachados={self.dispatched}  "
            f"duplicados={self.duplicates}  reagendados={self.rescheduled}  "
            f"ausentes={self.missing}"
        )


class OutboxDispatcher:
    """Publica eventos pendentes do outbox na fila."""

    def __init__(
        self,
        repository: RecordRepository,
        queue: QueueClient,
        settings: Settings | None = None,
        trail: TrailRecorder | None = None,
    ) -> None:
        self._repo = repository
        self._queue = queue
        self._settings = settings or get_settings()
        self._trail = trail or TrailRecorder(repository, "dispatcher")

    def dispatch_once(self, *, limit: int | None = None) -> DispatchReport:
        """Publica ate ``limit`` eventos pendentes e devolve o relatorio."""
        if not self._queue.is_enabled:
            logger.info("dispatch_skipped_no_queue")
            return DispatchReport()

        budget = limit if limit is not None else self._settings.outbox_dispatch_batch_size
        scanned = dispatched = duplicates = rescheduled = missing = 0
        now = utcnow()

        for shard_index in range(self._settings.outbox_shards):
            if budget <= 0:
                break
            shard = f"PENDING#{shard_index}"
            event_ids = self._repo.list_pending_outbox(shard, limit=budget, now=now)

            for event_id in event_ids:
                budget -= 1
                scanned += 1
                outcome = self._dispatch_event(event_id)
                if outcome == "dispatched":
                    dispatched += 1
                elif outcome == "duplicate":
                    duplicates += 1
                elif outcome == "rescheduled":
                    rescheduled += 1
                else:
                    missing += 1

        report = DispatchReport(scanned, dispatched, duplicates, rescheduled, missing)
        registry.increment("outbox_dispatched_total", dispatched)
        logger.info(
            "dispatch_completed",
            extra={
                "scanned": scanned,
                "dispatched": dispatched,
                "duplicates": duplicates,
                "rescheduled": rescheduled,
                "missing": missing,
            },
        )
        return report

    def _dispatch_event(self, event_id: str) -> str:
        event = self._repo.get_outbox_event(event_id)
        if event is None:
            # O indice e eventualmente consistente: pode listar um evento que a tabela
            # base ja nao tem. Nada a fazer alem de registrar.
            logger.warning("dispatch_event_missing", extra={"event_id": event_id})
            return "missing"

        set_correlation_id(event.correlation_id)
        message = QueueMessage(event.event_id, event.record_id, event.correlation_id)

        try:
            published = self._queue.publish(message)
        except Exception as exc:
            self._repo.reschedule_outbox(event_id, error=str(exc), now=utcnow())
            registry.increment("outbox_dispatch_failed_total")
            return "rescheduled"

        # Marca despachado mesmo quando a fila ja tinha a mensagem: o objetivo do
        # evento foi cumprido, e deixa-lo pendente faria o dispatcher tentar para
        # sempre um trabalho ja feito.
        self._repo.mark_outbox_dispatched(event_id)
        self._trail.marcar(
            event.record_id,
            TrailStage.PUBLISHED,
            correlation_id=event.correlation_id,
            event_id=event_id,
            via="dispatcher",
            duplicate=None if published else True,
        )
        return "dispatched" if published else "duplicate"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Publica eventos pendentes do outbox.")
    parser.add_argument("--limit", type=int, default=None, help="maximo de eventos")
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, "nexus-dispatcher")

    from nexus.persistence import get_repository
    from nexus.queue import get_queue_client

    dispatcher = OutboxDispatcher(get_repository(), get_queue_client(), settings)
    report = dispatcher.dispatch_once(limit=args.limit)
    print(report.render())
    return 0


if __name__ == "__main__":
    sys.exit(main())
