"""Worker de consumo — ADR-005.

Consome lotes da fila, processa e grava o resultado. Executa **sob demanda**: uma
passada, um lote, e termina. Nenhum processo permanente.

A propriedade central e a idempotencia no consumo. A entrega e at-least-once por
construcao (ADR-003 e ADR-004), entao reentrega nao e excecao — e comportamento normal.
O worker precisa estar correto sob reentrega, nao torcer para que ela nao ocorra.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import datetime

from nexus.observability.metrics import registry
from nexus.observability.trail import TrailRecorder
from nexus.persistence.models import ProcessingResult, TrailStage
from nexus.persistence.repository import CommitConflictError, RecordRepository
from nexus.queue.client import QueueClient, ReceivedMessage
from nexus.queue.processor import RecordProcessor, build_processor
from nexus.shared.clock import utcnow
from nexus.shared.config import Settings, get_settings
from nexus.shared.logging import configure_logging, get_logger, set_correlation_id

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class WorkerReport:
    """Resultado de uma passada do worker."""

    received: int = 0
    processed: int = 0
    skipped_duplicate: int = 0
    retried: int = 0
    dead_lettered: int = 0
    duration_ms: float = 0.0

    def render(self) -> str:
        return (
            f"recebidas={self.received}  processadas={self.processed}  "
            f"ja_processadas={self.skipped_duplicate}  retentativas={self.retried}  "
            f"dlq={self.dead_lettered}  duracao={self.duration_ms:.1f}ms"
        )


class Worker:
    """Consumidor de mensagens da fila."""

    def __init__(
        self,
        repository: RecordRepository,
        queue: QueueClient,
        processor: RecordProcessor | None = None,
        settings: Settings | None = None,
        trail: TrailRecorder | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._repo = repository
        self._queue = queue
        self._processor = processor or build_processor(self._settings, repository)
        self._trail = trail or TrailRecorder(repository, "worker")

    def process_once(self, *, max_messages: int | None = None) -> WorkerReport:
        """Consome um unico lote e termina."""
        batch_size = max_messages if max_messages is not None else self._settings.worker_batch_size
        started = time.perf_counter()

        messages = self._queue.receive(max_messages=batch_size)
        if not messages:
            return WorkerReport(duration_ms=(time.perf_counter() - started) * 1000)

        processed = skipped = retried = dead = 0
        for message in messages:
            outcome = self._handle(message)
            if outcome == "processed":
                processed += 1
            elif outcome == "skipped":
                skipped += 1
            elif outcome == "retried":
                retried += 1
            else:
                dead += 1

        duration_ms = (time.perf_counter() - started) * 1000
        report = WorkerReport(len(messages), processed, skipped, retried, dead, duration_ms)
        registry.increment("worker_processed_total", processed)
        registry.increment("worker_skipped_duplicate_total", skipped)
        registry.observe("worker_batch_duration", duration_ms)
        logger.info(
            "worker_batch_completed",
            extra={
                "received": report.received,
                "processed": processed,
                "skipped_duplicate": skipped,
                "retried": retried,
                "dead_lettered": dead,
                "duration_ms": round(duration_ms, 3),
            },
        )
        return report

    # ------------------------------------------------------------------ interno

    def _handle(self, message: ReceivedMessage) -> str:
        # A trilha de log continua aqui, em outro processo, pelo mesmo identificador
        # que a API gerou na ingestao.
        set_correlation_id(message.correlation_id)

        # Consulta antecipada: evita trabalho desnecessario numa reentrega.
        # NAO e a garantia — entre esta leitura e a escrita existe janela de corrida.
        if (
            self._repo.find_processing_result(message.record_id, self._processor.version)
            is not None
        ):
            logger.info("worker_already_processed", extra={"record_id": message.record_id})
            self._queue.delete(message.receipt)
            return "skipped"

        record = self._repo.get_record(message.record_id)
        if record is None:
            # Retentar nao resolve: o registro nao vai aparecer. Vai direto para a DLQ
            # em vez de consumir o orcamento de tentativas.
            logger.error("worker_record_missing", extra={"record_id": message.record_id})
            self._queue.dead_letter(message.receipt, error="registro inexistente")
            registry.increment("worker_dead_lettered_total")
            self._trail.marcar(
                message.record_id,
                TrailStage.DEAD_LETTERED,
                correlation_id=message.correlation_id,
                reason="registro inexistente",
                attempt=message.receive_count,
            )
            return "dead_lettered"

        self._trail.marcar(
            record.record_id,
            TrailStage.CONSUMED,
            correlation_id=message.correlation_id,
            attempt=message.receive_count,
            processor_version=self._processor.version,
            worker_id=self._settings.worker_id,
        )

        started = time.perf_counter()
        try:
            summary = self._processor.process(record)
        except Exception as exc:
            outcome = self._queue.fail(message.receipt, error=str(exc))
            registry.increment("worker_failed_total")
            logger.warning(
                "worker_processing_failed",
                extra={"record_id": message.record_id, "outcome": outcome.value},
            )
            morreu = outcome.value == "dead_lettered"
            self._trail.marcar(
                record.record_id,
                TrailStage.DEAD_LETTERED if morreu else TrailStage.FAILED,
                correlation_id=message.correlation_id,
                reason=str(exc),
                attempt=message.receive_count,
            )
            return "dead_lettered" if morreu else "retried"

        duration_ms = (time.perf_counter() - started) * 1000
        processed_at = utcnow()
        end_to_end_ms = self._end_to_end_ms(record.created_at, processed_at)
        result = ProcessingResult(
            record_id=record.record_id,
            event_id=message.event_id,
            worker_id=self._settings.worker_id,
            attempts=message.receive_count,
            duration_ms=round(duration_ms, 3),
            summary=summary,
            correlation_id=message.correlation_id,
            processed_at=processed_at,
            processor_version=self._processor.version,
            end_to_end_ms=end_to_end_ms,
        )

        try:
            # ESTA e a garantia de efeito unico: escrita condicional, nao a consulta.
            self._repo.commit_processing(result)
        except CommitConflictError:
            # Outro worker venceu a corrida. Nao e erro — o trabalho foi feito.
            logger.info("worker_commit_conflict", extra={"record_id": record.record_id})
            self._queue.delete(message.receipt)
            return "skipped"

        self._queue.delete(message.receipt)
        registry.observe("worker_record_duration", duration_ms)
        if end_to_end_ms is not None:
            registry.observe("record_end_to_end", end_to_end_ms)
        self._trail.marcar(
            record.record_id,
            TrailStage.RESOLVED,
            correlation_id=message.correlation_id,
            duration_ms=round(duration_ms, 3),
            end_to_end_ms=end_to_end_ms,
            entity_id=summary.get("entity_id"),
            matches=summary.get("matches"),
            candidates=summary.get("candidates_compared"),
            # `True` apenas; `None` e filtrado e nao polui a trilha dos casos normais.
            # Truncar candidatos em silencio esconderia um possivel falso negativo.
            truncated=summary.get("candidates_truncated") or None,
        )
        logger.info(
            "worker_record_processed",
            extra={
                "record_id": record.record_id,
                "duration_ms": round(duration_ms, 3),
                "end_to_end_ms": end_to_end_ms,
            },
        )
        return "processed"

    @staticmethod
    def _end_to_end_ms(created_at: datetime | None, processed_at: datetime) -> float | None:
        """Tempo entre a aceitacao e o fim do processamento.

        Devolve ``None`` em vez de um numero negativo quando os relogios discordam.
        Dois processos diferentes carimbam as duas pontas; na AWS sao duas Lambdas. Um
        valor negativo nao e uma latencia pequena, e um sinal de que a medicao nao vale
        — e gravar zero esconderia isso dentro de um histograma plausivel.
        """
        if created_at is None:
            return None
        delta = (processed_at - created_at).total_seconds() * 1000
        return round(delta, 3) if delta >= 0 else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Consome um lote da fila e termina.")
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument(
        "--drain",
        action="store_true",
        help="repete ate a fila esvaziar (continua sob demanda, nao e processo residente)",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, "nexus-worker")

    from nexus.persistence import get_repository
    from nexus.queue import get_queue_client

    worker = Worker(get_repository(), get_queue_client(), settings=settings)

    total = WorkerReport()
    while True:
        report = worker.process_once(max_messages=args.batch_size)
        total = WorkerReport(
            total.received + report.received,
            total.processed + report.processed,
            total.skipped_duplicate + report.skipped_duplicate,
            total.retried + report.retried,
            total.dead_lettered + report.dead_lettered,
            total.duration_ms + report.duration_ms,
        )
        if not args.drain or report.received == 0:
            break

    print(total.render())
    return 0


if __name__ == "__main__":
    sys.exit(main())
