"""Contrato da fila.

A ingestao e o worker dependem desta abstracao, nunca de SQLite ou SQS diretamente —
e o que torna a migracao para a AWS uma troca de configuracao (ARCHITECTURE.md).

O contrato cobre as duas pontas porque fila e um unico conceito: quem publica e quem
consome precisam concordar sobre visibilidade, retentativa e DLQ. Separar em duas
interfaces esconderia que ``visibility_timeout`` e ``max_receive`` sao propriedades da
fila, nao de quem a usa.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class QueueMessage:
    """Mensagem publicada pelo outbox.

    Carrega apenas identificadores. O conteudo do registro e lido da persistencia pelo
    consumidor: mensagens pequenas sao mais baratas, e o registro e a fonte de verdade.

    ``correlation_id`` viaja na mensagem para que a trilha de logs continue no worker,
    que roda em outro processo.
    """

    event_id: str
    record_id: str
    correlation_id: str


@dataclass(frozen=True, slots=True)
class ReceivedMessage:
    """Mensagem entregue a um consumidor.

    ``receipt`` identifica **esta entrega**, nao a mensagem. Se o prazo de visibilidade
    expirar e a mensagem for reentregue, o recibo antigo deixa de valer — e por isso que
    apagar com recibo vencido nao remove nada. Sem esse cuidado, um worker lento
    apagaria o trabalho que outro ja havia reivindicado.
    """

    message_id: str
    event_id: str
    record_id: str
    correlation_id: str
    receipt: str
    receive_count: int
    enqueued_at: datetime


class FailOutcome(StrEnum):
    """Destino de uma mensagem que falhou."""

    RETRY = "retry"
    DEAD_LETTERED = "dead_lettered"
    UNKNOWN_RECEIPT = "unknown_receipt"


@dataclass(frozen=True, slots=True)
class QueueStats:
    """Profundidade da fila.

    Vem do armazenamento, nao de contadores em memoria: sobrevive a reinicio e e
    consistente entre processos — ao contrario das metricas de ``/metrics``.
    """

    pending: int = 0
    in_flight: int = 0
    dead: int = 0

    @property
    def total(self) -> int:
        return self.pending + self.in_flight + self.dead


class QueueClient(ABC):
    """Publicacao e consumo de mensagens."""

    @property
    @abstractmethod
    def is_enabled(self) -> bool:
        """Indica se ha fila configurada.

        Quando ``False``, a ingestao nao tenta publicar: o evento fica pendente no
        outbox sem consumir tentativas de retry.
        """

    @abstractmethod
    def publish(self, message: QueueMessage) -> bool:
        """Publica uma mensagem. Devolve ``False`` se ela ja estava na fila.

        :raises nexus.shared.errors.QueuePublishError: falha de publicacao. Nao e fatal
            para a ingestao — o evento permanece pendente no outbox (ADR-003).
        """

    @abstractmethod
    def receive(
        self, *, max_messages: int, visibility_timeout_seconds: float | None = None
    ) -> list[ReceivedMessage]:
        """Reivindica ate ``max_messages`` mensagens visiveis.

        As mensagens ficam invisiveis para outros consumidores durante o prazo. Se o
        consumidor morrer sem apagar nem falhar, elas reaparecem sozinhas — e o que
        impede trabalho preso para sempre num processo que nao existe mais.
        """

    @abstractmethod
    def delete(self, receipt: str) -> bool:
        """Remove a mensagem desta entrega. ``False`` se o recibo nao vale mais."""

    @abstractmethod
    def fail(self, receipt: str, *, error: str) -> FailOutcome:
        """Registra falha de processamento.

        Dentro do limite de tentativas, devolve a mensagem para a fila com backoff.
        Ao atingir o limite, move para a Dead Letter Queue — uma mensagem envenenada
        nao pode bloquear a fila indefinidamente.
        """

    @abstractmethod
    def dead_letter(self, receipt: str, *, error: str) -> bool:
        """Move a mensagem direto para a DLQ, sem gastar tentativas.

        Para falhas que retentativa nao resolve — registro inexistente, mensagem
        malformada. Retentar nesses casos so adia o inevitavel consumindo recurso.
        """

    @abstractmethod
    def stats(self) -> QueueStats:
        """Profundidade atual da fila."""

    @abstractmethod
    def redrive(self, *, limit: int) -> int:
        """Devolve mensagens da DLQ para a fila. Util apos corrigir a causa da falha."""


class NullQueueClient(QueueClient):
    """Implementacao nula: nenhuma fila configurada.

    Publicar seria mentir sobre uma capacidade inexistente e consumiria tentativas de
    retry sem motivo. Consumir simplesmente nao devolve nada.
    """

    @property
    def is_enabled(self) -> bool:
        return False

    def publish(self, message: QueueMessage) -> bool:
        raise NotImplementedError("Nenhuma fila configurada (NEXUS_QUEUE_BACKEND=none).")

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
        return QueueStats()

    def redrive(self, *, limit: int) -> int:
        return 0
