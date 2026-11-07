"""Reprocessamento do acervo sob uma versao nova de processador — ADR-007.

Registros ja consumidos nao tem mais mensagem na fila: ela foi apagada ao confirmar o
processamento. Trocar o processador nao os traz de volta sozinho.

Este modulo pagina as observacoes existentes e reenfileira **apenas as que ainda nao
tem resultado na versao corrente**. Rodar duas vezes nao duplica trabalho.

Executa sob demanda e com teto, como todo o resto da plataforma.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass

from nexus.persistence.models import RecordType
from nexus.persistence.repository import RecordRepository
from nexus.queue.client import QueueClient, QueueMessage
from nexus.shared.config import Settings, get_settings
from nexus.shared.identity import new_ulid
from nexus.shared.logging import configure_logging, get_logger

logger = get_logger(__name__)

PAGE_SIZE = 100


@dataclass(frozen=True, slots=True)
class ReprocessReport:
    """Resultado de uma passada de reprocessamento."""

    scanned: int = 0
    enqueued: int = 0
    already_processed: int = 0

    def render(self) -> str:
        return (
            f"varridos={self.scanned}  enfileirados={self.enqueued}  "
            f"ja_processados={self.already_processed}"
        )


class Reprocessor:
    """Reenfileira observacoes sem resultado na versao corrente."""

    def __init__(
        self,
        repository: RecordRepository,
        queue: QueueClient,
        version: str,
        settings: Settings | None = None,
    ) -> None:
        self._repo = repository
        self._queue = queue
        self._version = version
        self._settings = settings or get_settings()

    def run(self, *, limit: int) -> ReprocessReport:
        if not self._queue.is_enabled:
            logger.info("reprocess_skipped_no_queue")
            return ReprocessReport()

        scanned = enqueued = already = 0
        budget = limit

        for record_type in RecordType:
            cursor: str | None = None
            while budget > 0:
                page = self._repo.list_records(
                    record_type, limit=min(PAGE_SIZE, budget), cursor=cursor
                )
                if not page.items:
                    break

                for record in page.items:
                    scanned += 1
                    budget -= 1
                    if self._repo.find_processing_result(record.record_id, self._version):
                        already += 1
                        continue
                    # O evento nao vem do outbox: e uma reinjecao deliberada, marcada
                    # como tal para que o rastro no log diga de onde veio.
                    message = QueueMessage(
                        event_id=f"reprocess-{new_ulid()}",
                        record_id=record.record_id,
                        correlation_id=record.correlation_id or new_ulid(),
                    )
                    if self._queue.publish(message):
                        enqueued += 1

                cursor = page.next_cursor
                if cursor is None:
                    break

        report = ReprocessReport(scanned, enqueued, already)
        logger.info(
            "reprocess_completed",
            extra={
                "version": self._version,
                "scanned": scanned,
                "enqueued": enqueued,
                "already_processed": already,
            },
        )
        return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Reenfileira observacoes sem resultado na versao corrente."
    )
    parser.add_argument("--limit", type=int, default=1_000)
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, "nexus-reprocess")

    from nexus.persistence import get_repository
    from nexus.queue import get_queue_client
    from nexus.queue.processor import build_processor

    repository = get_repository()
    processor = build_processor(settings, repository)
    reprocessor = Reprocessor(repository, get_queue_client(), processor.version, settings)
    print(reprocessor.run(limit=args.limit).render())
    return 0


if __name__ == "__main__":
    sys.exit(main())
