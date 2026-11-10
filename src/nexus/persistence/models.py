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


class TrailStage(StrEnum):
    """Marcos que mudam o estado de uma observacao — ADR-010.

    Apenas marcos, nao todo evento. Retentativa e conflito de idempotencia aparecem
    nos logs; aqui ficam os pontos em que o registro de fato avancou (ou parou).
    """

    ACCEPTED = "accepted"
    PUBLISHED = "published"
    CONSUMED = "consumed"
    RESOLVED = "resolved"
    FAILED = "failed"
    DEAD_LETTERED = "dead_lettered"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


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
    processor_version: str = "pipeline-v1"
    status: ProcessingStatus = ProcessingStatus.SUCCEEDED

    #: Tempo entre a aceitacao da observacao e o fim do processamento.
    #:
    #: ``duration_ms`` mede so o processamento. A diferenca entre os dois e o tempo que
    #: a mensagem passou parada na fila — e e ela que separa "o processamento esta
    #: lento" de "a fila esta acumulando". Sao diagnosticos opostos, com correcoes
    #: opostas, e ate aqui nenhum numero os distinguia.
    #:
    #: ``None`` quando a observacao nao traz ``created_at`` utilizavel.
    end_to_end_ms: float | None = None


# --------------------------------------------------------------- Entity Resolution


@dataclass(frozen=True, slots=True)
class Entity:
    """Entidade canonica: um conjunto de observacoes julgadas a mesma do mundo real.

    ``version`` suporta concorrencia otimista. Dois workers podem resolver registros
    diferentes que apontam para a mesma entidade ao mesmo tempo; a escrita condicional
    sobre a versao garante que uma perca e tente de novo, em vez de as duas gravarem
    por cima uma da outra.

    ``flagged`` marca entidades que precisam de olho humano — tipicamente por terem
    atingido o teto de tamanho, sinal de fusao em cadeia.
    """

    entity_id: str
    record_type: RecordType
    member_count: int
    version: int
    created_at: datetime
    updated_at: datetime
    flagged: bool = False
    flag_reason: str | None = None


@dataclass(frozen=True, slots=True)
class EntityMember:
    """Vinculo entre uma observacao e uma entidade.

    ``matched_record_id`` e ``evidence`` guardam **por que** o vinculo existe: qual par
    o causou e o score campo a campo. Sem isso, desfazer uma fusao especifica seria
    adivinhacao.
    """

    entity_id: str
    record_id: str
    joined_at: datetime
    score: float
    matched_record_id: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MergeEvent:
    """Registro de uma fusao de entidades.

    Guarda a entidade de origem e o par que a provocou, tornando o fecho transitivo
    auditavel: e possivel reconstruir a cadeia que levou dois registros ao mesmo cluster.
    """

    entity_id: str
    event_id: str
    source_entity_id: str
    record_a: str
    record_b: str
    score: float
    moved_members: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ReviewItem:
    """Par em duvida, aguardando decisao.

    ``POSSIBLE_MATCH`` nunca funde sozinho — vem para ca. ``review_shard`` existe
    somente enquanto pendente, mantendo o indice proporcional a fila, nao a tabela.
    """

    pair_id: str
    record_a: str
    record_b: str
    record_type: RecordType
    score: float
    evidence: dict[str, Any]
    created_at: datetime
    status: ReviewStatus = ReviewStatus.PENDING
    review_shard: str | None = None
    decided_at: datetime | None = None
    reason: str | None = None


# ------------------------------------------------------------------ Observability


@dataclass(frozen=True, slots=True)
class TrailEvent:
    """Um marco na jornada de uma observacao — ADR-010.

    Chaveado por ``record_id``, nao por ``correlation_id``: a pergunta de uma
    investigacao e "o que aconteceu com este registro", e um registro reprocessado tem
    um ``correlation_id`` por passagem. O ``correlation_id`` vai como atributo, para
    cruzar com os logs.

    Escrito em best-effort: falhar aqui nao pode derrubar a operacao descrita.
    """

    record_id: str
    stage: TrailStage
    occurred_at: datetime
    correlation_id: str
    #: Processo que emitiu o marco: api, dispatcher ou worker.
    service: str
    detail: dict[str, Any] = field(default_factory=dict)
    event_id: str = ""


@dataclass(frozen=True, slots=True)
class MetricSample:
    """Uma amostra de metricas num balde de tempo — ADR-010.

    O carimbo e arredondado ao intervalo de amostragem. E isso que permite escrita
    condicional: dois observadores no mesmo intervalo tentam gravar a mesma chave, e
    so o primeiro vence.
    """

    metric: str
    bucket: datetime
    values: dict[str, float]
    expires_at: int
