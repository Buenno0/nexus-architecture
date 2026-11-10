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
    Entity,
    EntityMember,
    IdempotencyRecord,
    MergeEvent,
    MetricSample,
    OutboxEvent,
    Page,
    ProcessingResult,
    RecordType,
    ReviewItem,
    ReviewStatus,
    StoredRecord,
    TrailEvent,
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
    def find_processing_result(self, record_id: str, version: str) -> ProcessingResult | None:
        """Consulta o marcador de processamento da versao informada.

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

    # ------------------------------------------------------- entity resolution

    @abstractmethod
    def put_blocking_keys(self, record_id: str, record_type: RecordType, keys: list[str]) -> None:
        """Indexa a observacao sob suas chaves de bloco.

        Gravadas **depois** da comparacao, para que o registro corrente nao apareca
        entre os proprios candidatos.
        """

    @abstractmethod
    def find_block_candidates(
        self, keys: list[str], *, limit: int, exclude: str | None = None
    ) -> tuple[list[str], bool]:
        """Devolve ``(record_ids, truncado)`` para as chaves informadas.

        O teto existe porque uma chave muito comum transformaria a comparacao em O(n).
        A flag de truncagem e devolvida em vez de truncar em silencio: cortar candidatos
        sem avisar esconderia falso negativo.
        """

    @abstractmethod
    def get_entity(self, entity_id: str) -> Entity | None:
        """Obtem a entidade canonica."""

    @abstractmethod
    def find_entity_id_for_record(self, record_id: str) -> str | None:
        """Descobre a que entidade uma observacao pertence."""

    @abstractmethod
    def list_entity_members(self, entity_id: str) -> list[EntityMember]:
        """Lista os vinculos da entidade, com evidencia de cada um."""

    @abstractmethod
    def list_merge_events(self, entity_id: str) -> list[MergeEvent]:
        """Historico de fusoes que formaram a entidade."""

    @abstractmethod
    def create_entity(self, entity: Entity, members: list[EntityMember]) -> None:
        """Cria a entidade e seus vinculos iniciais, atomicamente.

        :raises CommitConflictError: a entidade ja existe.
        """

    @abstractmethod
    def add_member(self, entity: Entity, member: EntityMember) -> Entity:
        """Adiciona um vinculo, com escrita condicional sobre a versao da entidade.

        :raises CommitConflictError: a entidade mudou desde a leitura.
        """

    @abstractmethod
    def merge_entities(
        self, target: Entity, source: Entity, members: list[EntityMember], event: MergeEvent
    ) -> Entity:
        """Move os vinculos da origem para o destino e registra o evento, atomicamente.

        :raises CommitConflictError: alguma das entidades mudou desde a leitura.
        """

    @abstractmethod
    def flag_entity(self, entity_id: str, reason: str) -> None:
        """Marca a entidade para revisao humana, sem alterar seus vinculos."""

    @abstractmethod
    def put_review(self, item: ReviewItem) -> bool:
        """Registra um par para revisao. ``False`` se o par ja era conhecido.

        Impede que cada reprocessamento ressuscite uma decisao ja tomada.
        """

    @abstractmethod
    def get_review(self, pair_id: str) -> ReviewItem | None:
        """Obtem um par de revisao."""

    @abstractmethod
    def list_pending_reviews(self, *, limit: int) -> list[ReviewItem]:
        """Lista pares aguardando decisao, pelo indice esparso."""

    @abstractmethod
    def decide_review(self, pair_id: str, status: ReviewStatus, reason: str | None) -> ReviewItem:
        """Registra a decisao e remove o par do indice de pendentes."""

    @abstractmethod
    def increment_resolution_stats(self, **counters: int) -> None:
        """Soma contadores duraveis de resolucao.

        Contadores em memoria zeram no reinicio; estes sobrevivem e sao consistentes
        entre processos.
        """

    @abstractmethod
    def get_resolution_stats(self) -> dict[str, int]:
        """Le os contadores duraveis de resolucao."""

    # ------------------------------------------------------------ observabilidade

    @abstractmethod
    def record_trail(self, event: TrailEvent) -> bool:
        """Grava um marco da jornada. **Best-effort** — ADR-010.

        Devolve ``False`` quando a gravacao falha, e **nunca levanta**. Observabilidade
        que derruba a operacao observada e pior que observabilidade nenhuma: trocaria
        uma linha a menos numa investigacao por um registro perdido.
        """

    @abstractmethod
    def get_trail(self, record_id: str) -> list[TrailEvent]:
        """Jornada completa da observacao, em ordem cronologica.

        A ordem vem da chave de ordenacao, nao de ordenacao em memoria.
        """

    @abstractmethod
    def put_metric_sample(self, sample: MetricSample) -> bool:
        """Grava uma amostra no balde. ``False`` se o balde ja estava ocupado.

        Escrita condicional: dois observadores no mesmo intervalo gravam a mesma
        chave, e so o primeiro vence. Sem isso, a densidade da serie acompanharia o
        numero de observadores em vez do tempo.
        """

    @abstractmethod
    def get_metric_series(self, metric: str, *, since: datetime) -> list[MetricSample]:
        """Amostras da metrica a partir do instante informado."""

    @abstractmethod
    def oldest_pending_outbox_at(self) -> datetime | None:
        """Instante do evento de outbox pendente mais antigo, se houver.

        Backlog parado e diferente de backlog grande: o que importa e ha quanto tempo
        o evento mais antigo espera.
        """
