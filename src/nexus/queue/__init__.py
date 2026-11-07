"""Nexus Queue Engine.

A fabrica e o unico ponto onde a configuracao decide a implementacao. Nenhum outro
modulo deve ramificar por ``NEXUS_QUEUE_BACKEND``.
"""

from __future__ import annotations

from functools import lru_cache

from nexus.queue.client import (
    FailOutcome,
    NullQueueClient,
    QueueClient,
    QueueMessage,
    QueueStats,
    ReceivedMessage,
)
from nexus.shared.config import get_settings


@lru_cache(maxsize=1)
def get_queue_client() -> QueueClient:
    """Devolve o cliente de fila configurado.

    Com ``NEXUS_QUEUE_BACKEND=none``, a ingestao nao publica e os eventos permanecem
    pendentes no outbox — comportamento correto quando nao ha consumidor, nao falha.
    """
    settings = get_settings()
    if settings.queue_backend == "none":
        return NullQueueClient()

    if settings.queue_backend == "sqs":
        from nexus.queue.sqs import SqsQueue

        return SqsQueue(settings=settings)

    from nexus.queue.sqlite import SqliteQueue

    return SqliteQueue(settings=settings)


__all__ = [
    "FailOutcome",
    "NullQueueClient",
    "QueueClient",
    "QueueMessage",
    "QueueStats",
    "ReceivedMessage",
    "get_queue_client",
]
