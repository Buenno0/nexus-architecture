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
    Entity,
    EntityMember,
    IdempotencyRecord,
    MergeEvent,
    MetricSample,
    OutboxEvent,
    OutboxStatus,
    Page,
    ProcessingResult,
    RecordType,
    ReviewItem,
    ReviewStatus,
    StoredRecord,
    TrailEvent,
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
        self.processing: dict[tuple[str, str], ProcessingResult] = {}
        self.blocks: dict[str, list[str]] = {}
        self.entities: dict[str, Entity] = {}
        self.members: dict[str, dict[str, EntityMember]] = {}
        self.merge_events: dict[str, list[MergeEvent]] = {}
        self.record_links: dict[str, str] = {}
        self.reviews: dict[str, ReviewItem] = {}
        self.stats: dict[str, int] = {}
        self.trail: dict[str, list[TrailEvent]] = {}
        self.samples: dict[tuple[str, str], MetricSample] = {}
        #: Quando True, toda escrita de trilha falha — para testar que ela nao derruba
        #: a operacao que descreve.
        self.trail_quebrada = False
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
            key = (result.record_id, result.processor_version)
            if key in self.processing:
                raise CommitConflictError("commit_processing")
            self.processing[key] = result

    def find_processing_result(self, record_id: str, version: str) -> ProcessingResult | None:
        with self._lock:
            return self.processing.get((record_id, version))

    # Conveniencias de teste: a chave real e (record_id, versao), mas a maioria dos
    # testes so quer saber se o registro foi processado por alguma versao.
    @property
    def processed_ids(self) -> set[str]:
        with self._lock:
            return {record_id for record_id, _ in self.processing}

    def result_for(self, record_id: str) -> ProcessingResult | None:
        with self._lock:
            for (stored_id, _), result in self.processing.items():
                if stored_id == record_id:
                    return result
        return None

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

    # ------------------------------------------------------- entity resolution

    def put_blocking_keys(self, record_id: str, record_type: RecordType, keys: list[str]) -> None:
        with self._lock:
            for key in keys:
                bucket = self.blocks.setdefault(key, [])
                if record_id not in bucket:
                    bucket.append(record_id)

    def find_block_candidates(
        self, keys: list[str], *, limit: int, exclude: str | None = None
    ) -> tuple[list[str], bool]:
        found: list[str] = []
        truncated = False
        with self._lock:
            for key in keys:
                for candidate in self.blocks.get(key, []):
                    if candidate == exclude or candidate in found:
                        continue
                    if len(found) >= limit:
                        truncated = True
                        return found, truncated
                    found.append(candidate)
        return found, truncated

    def get_entity(self, entity_id: str) -> Entity | None:
        with self._lock:
            return self.entities.get(entity_id)

    def find_entity_id_for_record(self, record_id: str) -> str | None:
        with self._lock:
            return self.record_links.get(record_id)

    def list_entity_members(self, entity_id: str) -> list[EntityMember]:
        with self._lock:
            return list(self.members.get(entity_id, {}).values())

    def list_merge_events(self, entity_id: str) -> list[MergeEvent]:
        with self._lock:
            return list(self.merge_events.get(entity_id, []))

    def create_entity(self, entity: Entity, members: list[EntityMember]) -> None:
        with self._lock:
            if entity.entity_id in self.entities:
                raise CommitConflictError("create_entity")
            self.entities[entity.entity_id] = entity
            self.members[entity.entity_id] = {m.record_id: m for m in members}
            for member in members:
                self.record_links[member.record_id] = entity.entity_id

    def add_member(self, entity: Entity, member: EntityMember) -> Entity:
        from dataclasses import replace

        with self._lock:
            current = self.entities.get(entity.entity_id)
            # Mesma condicao do repositorio real: versao divergente significa que
            # outro worker mexeu na entidade desde a leitura.
            if current is None or current.version != entity.version:
                raise CommitConflictError("add_member")
            updated = replace(
                current, member_count=current.member_count + 1, version=current.version + 1
            )
            self.entities[entity.entity_id] = updated
            self.members.setdefault(entity.entity_id, {})[member.record_id] = member
            self.record_links[member.record_id] = entity.entity_id
            return updated

    def merge_entities(
        self, target: Entity, source: Entity, members: list[EntityMember], event: MergeEvent
    ) -> Entity:
        from dataclasses import replace

        with self._lock:
            current_target = self.entities.get(target.entity_id)
            current_source = self.entities.get(source.entity_id)
            if (
                current_target is None
                or current_source is None
                or current_target.version != target.version
                or current_source.version != source.version
            ):
                raise CommitConflictError("merge_entities")

            moved = replace(
                current_target,
                member_count=current_target.member_count + len(members),
                version=current_target.version + 1,
            )
            self.entities[target.entity_id] = moved
            for member in members:
                self.members.setdefault(target.entity_id, {})[member.record_id] = replace(
                    member, entity_id=target.entity_id
                )
                self.record_links[member.record_id] = target.entity_id
            self.members.pop(source.entity_id, None)
            self.entities.pop(source.entity_id, None)
            self.merge_events.setdefault(target.entity_id, []).append(event)
            return moved

    def flag_entity(self, entity_id: str, reason: str) -> None:
        from dataclasses import replace

        with self._lock:
            current = self.entities.get(entity_id)
            if current is not None:
                self.entities[entity_id] = replace(current, flagged=True, flag_reason=reason)

    def put_review(self, item: ReviewItem) -> bool:
        with self._lock:
            if item.pair_id in self.reviews:
                return False
            self.reviews[item.pair_id] = item
            return True

    def get_review(self, pair_id: str) -> ReviewItem | None:
        with self._lock:
            return self.reviews.get(pair_id)

    def list_pending_reviews(self, *, limit: int) -> list[ReviewItem]:
        with self._lock:
            pendentes = [r for r in self.reviews.values() if r.status == ReviewStatus.PENDING]
        return pendentes[:limit]

    def decide_review(self, pair_id: str, status: ReviewStatus, reason: str | None) -> ReviewItem:
        from dataclasses import replace

        from nexus.shared.clock import utcnow

        with self._lock:
            current = self.reviews.get(pair_id)
            if current is None:
                from nexus.shared.errors import RecordNotFoundError

                raise RecordNotFoundError("Par de revisao nao encontrado")
            decided = replace(
                current,
                status=status,
                reason=reason,
                decided_at=utcnow(),
                review_shard=None,
            )
            self.reviews[pair_id] = decided
            return decided

    def increment_resolution_stats(self, **counters: int) -> None:
        with self._lock:
            for name, value in counters.items():
                self.stats[name] = self.stats.get(name, 0) + value

    def get_resolution_stats(self) -> dict[str, int]:
        with self._lock:
            return dict(self.stats)

    # ------------------------------------------------------------ observabilidade

    def record_trail(self, event: TrailEvent) -> bool:
        if self.trail_quebrada:
            return False
        with self._lock:
            self.trail.setdefault(event.record_id, []).append(event)
        return True

    def get_trail(self, record_id: str) -> list[TrailEvent]:
        with self._lock:
            return sorted(self.trail.get(record_id, []), key=lambda e: e.occurred_at)

    def put_metric_sample(self, sample: MetricSample) -> bool:
        chave = (sample.metric, sample.bucket.isoformat())
        with self._lock:
            # Mesma condicao do repositorio real: balde ocupado nao e sobrescrito.
            if chave in self.samples:
                return False
            self.samples[chave] = sample
        return True

    def get_metric_series(self, metric: str, *, since: datetime) -> list[MetricSample]:
        with self._lock:
            return sorted(
                (s for s in self.samples.values() if s.metric == metric and s.bucket >= since),
                key=lambda s: s.bucket,
            )

    def oldest_pending_outbox_at(self) -> datetime | None:
        with self._lock:
            pendentes = [
                e.next_attempt_at for e in self.events.values() if e.status == OutboxStatus.PENDING
            ]
        return min(pendentes) if pendentes else None


class RecordingQueueClient(QueueClient):
    """Fila que registra o que foi publicado."""

    def __init__(self, *, enabled: bool = True, fail: bool = False) -> None:
        self._enabled = enabled
        self._fail = fail
        self.published: list[QueueMessage] = []
        #: Profundidade da DLQ, ajustavel pelos testes de alerta.
        self.dead_count = 0

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
        return QueueStats(pending=len(self.published), dead=self.dead_count)

    def redrive(self, *, limit: int) -> int:
        return 0
