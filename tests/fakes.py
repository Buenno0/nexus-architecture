"""Dublês de teste.

O repositorio falso implementa o mesmo contrato do real e permite testar toda a logica
de ingestao sem Docker: rapido o bastante para rodar a cada salvamento.

Ele reproduz deliberadamente as **condicoes de escrita** do repositorio real — e delas
que depende a garantia de que N requisicoes concorrentes com a mesma chave produzem uma
unica observacao. Um falso que aceitasse qualquer escrita daria testes verdes e producao
quebrada.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

from nexus.persistence.models import (
    IdempotencyRecord,
    OutboxEvent,
    OutboxStatus,
    Page,
    ProcessingResult,
    RecordType,
    StoredRecord,
)
from nexus.persistence.repository import CommitConflictError, RecordRepository
from nexus.queue.client import FailOutcome, QueueClient, QueueMessage, QueueStats, ReceivedMessage
from nexus.shared.errors import QueuePublishError


class FakeRepository(RecordRepository):
    """Repositorio em memoria, seguro para uso concorrente."""

    def __init__(self, max_attempts: int = 3, backoff_base_seconds: float = 0.0) -> None:
        self._lock = threading.Lock()
        self.records: dict[str, StoredRecord] = {}
        self.events: dict[str, OutboxEvent] = {}
        self.idempotency: dict[tuple[str, str], IdempotencyRecord] = {}
        self.processing: dict[str, ProcessingResult] = {}
        self._max_attempts = max_attempts
        # Zero por padrao: o reagendamento fica imediatamente visivel, tornando os
        # testes deterministicos sem sleep. O backoff real e exercitado contra o
        # DynamoDB em tests/integration/test_repository.py.
        self._backoff_base = backoff_base_seconds
        self.ping_result = True

    def ensure_ready(self) -> None:
        return None

    def ping(self) -> bool:
        return self.ping_result

    def find_idempotency(self, source: str, idempotency_key: str) -> IdempotencyRecord | None:
        with self._lock:
            return self.idempotency.get((source, idempotency_key))

    def find_by_fingerprint(self, natural_key: str, fingerprint: str) -> StoredRecord | None:
        with self._lock:
            for record in self.records.values():
                if record.natural_key == natural_key and record.record_fingerprint == fingerprint:
                    return record
        return None

    def get_record(self, record_id: str) -> StoredRecord | None:
        with self._lock:
            return self.records.get(record_id)

    def list_records(
        self, record_type: RecordType, *, limit: int, cursor: str | None = None
    ) -> Page:
        with self._lock:
            matching = sorted(
                (r for r in self.records.values() if r.record_type == record_type),
                key=lambda r: r.record_id,
                reverse=True,
            )
        start = 0
        if cursor:
            ids = [r.record_id for r in matching]
            start = ids.index(cursor) + 1 if cursor in ids else len(ids)
        page = matching[start : start + limit]
        next_cursor = page[-1].record_id if len(matching) > start + limit and page else None
        return Page(items=page, next_cursor=next_cursor)

    def commit_ingestion(
        self, record: StoredRecord, event: OutboxEvent, idempotency: IdempotencyRecord
    ) -> None:
        key = (idempotency.source, idempotency.idempotency_key)
        with self._lock:
            # Mesma condicao do repositorio real: exatamente uma escrita vence.
            if key in self.idempotency or record.record_id in self.records:
                raise CommitConflictError("commit_ingestion")
            self.records[record.record_id] = record
            self.events[event.event_id] = event
            self.idempotency[key] = idempotency

    def register_duplicate(self, record_id: str, idempotency: IdempotencyRecord) -> None:
        key = (idempotency.source, idempotency.idempotency_key)
        with self._lock:
            if key in self.idempotency:
                raise CommitConflictError("register_duplicate")
            existing = self.records.get(record_id)
            if existing is None:
                raise CommitConflictError("register_duplicate")
            from dataclasses import replace

            self.records[record_id] = replace(existing, seen_count=existing.seen_count + 1)
            self.idempotency[key] = idempotency

    def commit_processing(self, result: ProcessingResult) -> None:
        with self._lock:
            # Mesma condicao do repositorio real: a escrita falha se ja houver
            # marcador. E dela, nao da consulta previa, que vem o efeito unico.
            if result.record_id in self.processing:
                raise CommitConflictError("commit_processing")
            self.processing[result.record_id] = result

    def find_processing_result(self, record_id: str) -> ProcessingResult | None:
        with self._lock:
            return self.processing.get(record_id)

    def get_outbox_event(self, event_id: str) -> OutboxEvent | None:
        with self._lock:
            return self.events.get(event_id)

    def mark_outbox_dispatched(self, event_id: str) -> None:
        from dataclasses import replace

        with self._lock:
            event = self.events.get(event_id)
            if event is not None:
                self.events[event_id] = replace(
                    event, status=OutboxStatus.DISPATCHED, pending_shard=None
                )

    def reschedule_outbox(self, event_id: str, *, error: str, now: datetime) -> OutboxEvent:
        from dataclasses import replace

        with self._lock:
            event = self.events[event_id]
            attempts = event.attempts + 1
            if attempts >= self._max_attempts:
                updated = replace(
                    event,
                    attempts=attempts,
                    status=OutboxStatus.FAILED,
                    pending_shard=None,
                    last_error=error,
                )
            else:
                updated = replace(
                    event,
                    attempts=attempts,
                    next_attempt_at=now
                    + timedelta(seconds=self._backoff_base * (2 ** (attempts - 1))),
                    last_error=error,
                )
            self.events[event_id] = updated
            return updated

    def list_pending_outbox(self, shard: str, *, limit: int, now: datetime) -> list[str]:
        with self._lock:
            return [
                event.event_id
                for event in self.events.values()
                if event.pending_shard == shard and event.next_attempt_at <= now
            ][:limit]

    def count_pending_outbox(self) -> int:
        with self._lock:
            return sum(1 for e in self.events.values() if e.status == OutboxStatus.PENDING)


class RecordingQueueClient(QueueClient):
    """Fila que registra o que foi publicado."""

    def __init__(self, *, enabled: bool = True, fail: bool = False) -> None:
        self._enabled = enabled
        self._fail = fail
        self.published: list[QueueMessage] = []

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def publish(self, message: QueueMessage) -> bool:
        if self._fail:
            raise QueuePublishError("falha simulada de publicacao")
        self.published.append(message)
        return True

    # Operacoes de consumo: este dublê existe para verificar publicacao na ingestao.
    # Os testes de worker usam a SqliteQueue real — um segundo motor de fila poderia
    # divergir do verdadeiro e dar testes verdes sobre comportamento inexistente.
    def receive(
        self, *, max_messages: int, visibility_timeout_seconds: float | None = None
    ) -> list[ReceivedMessage]:
        return []

    def delete(self, receipt: str) -> bool:
        return False

    def fail(self, receipt: str, *, error: str) -> FailOutcome:
        return FailOutcome.UNKNOWN_RECEIPT

    def dead_letter(self, receipt: str, *, error: str) -> bool:
        return False

    def stats(self) -> QueueStats:
        return QueueStats(pending=len(self.published))

    def redrive(self, *, limit: int) -> int:
        return 0
