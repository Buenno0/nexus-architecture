"""Handler do worker.

Invocado pelo Control Center ou pelo EventBridge Scheduler — **nao** por event source
mapping do SQS. Essa escolha esta registrada no ADR-003 e no ADR-008: nao e por custo,
e porque a plataforma demonstra execucao sob demanda.
"""

from __future__ import annotations

from typing import Any

from nexus.persistence import get_repository
from nexus.queue import get_queue_client
from nexus.queue.worker import Worker
from nexus.shared.config import get_settings
from nexus.shared.logging import (
    configure_logging,
    get_logger,
    new_correlation_id,
    set_correlation_id,
)

_settings = get_settings()
configure_logging(_settings.log_level, "nexus-worker")
logger = get_logger(__name__)

logger.info("lambda_cold_start", extra={"handler": "worker", "environment": _settings.env})


def handler(event: dict[str, Any] | None, context: Any = None) -> dict[str, Any]:
    """Consome um lote da fila.

    Aceita ``max_messages`` e ``drain``. Com ``drain``, repete ate a fila esvaziar ou
    ate o teto de lotes — o teto existe porque a Lambda tem tempo limitado e um laco
    sem fim seria interrompido no meio, deixando mensagens em voo ate expirarem.
    """
    payload = event or {}
    batch = min(int(payload.get("max_messages", _settings.worker_batch_size)), 100)
    max_batches = min(int(payload.get("max_batches", 1)), 50)
    set_correlation_id(str(payload.get("correlation_id") or new_correlation_id()))

    worker = Worker(get_repository(), get_queue_client(), settings=_settings)

    totals = {
        "received": 0,
        "processed": 0,
        "skipped_duplicate": 0,
        "retried": 0,
        "dead_lettered": 0,
    }
    batches = 0
    for _ in range(max_batches):
        report = worker.process_once(max_messages=batch)
        batches += 1
        totals["received"] += report.received
        totals["processed"] += report.processed
        totals["skipped_duplicate"] += report.skipped_duplicate
        totals["retried"] += report.retried
        totals["dead_lettered"] += report.dead_lettered
        if report.received == 0:
            break

    return {**totals, "batches": batches}
