"""Modelos de dominio da persistencia.

Dataclasses imutaveis, livres de detalhe de armazenamento. A traducao de/para itens do
DynamoDB vive em ``dynamo.py`` — trocar o mecanismo de persistencia nao deve exigir
alteracao nestes modelos.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class RecordType(StrEnum):
    PERSON = "person"
    ORGANIZATION = "organization"


class ProcessingStatus(StrEnum):
    SUCCEEDED = "succeeded"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StoredRecord:
    """Uma observacao imutavel — ADR-002.

    Nunca e sobrescrita. Uma nova versao dos dados produz uma nova observacao, com novo
    ``record_id``. O unico campo mutavel e ``seen_count``, incrementado quando o mesmo
    conteudo exato e reenviado.
    """

    record_id: str
    record_type: RecordType
    source: str
    natural_key: str
    record_fingerprint: str
    payload: dict[str, Any]
    normalized: dict[str, Any]
    correlation_id: str
    created_at: datetime
    seen_count: int = 1


@dataclass(frozen=True, slots=True)
class OutboxEvent:
    """Evento de outbox — ADR-003.

    ``pending_shard`` existe somente enquanto ``status == PENDING``. Ao despachar, o
    atributo e removido e o item deixa o indice esparso.
    """

    event_id: str
    record_id: str
    correlation_id: str
    created_at: datetime
    next_attempt_at: datetime
    status: OutboxStatus = OutboxStatus.PENDING
    attempts: int = 0
    pending_shard: str | None = None
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    """Resultado armazenado de uma operacao de ingestao — ADR-002.

    ``request_hash`` e o hash do corpo **bruto**: permite distinguir replay legitimo
    (mesmo corpo, devolve a resposta) de reuso indevido da chave (corpo diferente, 409).
    """

    source: str
    idempotency_key: str
    request_hash: str
    record_id: str
    status_code: int
    response_body: dict[str, Any]
    created_at: datetime
    expires_at: int


@dataclass(frozen=True, slots=True)
class Page:
    """Pagina de resultados com cursor opaco."""

    items: list[StoredRecord] = field(default_factory=list)
    next_cursor: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    """Resultado do processamento de uma observacao — ADR-005.

    Este item **e** o marcador de "ja processado". Nao sao duas coisas que precisam ser
    gravadas atomicamente: sao uma so.

    Duas escritas separadas teriam janela de crash entre elas, e a reentrega
    reprocessaria. Como item unico com escrita condicional, o efeito unico e garantido
    por uma unica operacao, mais barata que transacao e sem janela nenhuma.
    """

    record_id: str
    event_id: str
    worker_id: str
    attempts: int
    duration_ms: float
    summary: dict[str, Any]
    correlation_id: str
    processed_at: datetime
    status: ProcessingStatus = ProcessingStatus.SUCCEEDED
