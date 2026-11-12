"""Implementacao DynamoDB do repositorio.

O mesmo codigo roda contra DynamoDB Local e DynamoDB gerenciado — apenas o endpoint
muda (ADR-001). Usa a API de baixo nivel com serializacao explicita porque
``TransactWriteItems`` nao esta disponivel na interface de recurso.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import BotoCoreError, ClientError

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
    ProcessingStatus,
    RecordType,
    ReviewItem,
    ReviewStatus,
    StoredRecord,
    TrailEvent,
    TrailStage,
)
from nexus.persistence.repository import CommitConflictError, RecordRepository
from nexus.persistence.tables import (
    GSI_NATURAL,
    GSI_OUTBOX_PENDING,
    GSI_RECENCY,
    GSI_REVIEW,
    build_client,
    ensure_table,
    wait_for_dynamodb,
)
from nexus.shared.clock import utcnow
from nexus.shared.config import Settings, get_settings
from nexus.shared.errors import (
    InvalidPaginationCursorError,
    PersistenceError,
    RecordNotFoundError,
)
from nexus.shared.identity import idempotency_scope, new_ulid
from nexus.shared.logging import get_logger

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.client import DynamoDBClient

logger = get_logger(__name__)

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()

ItemDict = dict[str, Any]


# --------------------------------------------------------------------- serializacao


def _sanitize(value: Any) -> Any:
    """Converte tipos que o serializador do DynamoDB nao aceita.

    ``float`` e rejeitado por perda de precisao; a conversao passa por ``str`` para
    preservar o valor exato que chegou.
    """
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _to_item(data: ItemDict) -> ItemDict:
    """Converte um dicionario Python em item DynamoDB, omitindo valores nulos.

    Atributos ausentes importam: ``pending_shard`` igual a ``None`` deve **nao existir**
    no item, senao o indice esparso deixa de ser esparso (ADR-003).
    """
    return {
        key: _serializer.serialize(_sanitize(value))
        for key, value in data.items()
        if value is not None
    }


def _pythonize(value: Any) -> Any:
    """Converte tipos do DynamoDB de volta para tipos Python nativos.

    O DynamoDB devolve todo numero como ``Decimal``. Isso e correto para precisao, mas
    ``Decimal`` nao e serializavel em JSON — e o corpo de resposta armazenado para
    replay de idempotencia e devolvido ao cliente exatamente como foi lido. Sem esta
    conversao, o replay falharia com erro 500 enquanto a ingestao original funcionaria.
    """
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: _pythonize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_pythonize(item) for item in value]
    if isinstance(value, set):
        return {_pythonize(item) for item in value}
    return value


def _from_item(item: ItemDict) -> ItemDict:
    return {key: _pythonize(_deserializer.deserialize(value)) for key, value in item.items()}


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, Decimal):
        return int(value)
    if isinstance(value, int):
        return value
    return default


def _parse_dt(value: Any) -> datetime:
    return datetime.fromisoformat(str(value))


# ---------------------------------------------------------------------------- chaves


def record_pk(record_id: str) -> str:
    return f"RECORD#{record_id}"


def idempotency_pk(source: str, key: str) -> str:
    import hashlib

    digest = hashlib.sha256(idempotency_scope(source, key).encode("utf-8")).hexdigest()
    return f"IDEMP#{digest}"


def outbox_pk(event_id: str) -> str:
    return f"OUTBOX#{event_id}"


def processed_pk(record_id: str, version: str) -> str:
    """Chave do marcador de processamento — ADR-005 e ADR-007.

    Derivada do ``record_id``, nao do ``event_id``: a unicidade que importa e "esta
    observacao foi processada", e uma observacao pode receber mais de um evento se o
    outbox republicar.

    A versao do processador entra na chave. Sem ela, trocar o processador nao
    reprocessaria nada — o marcador antigo existe e a escrita condicional recusaria.
    Com ela, a chave nova nao colide, o acervo reprocessa e o resultado anterior
    permanece consultavel.
    """
    return f"PROCESSED#{record_id}#{version}"


def recency_pk(record_type: RecordType) -> str:
    return f"RECORDS#{record_type.value}"


# ------------------------------------------------------------- entity resolution

#: Limite do DynamoDB para itens numa transacao.
TRANSACT_MAX_ITEMS = 100

STATS_KEY = "STATS#resolution"
#: Item unico que guarda a cota ja consumida pela semeadura da demonstracao.
DEMO_QUOTA_KEY = "DEMO#quota"


def block_pk(key: str) -> str:
    return f"BLOCK#{key}"


def entity_pk(entity_id: str) -> str:
    return f"ENTITY#{entity_id}"


def member_sk(record_id: str) -> str:
    return f"MEMBER#{record_id}"


def merge_sk(event_id: str) -> str:
    return f"MERGE#{event_id}"


def review_pk(pair_id: str) -> str:
    return f"REVIEW#{pair_id}"


# ----------------------------------------------------------------- observabilidade


def trail_pk(record_id: str) -> str:
    return f"TRAIL#{record_id}"


def trail_sk(occurred_at: datetime, event_id: str) -> str:
    """Carimbo primeiro, identificador depois.

    Assim a ``Query`` devolve os marcos ja em ordem cronologica, sem ordenar em
    memoria. O identificador desempata marcos emitidos no mesmo milissegundo por
    processos diferentes.
    """
    return f"{occurred_at.isoformat()}#{event_id}"


def series_pk(metric: str) -> str:
    return f"SERIES#{metric}"


# ------------------------------------------------------------------------- cursores


def _encode_cursor(key: ItemDict) -> str:
    raw = json.dumps(_from_item(key), separators=(",", ":"), default=str)
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_cursor(cursor: str) -> ItemDict:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        data = json.loads(raw)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise InvalidPaginationCursorError("Cursor de paginacao invalido") from exc
    if not isinstance(data, dict) or not data:
        raise InvalidPaginationCursorError("Cursor de paginacao invalido")
    return _to_item(data)


# -------------------------------------------------------------------- mapeamento


def _record_to_item(record: StoredRecord) -> ItemDict:
    return {
        "pk": record_pk(record.record_id),
        "sk": record_pk(record.record_id),
        "entity": "record",
        "record_id": record.record_id,
        "record_type": record.record_type.value,
        "source": record.source,
        "natural_key": record.natural_key,
        "record_fingerprint": record.record_fingerprint,
        "recency_pk": recency_pk(record.record_type),
        "payload": record.payload,
        "normalized": record.normalized,
        "correlation_id": record.correlation_id,
        "created_at": record.created_at.isoformat(),
        "seen_count": record.seen_count,
    }


def _item_to_record(data: ItemDict) -> StoredRecord:
    return StoredRecord(
        record_id=str(data["record_id"]),
        record_type=RecordType(data["record_type"]),
        source=str(data["source"]),
        natural_key=str(data["natural_key"]),
        record_fingerprint=str(data["record_fingerprint"]),
        payload=dict(data.get("payload") or {}),
        normalized=dict(data.get("normalized") or {}),
        correlation_id=str(data.get("correlation_id", "")),
        created_at=_parse_dt(data["created_at"]),
        seen_count=_as_int(data.get("seen_count"), 1),
    )


def _event_to_item(event: OutboxEvent) -> ItemDict:
    item: ItemDict = {
        "pk": outbox_pk(event.event_id),
        "sk": outbox_pk(event.event_id),
        "entity": "outbox",
        "event_id": event.event_id,
        "record_id": event.record_id,
        "correlation_id": event.correlation_id,
        "created_at": event.created_at.isoformat(),
        "next_attempt_at": event.next_attempt_at.isoformat(),
        "status": event.status.value,
        "attempts": event.attempts,
        "last_error": event.last_error,
    }
    # Presente apenas enquanto pendente: e o que torna o indice esparso (ADR-003).
    if event.pending_shard is not None:
        item["pending_shard"] = event.pending_shard
    return item


def _item_to_event(data: ItemDict) -> OutboxEvent:
    shard = data.get("pending_shard")
    return OutboxEvent(
        event_id=str(data["event_id"]),
        record_id=str(data["record_id"]),
        correlation_id=str(data.get("correlation_id", "")),
        created_at=_parse_dt(data["created_at"]),
        next_attempt_at=_parse_dt(data["next_attempt_at"]),
        status=OutboxStatus(data.get("status", "pending")),
        attempts=_as_int(data.get("attempts")),
        pending_shard=str(shard) if shard is not None else None,
        last_error=data.get("last_error"),
    )


def _processing_to_item(result: ProcessingResult) -> ItemDict:
    key = processed_pk(result.record_id, result.processor_version)
    return {
        "pk": key,
        "sk": key,
        "entity": "processing_result",
        "record_id": result.record_id,
        "event_id": result.event_id,
        "status": result.status.value,
        "processor_version": result.processor_version,
        "worker_id": result.worker_id,
        "attempts": result.attempts,
        "duration_ms": result.duration_ms,
        "end_to_end_ms": result.end_to_end_ms,
        "summary": result.summary,
        "correlation_id": result.correlation_id,
        "processed_at": result.processed_at.isoformat(),
    }


def _item_to_processing(data: ItemDict) -> ProcessingResult:
    return ProcessingResult(
        record_id=str(data["record_id"]),
        event_id=str(data.get("event_id", "")),
        status=ProcessingStatus(data.get("status", "succeeded")),
        worker_id=str(data.get("worker_id", "")),
        attempts=_as_int(data.get("attempts")),
        duration_ms=float(data.get("duration_ms") or 0.0),
        summary=dict(data.get("summary") or {}),
        correlation_id=str(data.get("correlation_id", "")),
        processed_at=_parse_dt(data["processed_at"]),
        processor_version=str(data.get("processor_version", "pipeline-v1")),
        end_to_end_ms=(
            float(data["end_to_end_ms"]) if data.get("end_to_end_ms") is not None else None
        ),
    )


def _entity_to_item(entity: Entity) -> ItemDict:
    key = entity_pk(entity.entity_id)
    return {
        "pk": key,
        "sk": key,
        "entity": "entity",
        "entity_id": entity.entity_id,
        "record_type": entity.record_type.value,
        "member_count": entity.member_count,
        "version": entity.version,
        "created_at": entity.created_at.isoformat(),
        "updated_at": entity.updated_at.isoformat(),
        "flagged": entity.flagged,
        "flag_reason": entity.flag_reason,
    }


def _item_to_entity(data: ItemDict) -> Entity:
    return Entity(
        entity_id=str(data["entity_id"]),
        record_type=RecordType(data["record_type"]),
        member_count=_as_int(data.get("member_count")),
        version=_as_int(data.get("version")),
        created_at=_parse_dt(data["created_at"]),
        updated_at=_parse_dt(data["updated_at"]),
        flagged=bool(data.get("flagged", False)),
        flag_reason=data.get("flag_reason"),
    )


def _member_to_item(member: EntityMember) -> ItemDict:
    return {
        "pk": entity_pk(member.entity_id),
        "sk": member_sk(member.record_id),
        "entity": "entity_member",
        "entity_id": member.entity_id,
        "record_id": member.record_id,
        "joined_at": member.joined_at.isoformat(),
        "score": member.score,
        "matched_record_id": member.matched_record_id,
        "evidence": member.evidence,
    }


def _item_to_member(data: ItemDict) -> EntityMember:
    return EntityMember(
        entity_id=str(data["entity_id"]),
        record_id=str(data["record_id"]),
        joined_at=_parse_dt(data["joined_at"]),
        score=float(data.get("score") or 0.0),
        matched_record_id=data.get("matched_record_id"),
        evidence=dict(data.get("evidence") or {}),
    )


def _merge_to_item(event: MergeEvent) -> ItemDict:
    return {
        "pk": entity_pk(event.entity_id),
        "sk": merge_sk(event.event_id),
        "entity": "merge_event",
        "entity_id": event.entity_id,
        "event_id": event.event_id,
        "source_entity_id": event.source_entity_id,
        "record_a": event.record_a,
        "record_b": event.record_b,
        "score": event.score,
        "moved_members": event.moved_members,
        "created_at": event.created_at.isoformat(),
    }


def _item_to_merge(data: ItemDict) -> MergeEvent:
    return MergeEvent(
        entity_id=str(data["entity_id"]),
        event_id=str(data["event_id"]),
        source_entity_id=str(data["source_entity_id"]),
        record_a=str(data["record_a"]),
        record_b=str(data["record_b"]),
        score=float(data.get("score") or 0.0),
        moved_members=_as_int(data.get("moved_members")),
        created_at=_parse_dt(data["created_at"]),
    )


def _link_to_item(record_id: str, entity_id: str) -> ItemDict:
    """Vinculo reverso: fica na particao da observacao.

    Permite descobrir a entidade de um registro na mesma `Query` que le o registro —
    o beneficio concreto da modelagem single-table.
    """
    return {
        "pk": record_pk(record_id),
        "sk": entity_pk(entity_id),
        "entity": "entity_link",
        "record_id": record_id,
        "entity_id": entity_id,
    }


def _review_to_item(item: ReviewItem) -> ItemDict:
    key = review_pk(item.pair_id)
    payload: ItemDict = {
        "pk": key,
        "sk": key,
        "entity": "review",
        "pair_id": item.pair_id,
        "record_a": item.record_a,
        "record_b": item.record_b,
        "record_type": item.record_type.value,
        "score": item.score,
        "evidence": item.evidence,
        "status": item.status.value,
        "created_at": item.created_at.isoformat(),
        "decided_at": item.decided_at.isoformat() if item.decided_at else None,
        "reason": item.reason,
    }
    # Presente apenas enquanto pendente: e o que torna gsi_review esparso.
    if item.review_shard is not None:
        payload["review_shard"] = item.review_shard
    return payload


def _item_to_review(data: ItemDict) -> ReviewItem:
    shard = data.get("review_shard")
    decided = data.get("decided_at")
    return ReviewItem(
        pair_id=str(data["pair_id"]),
        record_a=str(data["record_a"]),
        record_b=str(data["record_b"]),
        record_type=RecordType(data["record_type"]),
        score=float(data.get("score") or 0.0),
        evidence=dict(data.get("evidence") or {}),
        created_at=_parse_dt(data["created_at"]),
        status=ReviewStatus(data.get("status", "pending")),
        review_shard=str(shard) if shard is not None else None,
        decided_at=_parse_dt(decided) if decided else None,
        reason=data.get("reason"),
    )


def _idempotency_to_item(record: IdempotencyRecord) -> ItemDict:
    key = idempotency_pk(record.source, record.idempotency_key)
    return {
        "pk": key,
        "sk": key,
        "entity": "idempotency",
        "source": record.source,
        "idempotency_key": record.idempotency_key,
        "request_hash": record.request_hash,
        "record_id": record.record_id,
        "status_code": record.status_code,
        "response_body": record.response_body,
        "created_at": record.created_at.isoformat(),
        "expires_at": record.expires_at,
    }


def _item_to_idempotency(data: ItemDict) -> IdempotencyRecord:
    return IdempotencyRecord(
        source=str(data["source"]),
        idempotency_key=str(data["idempotency_key"]),
        request_hash=str(data["request_hash"]),
        record_id=str(data["record_id"]),
        status_code=_as_int(data["status_code"], 200),
        response_body=dict(data.get("response_body") or {}),
        created_at=_parse_dt(data["created_at"]),
        expires_at=_as_int(data.get("expires_at")),
    )


# ------------------------------------------------------------------- repositorio


class DynamoRecordRepository(RecordRepository):
    """Repositorio single-table sobre DynamoDB."""

    def __init__(
        self,
        client: DynamoDBClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client or build_client(self._settings)
        self._table = self._settings.dynamo_table

    # ------------------------------------------------------------------ infra

    def ensure_ready(self) -> None:
        wait_for_dynamodb(self._client)
        ensure_table(self._client, self._settings)

    def ping(self) -> bool:
        """Uma unica chamada de metadado — nao le dados nem conta itens."""
        try:
            self._client.describe_table(TableName=self._table)
        except (ClientError, BotoCoreError) as exc:
            logger.warning("persistence_ping_failed", extra={"reason": str(exc)})
            return False
        return True

    def _fail(self, operation: str, exc: Exception) -> PersistenceError:
        logger.error("persistence_error", extra={"operation": operation, "reason": str(exc)})
        return PersistenceError("Falha ao acessar a camada de persistencia")

    # ----------------------------------------------------------- idempotencia

    def find_idempotency(self, source: str, idempotency_key: str) -> IdempotencyRecord | None:
        key = idempotency_pk(source, idempotency_key)
        try:
            response = self._client.get_item(
                TableName=self._table,
                Key={"pk": {"S": key}, "sk": {"S": key}},
                ConsistentRead=True,  # leitura na tabela base: consistencia forte
            )
        except (ClientError, BotoCoreError) as exc:
            raise self._fail("find_idempotency", exc) from exc

        item = response.get("Item")
        if not item:
            return None
        return _item_to_idempotency(_from_item(item))

    # ------------------------------------------------------------ observacoes

    def find_by_fingerprint(self, natural_key: str, fingerprint: str) -> StoredRecord | None:
        try:
            response = self._client.query(
                TableName=self._table,
                IndexName=GSI_NATURAL,
                KeyConditionExpression="natural_key = :nk AND record_fingerprint = :fp",
                ExpressionAttributeValues={
                    ":nk": {"S": natural_key},
                    ":fp": {"S": fingerprint},
                },
                Limit=1,
            )
        except (ClientError, BotoCoreError) as exc:
            raise self._fail("find_by_fingerprint", exc) from exc

        items = response.get("Items") or []
        if not items:
            return None
        return _item_to_record(_from_item(items[0]))

    def get_record(self, record_id: str) -> StoredRecord | None:
        key = record_pk(record_id)
        try:
            response = self._client.get_item(
                TableName=self._table,
                Key={"pk": {"S": key}, "sk": {"S": key}},
                ConsistentRead=True,
            )
        except (ClientError, BotoCoreError) as exc:
            raise self._fail("get_record", exc) from exc

        item = response.get("Item")
        if not item:
            return None
        return _item_to_record(_from_item(item))

    def list_records(
        self,
        record_type: RecordType,
        *,
        limit: int,
        cursor: str | None = None,
    ) -> Page:
        kwargs: dict[str, Any] = {
            "TableName": self._table,
            "IndexName": GSI_RECENCY,
            "KeyConditionExpression": "recency_pk = :rp",
            "ExpressionAttributeValues": {":rp": {"S": recency_pk(record_type)}},
            "Limit": limit,
            "ScanIndexForward": False,  # ULID ordena por tempo: False = mais recentes
        }
        if cursor:
            kwargs["ExclusiveStartKey"] = _decode_cursor(cursor)

        try:
            response = self._client.query(**kwargs)
        except (ClientError, BotoCoreError) as exc:
            raise self._fail("list_records", exc) from exc

        items = [_item_to_record(_from_item(raw)) for raw in response.get("Items") or []]
        last_key = response.get("LastEvaluatedKey")
        return Page(items=items, next_cursor=_encode_cursor(last_key) if last_key else None)

    # ---------------------------------------------------------------- escrita

    def _transact(self, operation: str, actions: list[dict[str, Any]]) -> None:
        try:
            # As acoes sao montadas dinamicamente; os TypedDicts do boto3-stubs
            # nao expressam essa construcao sem duplicar o schema inteiro.
            self._client.transact_write_items(TransactItems=cast(Any, actions))
        except self._client.exceptions.TransactionCanceledException as exc:
            reasons = [reason.get("Code") for reason in exc.response.get("CancellationReasons", [])]
            if "ConditionalCheckFailed" in reasons:
                logger.info("commit_conflict", extra={"operation": operation, "reasons": reasons})
                raise CommitConflictError(operation) from exc
            raise self._fail(operation, exc) from exc
        except (ClientError, BotoCoreError) as exc:
            raise self._fail(operation, exc) from exc

    def commit_ingestion(
        self,
        record: StoredRecord,
        event: OutboxEvent,
        idempotency: IdempotencyRecord,
    ) -> None:
        self._transact(
            "commit_ingestion",
            [
                {
                    "Put": {
                        "TableName": self._table,
                        "Item": _to_item(_record_to_item(record)),
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
                {
                    "Put": {
                        "TableName": self._table,
                        "Item": _to_item(_event_to_item(event)),
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
                {
                    "Put": {
                        "TableName": self._table,
                        "Item": _to_item(_idempotency_to_item(idempotency)),
                        # Serializa requisicoes concorrentes com a mesma chave:
                        # exatamente uma vence, as demais releem e devolvem o resultado.
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
            ],
        )

    def register_duplicate(self, record_id: str, idempotency: IdempotencyRecord) -> None:
        key = record_pk(record_id)
        self._transact(
            "register_duplicate",
            [
                {
                    "Update": {
                        "TableName": self._table,
                        "Key": {"pk": {"S": key}, "sk": {"S": key}},
                        "UpdateExpression": "SET seen_count = seen_count + :one",
                        "ExpressionAttributeValues": {":one": {"N": "1"}},
                        "ConditionExpression": "attribute_exists(pk)",
                    }
                },
                {
                    "Put": {
                        "TableName": self._table,
                        "Item": _to_item(_idempotency_to_item(idempotency)),
                        "ConditionExpression": "attribute_not_exists(pk)",
                    }
                },
            ],
        )

    # ---------------------------------------------------------------- consumo

    def commit_processing(self, result: ProcessingResult) -> None:
        """Escrita condicional unica: o item e o resultado e o marcador — ADR-005."""
        try:
            self._client.put_item(
                TableName=self._table,
                Item=_to_item(_processing_to_item(result)),
                ConditionExpression="attribute_not_exists(pk)",
            )
        except self._client.exceptions.ConditionalCheckFailedException as exc:
            logger.info("processing_already_committed", extra={"record_id": result.record_id})
            raise CommitConflictError("commit_processing") from exc
        except (ClientError, BotoCoreError) as exc:
            raise self._fail("commit_processing", exc) from exc

    def find_processing_result(self, record_id: str, version: str) -> ProcessingResult | None:
        key = processed_pk(record_id, version)
        try:
            response = self._client.get_item(
                TableName=self._table,
                Key={"pk": {"S": key}, "sk": {"S": key}},
                ConsistentRead=True,
            )
        except (ClientError, BotoCoreError) as exc:
            raise self._fail("find_processing_result", exc) from exc

        item = response.get("Item")
        if not item:
            return None
        return _item_to_processing(_from_item(item))

    # ----------------------------------------------------------------- outbox

    def get_outbox_event(self, event_id: str) -> OutboxEvent | None:
        key = outbox_pk(event_id)
        try:
            response = self._client.get_item(
                TableName=self._table,
                Key={"pk": {"S": key}, "sk": {"S": key}},
                ConsistentRead=True,
            )
        except (ClientError, BotoCoreError) as exc:
            raise self._fail("get_outbox_event", exc) from exc

        item = response.get("Item")
        if not item:
            return None
        return _item_to_event(_from_item(item))

    def mark_outbox_dispatched(self, event_id: str) -> None:
        key = outbox_pk(event_id)
        try:
            self._client.update_item(
                TableName=self._table,
                Key={"pk": {"S": key}, "sk": {"S": key}},
                # REMOVE tira o item do indice esparso — ADR-003.
                UpdateExpression="SET #st = :dispatched REMOVE pending_shard",
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={":dispatched": {"S": OutboxStatus.DISPATCHED.value}},
                ConditionExpression="attribute_exists(pk)",
            )
        except self._client.exceptions.ConditionalCheckFailedException:
            logger.warning("outbox_event_missing", extra={"event_id": event_id})
        except (ClientError, BotoCoreError) as exc:
            raise self._fail("mark_outbox_dispatched", exc) from exc

    def reschedule_outbox(self, event_id: str, *, error: str, now: datetime) -> OutboxEvent:
        event = self.get_outbox_event(event_id)
        if event is None:
            raise PersistenceError("Evento de outbox inexistente")

        attempts = event.attempts + 1
        key = outbox_pk(event_id)
        exhausted = attempts >= self._settings.outbox_max_attempts

        if exhausted:
            # Sai do indice esparso para nao bloquear os demais eventos.
            update = "SET #st = :failed, attempts = :a, last_error = :e REMOVE pending_shard"
            values: dict[str, Any] = {
                ":failed": {"S": OutboxStatus.FAILED.value},
                ":a": {"N": str(attempts)},
                ":e": {"S": error[:512]},
            }
            next_attempt = event.next_attempt_at
            shard: str | None = None
            status = OutboxStatus.FAILED
        else:
            backoff = self._settings.outbox_backoff_base_seconds * (2 ** (attempts - 1))
            next_attempt = now + timedelta(seconds=backoff)
            update = "SET attempts = :a, next_attempt_at = :n, last_error = :e"
            values = {
                ":a": {"N": str(attempts)},
                ":n": {"S": next_attempt.isoformat()},
                ":e": {"S": error[:512]},
            }
            shard = event.pending_shard
            status = event.status

        update_kwargs: dict[str, Any] = {
            "TableName": self._table,
            "Key": {"pk": {"S": key}, "sk": {"S": key}},
            "UpdateExpression": update,
            "ExpressionAttributeValues": values,
            "ConditionExpression": "attribute_exists(pk)",
        }
        # Um mapa vazio de ExpressionAttributeNames e recusado pelo DynamoDB:
        # o parametro precisa ser omitido, nao enviado vazio.
        if exhausted:
            update_kwargs["ExpressionAttributeNames"] = {"#st": "status"}

        try:
            self._client.update_item(**update_kwargs)
        except (ClientError, BotoCoreError) as exc:
            raise self._fail("reschedule_outbox", exc) from exc

        logger.warning(
            "outbox_retry_scheduled" if not exhausted else "outbox_event_failed",
            extra={"event_id": event_id, "attempts": attempts, "reason": error[:256]},
        )

        from dataclasses import replace

        return replace(
            event,
            attempts=attempts,
            next_attempt_at=next_attempt,
            status=status,
            pending_shard=shard,
            last_error=error[:512],
        )

    def list_pending_outbox(self, shard: str, *, limit: int, now: datetime) -> list[str]:
        try:
            response = self._client.query(
                TableName=self._table,
                IndexName=GSI_OUTBOX_PENDING,
                KeyConditionExpression="pending_shard = :s AND next_attempt_at <= :n",
                ExpressionAttributeValues={
                    ":s": {"S": shard},
                    ":n": {"S": now.isoformat()},
                },
                Limit=limit,
            )
        except (ClientError, BotoCoreError) as exc:
            raise self._fail("list_pending_outbox", exc) from exc

        # Projecao KEYS_ONLY: o indice devolve as chaves, nao o conteudo.
        return [
            str(_deserializer.deserialize(item["pk"])).removeprefix("OUTBOX#")
            for item in response.get("Items") or []
        ]

    # ------------------------------------------------- entity resolution: blocos

    def put_blocking_keys(self, record_id: str, record_type: RecordType, keys: list[str]) -> None:
        if not keys:
            return
        now = utcnow().isoformat()
        try:
            for key in keys:
                self._client.put_item(
                    TableName=self._table,
                    Item=_to_item(
                        {
                            "pk": block_pk(key),
                            "sk": record_pk(record_id),
                            "entity": "block",
                            "block_key": key,
                            "record_id": record_id,
                            "record_type": record_type.value,
                            "indexed_at": now,
                        }
                    ),
                )
        except (ClientError, BotoCoreError) as exc:
            raise self._fail("put_blocking_keys", exc) from exc

    def find_block_candidates(
        self, keys: list[str], *, limit: int, exclude: str | None = None
    ) -> tuple[list[str], bool]:
        found: list[str] = []
        seen: set[str] = set()
        truncated = False

        for key in keys:
            if len(found) >= limit:
                truncated = True
                break
            try:
                response = self._client.query(
                    TableName=self._table,
                    KeyConditionExpression="pk = :pk",
                    ExpressionAttributeValues={":pk": {"S": block_pk(key)}},
                    Limit=limit - len(found) + 1,
                )
            except (ClientError, BotoCoreError) as exc:
                raise self._fail("find_block_candidates", exc) from exc

            items = response.get("Items") or []
            if response.get("LastEvaluatedKey"):
                truncated = True
            for raw in items:
                data = _from_item(raw)
                candidate = str(data["record_id"])
                if candidate == exclude or candidate in seen:
                    continue
                if len(found) >= limit:
                    truncated = True
                    break
                seen.add(candidate)
                found.append(candidate)

        return found, truncated

    # ----------------------------------------------- entity resolution: entidades

    def get_entity(self, entity_id: str) -> Entity | None:
        key = entity_pk(entity_id)
        try:
            response = self._client.get_item(
                TableName=self._table,
                Key={"pk": {"S": key}, "sk": {"S": key}},
                ConsistentRead=True,
            )
        except (ClientError, BotoCoreError) as exc:
            raise self._fail("get_entity", exc) from exc
        item = response.get("Item")
        return _item_to_entity(_from_item(item)) if item else None

    def find_entity_id_for_record(self, record_id: str) -> str | None:
        try:
            response = self._client.query(
                TableName=self._table,
                KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
                ExpressionAttributeValues={
                    ":pk": {"S": record_pk(record_id)},
                    ":prefix": {"S": "ENTITY#"},
                },
                ConsistentRead=True,
                Limit=1,
            )
        except (ClientError, BotoCoreError) as exc:
            raise self._fail("find_entity_id_for_record", exc) from exc
        items = response.get("Items") or []
        return str(_from_item(items[0])["entity_id"]) if items else None

    def _query_entity_children(self, entity_id: str, prefix: str) -> list[ItemDict]:
        collected: list[ItemDict] = []
        start_key: ItemDict | None = None
        while True:
            kwargs: dict[str, Any] = {
                "TableName": self._table,
                "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
                "ExpressionAttributeValues": {
                    ":pk": {"S": entity_pk(entity_id)},
                    ":prefix": {"S": prefix},
                },
            }
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key
            try:
                response = self._client.query(**kwargs)
            except (ClientError, BotoCoreError) as exc:
                raise self._fail("query_entity_children", exc) from exc
            collected.extend(_from_item(raw) for raw in response.get("Items") or [])
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                return collected

    def list_entity_members(self, entity_id: str) -> list[EntityMember]:
        return [_item_to_member(data) for data in self._query_entity_children(entity_id, "MEMBER#")]

    def list_merge_events(self, entity_id: str) -> list[MergeEvent]:
        return [_item_to_merge(data) for data in self._query_entity_children(entity_id, "MERGE#")]

    def create_entity(self, entity: Entity, members: list[EntityMember]) -> None:
        actions: list[dict[str, Any]] = [
            {
                "Put": {
                    "TableName": self._table,
                    "Item": _to_item(_entity_to_item(entity)),
                    "ConditionExpression": "attribute_not_exists(pk)",
                }
            }
        ]
        for member in members:
            actions.append(
                {"Put": {"TableName": self._table, "Item": _to_item(_member_to_item(member))}}
            )
            actions.append(
                {
                    "Put": {
                        "TableName": self._table,
                        "Item": _to_item(_link_to_item(member.record_id, entity.entity_id)),
                    }
                }
            )
        self._transact("create_entity", actions)

    def add_member(self, entity: Entity, member: EntityMember) -> Entity:
        now = utcnow()
        self._transact(
            "add_member",
            [
                {
                    "Update": {
                        "TableName": self._table,
                        "Key": {
                            "pk": {"S": entity_pk(entity.entity_id)},
                            "sk": {"S": entity_pk(entity.entity_id)},
                        },
                        "UpdateExpression": (
                            "SET member_count = member_count + :one, "
                            "#v = #v + :one, updated_at = :now"
                        ),
                        "ExpressionAttributeNames": {"#v": "version"},
                        "ExpressionAttributeValues": {
                            ":one": {"N": "1"},
                            ":now": {"S": now.isoformat()},
                            ":version": {"N": str(entity.version)},
                        },
                        # Concorrencia otimista: se outro worker mexeu na entidade
                        # desde a leitura, esta escrita falha e a mensagem e retentada.
                        "ConditionExpression": "#v = :version",
                    }
                },
                {"Put": {"TableName": self._table, "Item": _to_item(_member_to_item(member))}},
                {
                    "Put": {
                        "TableName": self._table,
                        "Item": _to_item(_link_to_item(member.record_id, entity.entity_id)),
                    }
                },
            ],
        )
        from dataclasses import replace

        return replace(
            entity,
            member_count=entity.member_count + 1,
            version=entity.version + 1,
            updated_at=now,
        )

    def merge_entities(
        self, target: Entity, source: Entity, members: list[EntityMember], event: MergeEvent
    ) -> Entity:
        """Move os vinculos da origem para o destino numa unica transacao.

        Cada membro movido custa tres operacoes (gravar no destino, apagar da origem,
        atualizar o vinculo reverso). Com o teto de tamanho de cluster, o total fica
        confortavelmente abaixo do limite de 100 itens por transacao do DynamoDB.
        """
        now = utcnow()
        required = len(members) * 3 + 3
        if required > TRANSACT_MAX_ITEMS:
            raise PersistenceError(
                f"fusao exigiria {required} operacoes, acima do limite de {TRANSACT_MAX_ITEMS}"
            )

        actions: list[dict[str, Any]] = [
            {
                "Update": {
                    "TableName": self._table,
                    "Key": {
                        "pk": {"S": entity_pk(target.entity_id)},
                        "sk": {"S": entity_pk(target.entity_id)},
                    },
                    "UpdateExpression": (
                        "SET member_count = member_count + :moved, "
                        "#v = #v + :one, updated_at = :now"
                    ),
                    "ExpressionAttributeNames": {"#v": "version"},
                    "ExpressionAttributeValues": {
                        ":moved": {"N": str(len(members))},
                        ":one": {"N": "1"},
                        ":now": {"S": now.isoformat()},
                        ":version": {"N": str(target.version)},
                    },
                    "ConditionExpression": "#v = :version",
                }
            },
            {
                "Delete": {
                    "TableName": self._table,
                    "Key": {
                        "pk": {"S": entity_pk(source.entity_id)},
                        "sk": {"S": entity_pk(source.entity_id)},
                    },
                    "ExpressionAttributeNames": {"#v": "version"},
                    "ExpressionAttributeValues": {":version": {"N": str(source.version)}},
                    "ConditionExpression": "#v = :version",
                }
            },
            {"Put": {"TableName": self._table, "Item": _to_item(_merge_to_item(event))}},
        ]

        from dataclasses import replace as _replace

        for member in members:
            moved = _replace(member, entity_id=target.entity_id)
            actions.append(
                {"Put": {"TableName": self._table, "Item": _to_item(_member_to_item(moved))}}
            )
            actions.append(
                {
                    "Delete": {
                        "TableName": self._table,
                        "Key": {
                            "pk": {"S": entity_pk(source.entity_id)},
                            "sk": {"S": member_sk(member.record_id)},
                        },
                    }
                }
            )
            actions.append(
                {
                    "Put": {
                        "TableName": self._table,
                        "Item": _to_item(_link_to_item(member.record_id, target.entity_id)),
                    }
                }
            )

        self._transact("merge_entities", actions)
        return _replace(
            target,
            member_count=target.member_count + len(members),
            version=target.version + 1,
            updated_at=now,
        )

    def flag_entity(self, entity_id: str, reason: str) -> None:
        try:
            self._client.update_item(
                TableName=self._table,
                Key={"pk": {"S": entity_pk(entity_id)}, "sk": {"S": entity_pk(entity_id)}},
                UpdateExpression="SET flagged = :t, flag_reason = :r, updated_at = :now",
                ExpressionAttributeValues={
                    ":t": {"BOOL": True},
                    ":r": {"S": reason[:512]},
                    ":now": {"S": utcnow().isoformat()},
                },
                ConditionExpression="attribute_exists(pk)",
            )
        except self._client.exceptions.ConditionalCheckFailedException:
            logger.warning("flag_entity_missing", extra={"entity_id": entity_id})
        except (ClientError, BotoCoreError) as exc:
            raise self._fail("flag_entity", exc) from exc

    # -------------------------------------------------- entity resolution: revisao

    def put_review(self, item: ReviewItem) -> bool:
        try:
            self._client.put_item(
                TableName=self._table,
                Item=_to_item(_review_to_item(item)),
                ConditionExpression="attribute_not_exists(pk)",
            )
        except self._client.exceptions.ConditionalCheckFailedException:
            logger.info("review_already_known", extra={"pair_id": item.pair_id})
            return False
        except (ClientError, BotoCoreError) as exc:
            raise self._fail("put_review", exc) from exc
        return True

    def get_review(self, pair_id: str) -> ReviewItem | None:
        key = review_pk(pair_id)
        try:
            response = self._client.get_item(
                TableName=self._table,
                Key={"pk": {"S": key}, "sk": {"S": key}},
                ConsistentRead=True,
            )
        except (ClientError, BotoCoreError) as exc:
            raise self._fail("get_review", exc) from exc
        item = response.get("Item")
        return _item_to_review(_from_item(item)) if item else None

    def list_pending_reviews(self, *, limit: int) -> list[ReviewItem]:
        pair_ids: list[str] = []
        for shard_index in range(self._settings.resolution_review_shards):
            if len(pair_ids) >= limit:
                break
            try:
                response = self._client.query(
                    TableName=self._table,
                    IndexName=GSI_REVIEW,
                    KeyConditionExpression="review_shard = :s",
                    ExpressionAttributeValues={":s": {"S": f"REVIEW#{shard_index}"}},
                    Limit=limit - len(pair_ids),
                )
            except (ClientError, BotoCoreError) as exc:
                raise self._fail("list_pending_reviews", exc) from exc
            # Projecao KEYS_ONLY: o indice da a chave, o conteudo vem da tabela base.
            for raw in response.get("Items") or []:
                pair_ids.append(str(_deserializer.deserialize(raw["pk"])).removeprefix("REVIEW#"))

        reviews = [self.get_review(pair_id) for pair_id in pair_ids]
        return [review for review in reviews if review is not None]

    def decide_review(self, pair_id: str, status: ReviewStatus, reason: str | None) -> ReviewItem:
        key = review_pk(pair_id)
        values: dict[str, Any] = {
            ":status": {"S": status.value},
            ":now": {"S": utcnow().isoformat()},
        }
        update = "SET #st = :status, decided_at = :now REMOVE review_shard"
        if reason:
            update = "SET #st = :status, decided_at = :now, reason = :reason REMOVE review_shard"
            values[":reason"] = {"S": reason[:512]}

        try:
            self._client.update_item(
                TableName=self._table,
                Key={"pk": {"S": key}, "sk": {"S": key}},
                UpdateExpression=update,
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues=values,
                ConditionExpression="attribute_exists(pk)",
            )
        except self._client.exceptions.ConditionalCheckFailedException as exc:
            raise RecordNotFoundError("Par de revisao nao encontrado") from exc
        except (ClientError, BotoCoreError) as exc:
            raise self._fail("decide_review", exc) from exc

        decided = self.get_review(pair_id)
        if decided is None:
            raise PersistenceError("Par de revisao desapareceu apos a decisao")
        return decided

    # ----------------------------------------------------------- observabilidade

    def record_trail(self, event: TrailEvent) -> bool:
        """Grava um marco. Falha e engolida de proposito — ADR-010."""
        event_id = event.event_id or new_ulid()
        expira = utcnow() + timedelta(days=self._settings.trail_retention_days)
        item = {
            "pk": trail_pk(event.record_id),
            "sk": trail_sk(event.occurred_at, event_id),
            "entity": "trail",
            "record_id": event.record_id,
            "stage": event.stage.value,
            "occurred_at": event.occurred_at.isoformat(),
            "correlation_id": event.correlation_id,
            "service": event.service,
            "detail": event.detail,
            "event_id": event_id,
            "expires_at": int(expira.timestamp()),
        }
        try:
            self._client.put_item(TableName=self._table, Item=_to_item(item))
        except (ClientError, BotoCoreError) as exc:
            # Nao propaga: a trilha explica falhas, nao as causa.
            logger.warning(
                "trail_write_failed",
                extra={
                    "record_id": event.record_id,
                    "stage": event.stage.value,
                    "reason": str(exc),
                },
            )
            return False
        return True

    def get_trail(self, record_id: str) -> list[TrailEvent]:
        eventos: list[TrailEvent] = []
        start_key: ItemDict | None = None
        while True:
            kwargs: dict[str, Any] = {
                "TableName": self._table,
                "KeyConditionExpression": "pk = :pk",
                "ExpressionAttributeValues": {":pk": {"S": trail_pk(record_id)}},
            }
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key
            try:
                response = self._client.query(**kwargs)
            except (ClientError, BotoCoreError) as exc:
                raise self._fail("get_trail", exc) from exc

            for raw in response.get("Items") or []:
                data = _from_item(raw)
                eventos.append(
                    TrailEvent(
                        record_id=str(data["record_id"]),
                        stage=TrailStage(data["stage"]),
                        occurred_at=_parse_dt(data["occurred_at"]),
                        correlation_id=str(data.get("correlation_id", "")),
                        service=str(data.get("service", "")),
                        detail=dict(data.get("detail") or {}),
                        event_id=str(data.get("event_id", "")),
                    )
                )
            start_key = response.get("LastEvaluatedKey")
            if not start_key:
                return eventos

    def put_metric_sample(self, sample: MetricSample) -> bool:
        item = {
            "pk": series_pk(sample.metric),
            "sk": sample.bucket.isoformat(),
            "entity": "metric_sample",
            "metric": sample.metric,
            "bucket": sample.bucket.isoformat(),
            "values": sample.values,
            "expires_at": sample.expires_at,
        }
        try:
            self._client.put_item(
                TableName=self._table,
                Item=_to_item(item),
                # O balde ja ocupado significa que outro observador chegou primeiro
                # neste intervalo. Nao e erro.
                ConditionExpression="attribute_not_exists(pk)",
            )
        except self._client.exceptions.ConditionalCheckFailedException:
            return False
        except (ClientError, BotoCoreError) as exc:
            logger.warning("metric_sample_failed", extra={"reason": str(exc)})
            return False
        return True

    def get_metric_series(self, metric: str, *, since: datetime) -> list[MetricSample]:
        try:
            response = self._client.query(
                TableName=self._table,
                KeyConditionExpression="pk = :pk AND sk >= :desde",
                ExpressionAttributeValues={
                    ":pk": {"S": series_pk(metric)},
                    ":desde": {"S": since.isoformat()},
                },
            )
        except (ClientError, BotoCoreError) as exc:
            raise self._fail("get_metric_series", exc) from exc

        amostras: list[MetricSample] = []
        for raw in response.get("Items") or []:
            data = _from_item(raw)
            amostras.append(
                MetricSample(
                    metric=str(data["metric"]),
                    bucket=_parse_dt(data["bucket"]),
                    values={k: float(v) for k, v in (data.get("values") or {}).items()},
                    expires_at=_as_int(data.get("expires_at")),
                )
            )
        return amostras

    def oldest_pending_outbox_at(self) -> datetime | None:
        """O evento pendente mais antigo entre todos os shards.

        Backlog parado e um problema diferente de backlog grande: cem eventos
        publicados ha um segundo sao normais; um evento parado ha uma hora nao.
        """
        mais_antigo: datetime | None = None
        for shard_index in range(self._settings.outbox_shards):
            try:
                response = self._client.query(
                    TableName=self._table,
                    IndexName=GSI_OUTBOX_PENDING,
                    KeyConditionExpression="pending_shard = :s",
                    ExpressionAttributeValues={":s": {"S": f"PENDING#{shard_index}"}},
                    Limit=1,
                    ScanIndexForward=True,
                )
            except (ClientError, BotoCoreError) as exc:
                logger.warning("oldest_pending_failed", extra={"reason": str(exc)})
                continue
            for raw in response.get("Items") or []:
                quando = _parse_dt(_deserializer.deserialize(raw["next_attempt_at"]))
                if mais_antigo is None or quando < mais_antigo:
                    mais_antigo = quando
        return mais_antigo

    # ------------------------------------------------ entity resolution: metricas

    def increment_resolution_stats(self, **counters: int) -> None:
        if not counters:
            return
        names = {f"#c{i}": name for i, name in enumerate(counters)}
        values = {f":v{i}": {"N": str(value)} for i, value in enumerate(counters.values())}
        expression = "ADD " + ", ".join(f"{alias} :v{i}" for i, alias in enumerate(names))
        try:
            self._client.update_item(
                TableName=self._table,
                Key={"pk": {"S": STATS_KEY}, "sk": {"S": STATS_KEY}},
                UpdateExpression=expression,
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
            )
        except (ClientError, BotoCoreError) as exc:
            # Metrica nunca derruba o processamento que ela descreve.
            logger.warning("resolution_stats_failed", extra={"reason": str(exc)})

    def reserve_demo_quota(self, amount: int, *, ceiling: int) -> int | None:
        """Ver o contrato. Uma unica ``UpdateItem`` condicional faz checagem e reserva."""
        if amount < 1:
            return None
        try:
            response = self._client.update_item(
                TableName=self._table,
                Key={"pk": {"S": DEMO_QUOTA_KEY}, "sk": {"S": DEMO_QUOTA_KEY}},
                UpdateExpression="ADD seeded :a",
                # O item pode nao existir ainda: a primeira reserva cria. O teto e
                # avaliado sobre o valor ANTERIOR, entao a comparacao usa o restante.
                ConditionExpression="attribute_not_exists(seeded) OR seeded <= :limite",
                ExpressionAttributeValues={
                    ":a": {"N": str(amount)},
                    ":limite": {"N": str(max(ceiling - amount, 0))},
                },
                ReturnValues="UPDATED_NEW",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return None
            raise self._fail("reserve_demo_quota", exc) from exc
        except BotoCoreError as exc:
            raise self._fail("reserve_demo_quota", exc) from exc

        total = response.get("Attributes", {}).get("seeded", {}).get("N")
        return int(total) if total is not None else amount

    def get_resolution_stats(self) -> dict[str, int]:
        try:
            response = self._client.get_item(
                TableName=self._table,
                Key={"pk": {"S": STATS_KEY}, "sk": {"S": STATS_KEY}},
                ConsistentRead=True,
            )
        except (ClientError, BotoCoreError) as exc:
            raise self._fail("get_resolution_stats", exc) from exc
        item = response.get("Item")
        if not item:
            return {}
        data = _from_item(item)
        return {
            name: _as_int(value)
            for name, value in data.items()
            if name not in {"pk", "sk", "entity"} and isinstance(value, int | float)
        }

    def count_pending_outbox(self) -> int:
        total = 0
        for shard_index in range(self._settings.outbox_shards):
            try:
                response = self._client.query(
                    TableName=self._table,
                    IndexName=GSI_OUTBOX_PENDING,
                    KeyConditionExpression="pending_shard = :s",
                    ExpressionAttributeValues={":s": {"S": f"PENDING#{shard_index}"}},
                    Select="COUNT",
                )
            except (ClientError, BotoCoreError) as exc:
                raise self._fail("count_pending_outbox", exc) from exc
            total += _as_int(response.get("Count"))
        return total
