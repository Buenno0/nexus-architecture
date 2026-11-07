"""Contratos de entrada e saida da API.

Validacao acontece na borda. Payload invalido resulta em ``422`` e **nunca** alcanca a
persistencia ou a fila — essa e a garantia que mantem o restante do sistema livre de
verificacoes defensivas espalhadas.

``extra="forbid"`` e deliberado: um campo nao reconhecido indica que o cliente acredita
estar enviando algo que o sistema ignoraria em silencio. Melhor recusar do que descartar.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

#: Limite de tamanho por campo de texto. Protege contra payloads abusivos.
MAX_FIELD_LENGTH = 512

Source = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
        description="Identificador da fonte de dados. Escopo das chaves de idempotencia.",
    ),
]
ShortText = Annotated[str, Field(min_length=1, max_length=MAX_FIELD_LENGTH)]
OptionalText = Annotated[str | None, Field(default=None, max_length=MAX_FIELD_LENGTH)]


class _BaseRecordIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)

    source: Source

    @field_validator("*", mode="before")
    @classmethod
    def _reject_control_characters(cls, value: object) -> object:
        """Recusa caracteres de controle em qualquer campo de texto.

        Bytes nulos e caracteres de controle nao aparecem em dados legitimos e podem
        corromper logs estruturados e delimitadores internos de chave.
        """
        if isinstance(value, str) and any(ord(ch) < 32 and ch not in "\t" for ch in value):
            raise ValueError("caractere de controle nao permitido")
        return value


class PersonIn(_BaseRecordIn):
    """Registro sintetico de pessoa."""

    full_name: ShortText
    email: EmailStr | None = None
    document: OptionalText = None
    phone: OptionalText = None
    birth_date: date | None = None


class OrganizationIn(_BaseRecordIn):
    """Registro sintetico de organizacao."""

    legal_name: ShortText
    trade_name: OptionalText = None
    email: EmailStr | None = None
    document: OptionalText = None
    phone: OptionalText = None
    country: OptionalText = None


class RecordOut(BaseModel):
    """Resposta de ingestao.

    ``natural_key`` nao e exposta: e detalhe interno de modelagem e expo-la criaria
    acoplamento com clientes.
    """

    record_id: str
    record_type: Literal["person", "organization"]
    status: Literal["accepted", "duplicate"]
    record_fingerprint: str
    correlation_id: str
    seen_count: int = 1


class RecordDetail(BaseModel):
    """Representacao completa de uma observacao armazenada."""

    record_id: str
    record_type: Literal["person", "organization"]
    source: str
    record_fingerprint: str
    payload: dict[str, object]
    normalized: dict[str, object]
    correlation_id: str
    created_at: str
    seen_count: int
    #: Entidade a que a observacao pertence, quando a resolucao ja a vinculou.
    entity_id: str | None = None


class RecordPage(BaseModel):
    """Pagina de observacoes."""

    items: list[RecordDetail]
    next_cursor: str | None = None


class HealthOut(BaseModel):
    status: Literal["ok", "degraded"]
    environment: str
    version: str
    persistence: Literal["ok", "unavailable"]
    queue: Literal["enabled", "not_implemented"]


class ErrorOut(BaseModel):
    code: str
    message: str
    correlation_id: str
    details: dict[str, object] | None = None


# --------------------------------------------------------------------------- ops


class DispatchRequest(BaseModel):
    """Pedido de publicacao de eventos pendentes do outbox."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=100, ge=1, le=1_000)


class DispatchOut(BaseModel):
    scanned: int
    dispatched: int
    duplicates: int
    rescheduled: int
    missing: int


class ProcessRequest(BaseModel):
    """Pedido de consumo de um lote da fila."""

    model_config = ConfigDict(extra="forbid")

    max_messages: int = Field(default=10, ge=1, le=100)


class ProcessOut(BaseModel):
    received: int
    processed: int
    skipped_duplicate: int
    retried: int
    dead_lettered: int
    duration_ms: float


class QueueStatsOut(BaseModel):
    """Profundidade da fila.

    Vem do armazenamento, ao contrario dos contadores de ``/metrics``: sobrevive a
    reinicio e e consistente entre processos.
    """

    backend: str
    enabled: bool
    pending: int
    in_flight: int
    dead: int
    outbox_pending: int


class RedriveRequest(BaseModel):
    """Pedido de devolucao de mensagens da DLQ."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=100, ge=1, le=1_000)


class RedriveOut(BaseModel):
    redriven: int


# -------------------------------------------------------------------- resolution


class EntityMemberOut(BaseModel):
    """Vinculo de uma observacao a uma entidade, com a evidencia que o justifica."""

    record_id: str
    joined_at: str
    score: float
    matched_record_id: str | None = None
    evidence: dict[str, object] = Field(default_factory=dict)


class MergeEventOut(BaseModel):
    """Fusao que ajudou a formar a entidade."""

    event_id: str
    source_entity_id: str
    record_a: str
    record_b: str
    score: float
    moved_members: int
    created_at: str


class EntityOut(BaseModel):
    """Entidade canonica com seus vinculos e historico de fusoes."""

    entity_id: str
    record_type: Literal["person", "organization"]
    member_count: int
    version: int
    created_at: str
    updated_at: str
    flagged: bool
    flag_reason: str | None = None
    members: list[EntityMemberOut] = Field(default_factory=list)
    merges: list[MergeEventOut] = Field(default_factory=list)


class ReviewOut(BaseModel):
    """Par aguardando decisao humana."""

    pair_id: str
    record_a: str
    record_b: str
    record_type: Literal["person", "organization"]
    score: float
    status: Literal["pending", "confirmed", "rejected"]
    created_at: str
    decided_at: str | None = None
    reason: str | None = None
    evidence: dict[str, object] = Field(default_factory=dict)


class ReviewPage(BaseModel):
    items: list[ReviewOut]


class ReviewDecisionRequest(BaseModel):
    """Decisao sobre um par em duvida.

    ``confirm`` funde os clusters; ``reject`` registra a recusa e impede que o mesmo
    par volte a fila em reprocessamentos futuros.
    """

    model_config = ConfigDict(extra="forbid")

    decision: Literal["confirm", "reject"]
    reason: Annotated[str | None, Field(default=None, max_length=512)] = None


class ResolutionStatsOut(BaseModel):
    """Contadores duraveis de resolucao, lidos do armazenamento."""

    processor_version: str
    pending_reviews: int
    counters: dict[str, int] = Field(default_factory=dict)


class ReprocessRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=1_000, ge=1, le=10_000)


class ReprocessOut(BaseModel):
    version: str
    scanned: int
    enqueued: int
    already_processed: int
