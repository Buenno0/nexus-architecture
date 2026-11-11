"""Orquestracao da ingestao — ADR-002 e ADR-003.

Este modulo concentra a logica do caminho de ingestao. Ele nao conhece HTTP: recebe
dados ja validados e devolve um resultado, o que o torna testavel sem subir servidor.
"""

from __future__ import annotations

import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from nexus.ingestion.normalization import normalize_payload
from nexus.observability.metrics import registry
from nexus.observability.trail import TrailRecorder
from nexus.persistence.models import (
    IdempotencyRecord,
    OutboxEvent,
    OutboxStatus,
    RecordType,
    StoredRecord,
    TrailStage,
)
from nexus.persistence.repository import CommitConflictError, RecordRepository
from nexus.queue.client import QueueClient, QueueMessage
from nexus.shared.clock import utcnow
from nexus.shared.config import Settings, get_settings
from nexus.shared.errors import IdempotencyConflictError
from nexus.shared.identity import natural_key, new_ulid, record_fingerprint, request_hash
from nexus.shared.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Resultado de uma operacao de ingestao."""

    status_code: int
    body: dict[str, Any]
    replayed: bool = False


class IngestionService:
    """Caminho de ingestao: idempotencia, normalizacao, transacao e publicacao."""

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
        self._trail = trail or TrailRecorder(repository, "api", self._settings)

    # ------------------------------------------------------------------ publico

    def ingest(
        self,
        record_type: RecordType,
        payload: Mapping[str, Any],
        *,
        raw_body: bytes,
        idempotency_key: str,
        correlation_id: str,
    ) -> IngestionResult:
        """Executa o caminho completo de ingestao.

        A ordem das verificacoes nao e arbitraria:

        1. **Idempotencia primeiro.** Um replay nao deve pagar normalizacao nem consultas.
        2. **Normalizacao depois.** O fingerprint precisa ser calculado sobre o conteudo
           canonizado, senao variacoes irrelevantes gerariam observacoes distintas.
        3. **Duplicata de conteudo por ultimo.** So faz sentido depois de normalizar.
        """
        source = str(payload["source"])
        incoming_hash = request_hash(raw_body)

        replay = self._check_replay(source, idempotency_key, incoming_hash)
        if replay is not None:
            return replay

        normalized = normalize_payload(payload)
        fingerprint = record_fingerprint(record_type.value, normalized)
        key = natural_key(record_type.value, normalized)

        existing = self._repo.find_by_fingerprint(key, fingerprint)
        if existing is not None:
            return self._handle_duplicate(
                existing, source, idempotency_key, incoming_hash, correlation_id
            )

        return self._accept_new(
            record_type=record_type,
            payload=dict(payload),
            normalized=normalized,
            natural_key_value=key,
            fingerprint=fingerprint,
            source=source,
            idempotency_key=idempotency_key,
            request_hash_value=incoming_hash,
            correlation_id=correlation_id,
        )

    # ----------------------------------------------------------------- internos

    def _check_replay(
        self, source: str, idempotency_key: str, incoming_hash: str
    ) -> IngestionResult | None:
        """Devolve a resposta armazenada, ou ``None`` se a operacao e nova.

        Chave conhecida com corpo diferente resulta em ``409``: reusar a chave com
        payload distinto e bug do cliente, e devolver a resposta antiga o esconderia.
        """
        stored = self._repo.find_idempotency(source, idempotency_key)
        if stored is None:
            return None

        if stored.request_hash != incoming_hash:
            registry.increment("ingestion_idempotency_conflict_total")
            logger.warning(
                "idempotency_conflict",
                extra={"source": source, "record_id": stored.record_id},
            )
            raise IdempotencyConflictError(
                "Chave de idempotencia ja utilizada com um corpo diferente",
                details={"record_id": stored.record_id},
            )

        registry.increment("ingestion_replayed_total")
        logger.info("ingestion_replayed", extra={"record_id": stored.record_id})
        return IngestionResult(stored.status_code, stored.response_body, replayed=True)

    def _handle_duplicate(
        self,
        existing: StoredRecord,
        source: str,
        idempotency_key: str,
        incoming_hash: str,
        correlation_id: str,
    ) -> IngestionResult:
        """Conteudo byte-identico ja observado: nao cria observacao, nao enfileira."""
        body = {
            "record_id": existing.record_id,
            "record_type": existing.record_type.value,
            "status": "duplicate",
            "record_fingerprint": existing.record_fingerprint,
            "correlation_id": correlation_id,
            "seen_count": existing.seen_count + 1,
        }
        idempotency = self._build_idempotency(
            source, idempotency_key, incoming_hash, existing.record_id, 200, body
        )

        try:
            self._repo.register_duplicate(existing.record_id, idempotency)
        except CommitConflictError:
            return self._resolve_race(source, idempotency_key)

        registry.increment("ingestion_duplicate_total")
        logger.info(
            "ingestion_duplicate",
            extra={"record_id": existing.record_id, "seen_count": existing.seen_count + 1},
        )
        return IngestionResult(200, body)

    def _accept_new(
        self,
        *,
        record_type: RecordType,
        payload: dict[str, Any],
        normalized: dict[str, Any],
        natural_key_value: str,
        fingerprint: str,
        source: str,
        idempotency_key: str,
        request_hash_value: str,
        correlation_id: str,
    ) -> IngestionResult:
        now = utcnow()
        record_id = new_ulid()
        event_id = new_ulid()

        record = StoredRecord(
            record_id=record_id,
            record_type=record_type,
            source=source,
            natural_key=natural_key_value,
            record_fingerprint=fingerprint,
            payload=payload,
            normalized=normalized,
            correlation_id=correlation_id,
            created_at=now,
        )
        event = OutboxEvent(
            event_id=event_id,
            record_id=record_id,
            correlation_id=correlation_id,
            created_at=now,
            next_attempt_at=now,
            status=OutboxStatus.PENDING,
            pending_shard=self._shard_for(event_id),
        )
        body = {
            "record_id": record_id,
            "record_type": record_type.value,
            "status": "accepted",
            "record_fingerprint": fingerprint,
            "correlation_id": correlation_id,
            "seen_count": 1,
        }
        idempotency = self._build_idempotency(
            source, idempotency_key, request_hash_value, record_id, 202, body
        )

        try:
            # Observacao, evento e idempotencia numa unica transacao — ADR-003.
            self._repo.commit_ingestion(record, event, idempotency)
        except CommitConflictError:
            return self._resolve_race(source, idempotency_key)

        registry.increment("ingestion_accepted_total", record_type=record_type.value)
        registry.increment("outbox_pending_total")
        logger.info(
            "ingestion_accepted",
            extra={"record_id": record_id, "event_id": event_id, "source": source},
        )

        self._trail.marcar(
            record_id,
            TrailStage.ACCEPTED,
            correlation_id=correlation_id,
            source=source,
            record_type=record_type.value,
            fingerprint=fingerprint,
            event_id=event_id,
        )

        self._publish_best_effort(event)
        return IngestionResult(202, body)

    def _publish_best_effort(self, event: OutboxEvent) -> None:
        """Publica imediatamente, se houver fila.

        Caminho feliz: latencia baixa e o evento sai do indice esparso em seguida.
        Caminho triste: o evento continua pendente e o dispatcher recupera — ADR-003.

        Sem fila configurada (Fase 1), nao ha tentativa: falhar consumiria tentativas de
        retry para anunciar uma capacidade que ainda nao existe.
        """
        if not self._queue.is_enabled:
            logger.info("outbox_pending_no_consumer", extra={"event_id": event.event_id})
            return

        message = QueueMessage(event.event_id, event.record_id, event.correlation_id)
        try:
            self._queue.publish(message)
        except Exception as exc:
            registry.increment("outbox_publish_failed_total")
            logger.warning(
                "outbox_publish_failed",
                extra={"event_id": event.event_id, "reason": str(exc)},
            )
            return

        self._repo.mark_outbox_dispatched(event.event_id)
        registry.increment("outbox_dispatched_total")
        self._trail.marcar(
            event.record_id,
            TrailStage.PUBLISHED,
            correlation_id=event.correlation_id,
            event_id=event.event_id,
            via="inline",
        )

    def _resolve_race(self, source: str, idempotency_key: str) -> IngestionResult:
        """Resolve corrida entre requisicoes concorrentes com a mesma chave.

        A condicao ``attribute_not_exists`` na transacao garante que exatamente uma
        requisicao grava. As demais chegam aqui, releem o resultado ja estabelecido e
        devolvem a mesma resposta — e por isso que N requisicoes simultaneas com a mesma
        chave produzem exatamente uma observacao.
        """
        stored = self._repo.find_idempotency(source, idempotency_key)
        if stored is None:
            # A transacao foi cancelada por outra condicao que nao a de idempotencia.
            raise IdempotencyConflictError("Conflito de escrita concorrente; repita a requisicao")
        registry.increment("ingestion_race_resolved_total")
        logger.info("ingestion_race_resolved", extra={"record_id": stored.record_id})
        return IngestionResult(stored.status_code, stored.response_body, replayed=True)

    def _build_idempotency(
        self,
        source: str,
        idempotency_key: str,
        request_hash_value: str,
        record_id: str,
        status_code: int,
        body: dict[str, Any],
    ) -> IdempotencyRecord:
        now = utcnow()
        expires = now + timedelta(seconds=self._settings.idempotency_ttl_seconds)
        return IdempotencyRecord(
            source=source,
            idempotency_key=idempotency_key,
            request_hash=request_hash_value,
            record_id=record_id,
            status_code=status_code,
            response_body=body,
            created_at=now,
            expires_at=int(expires.timestamp()),
        )

    def _shard_for(self, event_id: str) -> str:
        """Distribui eventos entre shards do indice esparso.

        CRC32 e deterministico e barato. O objetivo nao e distribuicao criptografica,
        apenas evitar que toda escrita do indice caia na mesma particao — ADR-003.
        """
        index = zlib.crc32(event_id.encode("ascii")) % self._settings.outbox_shards
        return f"PENDING#{index}"
