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
    IdempotencyRecord,
    OutboxEvent,
    OutboxStatus,
    Page,
    ProcessingResult,
    ProcessingStatus,
    RecordType,
    StoredRecord,
)
from nexus.persistence.repository import CommitConflictError, RecordRepository
from nexus.persistence.tables import (
    GSI_NATURAL,
    GSI_OUTBOX_PENDING,
    GSI_RECENCY,
    build_client,
    ensure_table,
    wait_for_dynamodb,
)
from nexus.shared.config import Settings, get_settings
from nexus.shared.errors import InvalidPaginationCursorError, PersistenceError
from nexus.shared.identity import idempotency_scope
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


def processed_pk(record_id: str) -> str:
    """Chave do marcador de processamento — ADR-005.

    Derivada do ``record_id``, nao do ``event_id``: a unicidade que importa e "esta
    observacao foi processada", e uma observacao pode receber mais de um evento se o
    outbox republicar.
    """
    return f"PROCESSED#{record_id}"


def recency_pk(record_type: RecordType) -> str:
    return f"RECORDS#{record_type.value}"


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
    key = processed_pk(result.record_id)
    return {
        "pk": key,
        "sk": key,
        "entity": "processing_result",
        "record_id": result.record_id,
        "event_id": result.event_id,
        "status": result.status.value,
        "worker_id": result.worker_id,
        "attempts": result.attempts,
        "duration_ms": result.duration_ms,
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

    def find_processing_result(self, record_id: str) -> ProcessingResult | None:
        key = processed_pk(record_id)
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
