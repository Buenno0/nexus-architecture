"""Handler do dispatcher do outbox.

Invocado pelo Control Center ou pelo EventBridge Scheduler. Publica eventos pendentes
e termina — nenhum laco, nenhum processo residente.
"""

from __future__ import annotations

from typing import Any

from nexus.persistence import get_repository
from nexus.queue import get_queue_client
from nexus.queue.dispatcher import OutboxDispatcher
from nexus.shared.config import get_settings
from nexus.shared.logging import (
    configure_logging,
    get_logger,
    new_correlation_id,
    set_correlation_id,
)

_settings = get_settings()
configure_logging(_settings.log_level, "nexus-dispatcher")
logger = get_logger(__name__)

logger.info("lambda_cold_start", extra={"handler": "dispatcher", "environment": _settings.env})


def handler(event: dict[str, Any] | None, context: Any = None) -> dict[str, Any]:
    """Publica ate ``limit`` eventos pendentes do outbox.

    O evento aceita ``limit``; na ausencia, usa o lote padrao da configuracao. O teto
    e aplicado tambem aqui, e nao apenas na API, porque a Lambda pode ser invocada
    diretamente.
    """
    payload = event or {}
    limit = min(
        int(payload.get("limit", _settings.outbox_dispatch_batch_size)),
        _settings.max_batch_records,
    )
    set_correlation_id(str(payload.get("correlation_id") or new_correlation_id()))

    dispatcher = OutboxDispatcher(get_repository(), get_queue_client(), _settings)
    report = dispatcher.dispatch_once(limit=limit)

    return {
        "scanned": report.scanned,
        "dispatched": report.dispatched,
        "duplicates": report.duplicates,
        "rescheduled": report.rescheduled,
        "missing": report.missing,
    }
