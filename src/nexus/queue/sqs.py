"""Adaptador Amazon SQS — ADR-008.

Implementa o mesmo `QueueClient` da fila SQLite. A ingestao e o worker nao sabem qual
esta ativa: a troca e uma variavel de ambiente.

## Onde o SQS difere da fila local

A fila SQLite foi escrita para **mostrar o mecanismo**; o SQS ja o tem pronto. Duas
diferencas importam:

| | SQLite (ADR-004) | SQS |
|---|---|---|
| Decide a DLQ | `fail`, comparando `receive_count` | O `redrive_policy`, pelo `maxReceiveCount` |
| O que `fail` faz | Reagenda ou move | So encurta a visibilidade |

O comportamento observavel e o mesmo — a mensagem retorna com backoff e, esgotadas as
tentativas, acaba na DLQ. O que muda e **quem** aplica a regra. Por isso o teto de
tentativas vira configuracao de infraestrutura (Terraform), nao da aplicacao.

`dead_letter` continua explicito porque o SQS nao oferece "mover agora para a DLQ":
e feito como envio para a DLQ seguido de remocao da principal.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, cast

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from nexus.queue.client import (
    FailOutcome,
    QueueClient,
    QueueMessage,
    QueueStats,
    ReceivedMessage,
)
from nexus.shared.clock import utcnow
from nexus.shared.config import Settings, get_settings
from nexus.shared.errors import QueuePublishError
from nexus.shared.logging import get_logger

if TYPE_CHECKING:
    from mypy_boto3_sqs.client import SQSClient

logger = get_logger(__name__)

MAX_ERROR_LENGTH = 512
#: Teto do SQS para mensagens por chamada de ReceiveMessage.
SQS_MAX_RECEIVE = 10
#: Atributos de contagem que o SQS expoe. Tipados porque os stubs do boto3 usam
#: Literal: passar uma string solta nao compila sob mypy --strict.
QueueCounter = Literal[
    "ApproximateNumberOfMessages",
    "ApproximateNumberOfMessagesNotVisible",
]

#: Long polling: espera ate este tempo por mensagens antes de devolver vazio.
#: Reduz chamadas vazias e, com isso, custo.
WAIT_TIME_SECONDS = 2


class SqsQueue(QueueClient):
    """Fila gerenciada pela AWS."""

    def __init__(
        self,
        client: SQSClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        if not self._settings.sqs_queue_url:
            raise ValueError("SqsQueue exige sqs_queue_url configurada")
        self._queue_url = self._settings.sqs_queue_url
        self._dlq_url = self._settings.sqs_dlq_url
        self._client = client or boto3.client("sqs", region_name=self._settings.aws_region)

    @property
    def is_enabled(self) -> bool:
        return True

    # ---------------------------------------------------------------- publicacao

    def publish(self, message: QueueMessage) -> bool:
        """Publica a mensagem.

        Devolve sempre ``True``: uma fila SQS padrao nao deduplica, entao nao ha como
        saber se o evento ja estava la. A protecao contra efeito duplicado e a escrita
        condicional do marcador de processamento (ADR-005) — que nunca dependeu da
        fila.
        """
        try:
            self._client.send_message(
                QueueUrl=self._queue_url,
                MessageBody=message.record_id,
                MessageAttributes={
                    "event_id": {"StringValue": message.event_id, "DataType": "String"},
                    "record_id": {"StringValue": message.record_id, "DataType": "String"},
                    "correlation_id": {
                        "StringValue": message.correlation_id or "-",
                        "DataType": "String",
                    },
                },
            )
        except (ClientError, BotoCoreError) as exc:
            logger.error("sqs_publish_failed", extra={"reason": str(exc)})
            raise QueuePublishError("Falha ao publicar na fila SQS") from exc
        return True

    # ------------------------------------------------------------------ consumo

    def receive(
        self, *, max_messages: int, visibility_timeout_seconds: float | None = None
    ) -> list[ReceivedMessage]:
        if max_messages < 1:
            return []
        timeout = (
            visibility_timeout_seconds
            if visibility_timeout_seconds is not None
            else self._settings.queue_visibility_timeout_seconds
        )
        try:
            response = self._client.receive_message(
                QueueUrl=self._queue_url,
                MaxNumberOfMessages=min(max_messages, SQS_MAX_RECEIVE),
                VisibilityTimeout=int(timeout),
                WaitTimeSeconds=WAIT_TIME_SECONDS,
                MessageAttributeNames=["All"],
                AttributeNames=["ApproximateReceiveCount", "SentTimestamp"],
            )
        except (ClientError, BotoCoreError) as exc:
            logger.error("sqs_receive_failed", extra={"reason": str(exc)})
            return []

        return [
            self._to_received(cast("dict[str, Any]", raw)) for raw in response.get("Messages", [])
        ]

    @staticmethod
    def _to_received(raw: dict[str, Any]) -> ReceivedMessage:
        attributes = raw.get("MessageAttributes") or {}
        system = raw.get("Attributes") or {}

        def attribute(name: str, default: str = "") -> str:
            return str(attributes.get(name, {}).get("StringValue", default))

        sent = system.get("SentTimestamp")
        # SentTimestamp vem em milissegundos desde a epoca, como string.
        enqueued = datetime.fromtimestamp(int(sent) / 1000, tz=UTC) if sent else utcnow()
        return ReceivedMessage(
            message_id=str(raw.get("MessageId", "")),
            event_id=attribute("event_id"),
            record_id=attribute("record_id", str(raw.get("Body", ""))),
            correlation_id=attribute("correlation_id"),
            # O ReceiptHandle identifica ESTA entrega, exatamente como o recibo da
            # fila local. A semantica foi copiada de la de proposito.
            receipt=str(raw.get("ReceiptHandle", "")),
            receive_count=int(system.get("ApproximateReceiveCount", 1)),
            enqueued_at=enqueued,
        )

    def delete(self, receipt: str) -> bool:
        try:
            self._client.delete_message(QueueUrl=self._queue_url, ReceiptHandle=receipt)
        except (ClientError, BotoCoreError) as exc:
            logger.warning("sqs_delete_failed", extra={"reason": str(exc)})
            return False
        return True

    def fail(self, receipt: str, *, error: str) -> FailOutcome:
        """Devolve a mensagem para a fila com backoff.

        **Nao move para a DLQ.** Quem conta tentativas e decide e o `redrive_policy`
        configurado no Terraform. Tentar decidir aqui tambem duplicaria a regra em dois
        lugares, que fatalmente divergiriam.
        """
        backoff = int(self._settings.queue_retry_backoff_base_seconds)
        try:
            self._client.change_message_visibility(
                QueueUrl=self._queue_url,
                ReceiptHandle=receipt,
                VisibilityTimeout=max(0, backoff),
            )
        except (ClientError, BotoCoreError) as exc:
            logger.warning("sqs_fail_failed", extra={"reason": str(exc)})
            return FailOutcome.UNKNOWN_RECEIPT

        logger.warning("sqs_message_failed", extra={"reason": error[:256]})
        return FailOutcome.RETRY

    def dead_letter(self, receipt: str, *, error: str) -> bool:
        """Move explicitamente para a DLQ, sem gastar tentativas.

        O SQS nao oferece essa operacao: e envio para a DLQ seguido de remocao da
        principal. A ordem importa — remover primeiro perderia a mensagem se o envio
        falhasse.
        """
        if not self._dlq_url:
            logger.warning("sqs_dead_letter_without_dlq")
            return False

        received = self.receive(max_messages=1, visibility_timeout_seconds=30)
        body = received[0].record_id if received else ""

        try:
            self._client.send_message(
                QueueUrl=self._dlq_url,
                MessageBody=body or "unknown",
                MessageAttributes={
                    "error": {"StringValue": error[:MAX_ERROR_LENGTH], "DataType": "String"},
                },
            )
            self._client.delete_message(QueueUrl=self._queue_url, ReceiptHandle=receipt)
        except (ClientError, BotoCoreError) as exc:
            logger.error("sqs_dead_letter_failed", extra={"reason": str(exc)})
            return False

        logger.warning("sqs_message_dead_lettered", extra={"reason": error[:256]})
        return True

    # ---------------------------------------------------------------- metricas

    def stats(self) -> QueueStats:
        pending = self._approximate(self._queue_url, "ApproximateNumberOfMessages")
        in_flight = self._approximate(self._queue_url, "ApproximateNumberOfMessagesNotVisible")
        dead = (
            self._approximate(self._dlq_url, "ApproximateNumberOfMessages") if self._dlq_url else 0
        )
        return QueueStats(pending=pending, in_flight=in_flight, dead=dead)

    def _approximate(self, queue_url: str | None, attribute: QueueCounter) -> int:
        """Le um contador do SQS.

        Os nomes comecam com ``Approximate`` por um motivo: o SQS e distribuido e os
        valores sao estimativas, nao contagens exatas. Usa-los para decisao de negocio
        seria um erro; para observabilidade, servem.
        """
        if not queue_url:
            return 0
        try:
            response = self._client.get_queue_attributes(
                QueueUrl=queue_url, AttributeNames=[attribute]
            )
        except (ClientError, BotoCoreError) as exc:
            logger.warning("sqs_attributes_failed", extra={"reason": str(exc)})
            return 0
        return int(response.get("Attributes", {}).get(attribute) or 0)

    def redrive(self, *, limit: int) -> int:
        """Devolve mensagens da DLQ para a fila principal e conta quantas moveu.

        Feito manualmente — receber da DLQ, enviar para a principal, apagar da DLQ —
        em vez de `StartMessageMoveTask`. Duas razoes:

        1. **Contagem exata.** `StartMessageMoveTask` e assincrono e devolveria apenas
           o teto pedido. A fila local devolve o numero real, e duas implementacoes do
           mesmo contrato nao podem divergir no que prometem.
        2. **Verificavel.** O caminho manual roda inteiro nos testes.

        Em volume alto `StartMessageMoveTask` e preferivel, por fazer o trabalho do
        lado do servico. Nos volumes deste projeto a diferenca nao se paga.

        Ordem deliberada: envia antes de apagar. Apagar primeiro perderia a mensagem
        se o envio falhasse.
        """
        if limit < 1 or not self._dlq_url:
            return 0

        moved = 0
        while moved < limit:
            try:
                response = self._client.receive_message(
                    QueueUrl=self._dlq_url,
                    MaxNumberOfMessages=min(limit - moved, SQS_MAX_RECEIVE),
                    VisibilityTimeout=30,
                    WaitTimeSeconds=0,
                    MessageAttributeNames=["All"],
                )
            except (ClientError, BotoCoreError) as exc:
                logger.error("sqs_redrive_failed", extra={"reason": str(exc)})
                break

            messages = response.get("Messages", [])
            if not messages:
                break

            for raw in messages:
                try:
                    self._client.send_message(
                        QueueUrl=self._queue_url,
                        MessageBody=str(raw.get("Body", "")),
                        MessageAttributes=raw.get("MessageAttributes") or {},
                    )
                    self._client.delete_message(
                        QueueUrl=self._dlq_url, ReceiptHandle=str(raw["ReceiptHandle"])
                    )
                except (ClientError, BotoCoreError) as exc:
                    logger.error("sqs_redrive_message_failed", extra={"reason": str(exc)})
                    continue
                moved += 1

        if moved:
            logger.info("sqs_redrive", extra={"count": moved})
        return moved
