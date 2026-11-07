"""Interface de persistencia.

A logica de negocio depende desta abstracao, nunca de DynamoDB diretamente. E o que
permite trocar o mecanismo de armazenamento sem tocar na ingestao — e o que torna a
migracao para a AWS uma troca de configuracao, nao uma reescrita.

A abstracao e deliberadamente fina: expoe as operacoes que a Fase 1 precisa, nao um
ORM generico. Abstracao alem da necessidade e custo sem beneficio.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from nexus.persistence.models import (
    IdempotencyRecord,
    OutboxEvent,
    Page,
    ProcessingResult,
    RecordType,
    StoredRecord,
)


class CommitConflictError(Exception):
    """Uma condicao de escrita falhou: outra requisicao concorrente venceu a corrida.

    Nao e erro do cliente. O chamador deve reler o estado e responder com o resultado
    ja estabelecido.
    """


class RecordRepository(ABC):
    """Operacoes de persistencia exigidas pela Fase 1."""

    @abstractmethod
    def ensure_ready(self) -> None:
        """Garante que o armazenamento esta acessivel e provisionado."""

    @abstractmethod
    def ping(self) -> bool:
        """Verificacao barata de disponibilidade, para o endpoint de saude.

        Nao deve varrer dados nem criar recursos: um health check caro vira,
        ele proprio, uma fonte de carga.
        """

    # ---------------------------------------------------------------- idempotencia

    @abstractmethod
    def find_idempotency(self, source: str, idempotency_key: str) -> IdempotencyRecord | None:
        """Recupera o resultado de uma operacao de ingestao anterior — ADR-002."""

    # ------------------------------------------------------------------ observacoes

    @abstractmethod
    def find_by_fingerprint(self, natural_key: str, fingerprint: str) -> StoredRecord | None:
        """Localiza observacao com conteudo byte-identico.

        Leitura em indice secundario global, portanto **eventualmente consistente**:
        duas requisicoes concorrentes com o mesmo conteudo e chaves de idempotencia
        diferentes podem ambas criar observacoes. Isso e aceito por design — a
        deduplicacao autoritativa de conteudo e responsabilidade do Entity Resolution,
        nao da ingestao (ADR-002).
        """

    @abstractmethod
    def get_record(self, record_id: str) -> StoredRecord | None:
        """Obtem uma observacao por identificador."""

    @abstractmethod
    def list_records(
        self,
        record_type: RecordType,
        *,
        limit: int,
        cursor: str | None = None,
    ) -> Page:
        """Lista observacoes do tipo, mais recentes primeiro."""

    # --------------------------------------------------------------------- escrita

    @abstractmethod
    def commit_ingestion(
        self,
        record: StoredRecord,
        event: OutboxEvent,
        idempotency: IdempotencyRecord,
    ) -> None:
        """Grava observacao, evento de outbox e idempotencia **atomicamente**.

        As tres escritas sao indivisiveis. Grava-las separadamente reabriria o problema
        de dual-write que o ADR-003 existe para fechar.

        :raises CommitConflictError: outra requisicao gravou a mesma chave primeiro.
        """

    @abstractmethod
    def register_duplicate(self, record_id: str, idempotency: IdempotencyRecord) -> None:
        """Registra reenvio de conteudo ja observado.

        Incrementa ``seen_count`` da observacao existente e grava a idempotencia na
        mesma transacao. Nenhuma observacao nova e criada e nada e enfileirado.

        :raises CommitConflictError: outra requisicao gravou a mesma chave primeiro.
        """

    # ----------------------------------------------------------------- consumo

    @abstractmethod
    def commit_processing(self, result: ProcessingResult) -> None:
        """Grava o resultado do processamento, que **e** o marcador — ADR-005.

        Escrita condicional: falha se a observacao ja foi processada. E dessa condicao,
        nao de uma verificacao previa, que vem a garantia de efeito unico sob reentrega.

        :raises CommitConflictError: a observacao ja havia sido processada.
        """

    @abstractmethod
    def find_processing_result(self, record_id: str) -> ProcessingResult | None:
        """Consulta o marcador de processamento.

        Serve para evitar trabalho desnecessario antes de processar. **Nao e a
        garantia** — entre a consulta e a escrita existe janela de corrida, fechada
        pela condicao em ``commit_processing``.
        """

    # ---------------------------------------------------------------------- outbox

    @abstractmethod
    def get_outbox_event(self, event_id: str) -> OutboxEvent | None:
        """Obtem um evento de outbox por identificador."""

    @abstractmethod
    def mark_outbox_dispatched(self, event_id: str) -> None:
        """Marca o evento como despachado e o remove do indice esparso — ADR-003."""

    @abstractmethod
    def reschedule_outbox(self, event_id: str, *, error: str, now: datetime) -> OutboxEvent:
        """Registra falha de publicacao e reagenda com backoff exponencial.

        Ao atingir ``outbox_max_attempts``, marca ``failed`` e remove do indice esparso
        para nao bloquear os demais eventos.
        """

    @abstractmethod
    def list_pending_outbox(self, shard: str, *, limit: int, now: datetime) -> list[str]:
        """Devolve identificadores de eventos pendentes e vencidos do shard."""

    @abstractmethod
    def count_pending_outbox(self) -> int:
        """Total de eventos pendentes em todos os shards. Metrica de backlog."""
