"""API HTTP do Nexus Ingestion.

Esta camada e fina por desenho: traduz HTTP para o servico e de volta. Toda regra vive
em ``service.py``, o que permite testar o caminho de ingestao sem subir um servidor.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, Path, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from nexus import __version__
from nexus.ingestion.schemas import (
    AlertOut,
    AlertsOut,
    DispatchOut,
    DispatchRequest,
    EntityMemberOut,
    EntityOut,
    ErrorOut,
    HealthOut,
    MergeEventOut,
    OrganizationIn,
    PersonIn,
    ProcessOut,
    ProcessRequest,
    QueueStatsOut,
    RecordDetail,
    RecordOut,
    RecordPage,
    RedriveOut,
    RedriveRequest,
    ReprocessOut,
    ReprocessRequest,
    ResolutionStatsOut,
    ReviewDecisionRequest,
    ReviewOut,
    ReviewPage,
    SampleOut,
    SeriesOut,
    SeriesPointOut,
    TrailEventOut,
    TrailOut,
)
from nexus.ingestion.service import IngestionResult, IngestionService
from nexus.observability.alerts import AlertEvaluator
from nexus.observability.metrics import registry
from nexus.observability.middleware import ObservabilityMiddleware
from nexus.observability.series import PLATFORM_SERIES, MetricSampler
from nexus.persistence import get_repository
from nexus.persistence.models import (
    Entity,
    EntityMember,
    MergeEvent,
    RecordType,
    ReviewItem,
    ReviewStatus,
    StoredRecord,
)
from nexus.persistence.repository import RecordRepository
from nexus.queue import get_queue_client
from nexus.queue.client import QueueClient
from nexus.queue.dispatcher import OutboxDispatcher
from nexus.queue.processor import build_processor
from nexus.queue.reprocess import Reprocessor
from nexus.queue.worker import Worker
from nexus.resolution.clustering import ClusterManager
from nexus.shared.clock import utcnow
from nexus.shared.config import Settings, get_settings
from nexus.shared.errors import MissingIdempotencyKeyError, NexusError, RecordNotFoundError
from nexus.shared.logging import configure_logging, get_correlation_id, get_logger

logger = get_logger(__name__)

MAX_IDEMPOTENCY_KEY_LENGTH = 128


# ---------------------------------------------------------------------- dependencias


# Injetadas por ``Depends`` em vez de chamadas diretamente nas rotas: e o que permite
# substituir persistencia e fila em teste sem tocar no codigo de producao.
RepositoryDep = Annotated[RecordRepository, Depends(get_repository)]
QueueDep = Annotated[QueueClient, Depends(get_queue_client)]
# A configuracao tambem e injetada: servico e repositorio PRECISAM enxergar o mesmo
# ``outbox_shards``, senao o dispatcher varre shards diferentes dos que a ingestao
# escreve e eventos pendentes ficam orfaos. Ver ADR-003.
SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_service(
    repository: RepositoryDep, queue: QueueDep, settings: SettingsDep
) -> IngestionService:
    return IngestionService(repository, queue, settings)


def require_idempotency_key(
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            description="Identificador da operacao de ingestao, definido pelo cliente.",
        ),
    ] = None,
) -> str:
    """Exige e valida o header ``Idempotency-Key`` — ADR-002.

    Obrigatorio por decisao explicita: a fonte e quem sabe se duas requisicoes sao a
    mesma operacao ou duas operacoes distintas. O servidor nao tem essa informacao.
    """
    key = (idempotency_key or "").strip()
    if not key:
        raise MissingIdempotencyKeyError(
            "Header 'Idempotency-Key' e obrigatorio nas operacoes de ingestao"
        )
    if len(key) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise MissingIdempotencyKeyError(
            f"Header 'Idempotency-Key' excede {MAX_IDEMPOTENCY_KEY_LENGTH} caracteres"
        )
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in key):
        raise MissingIdempotencyKeyError(
            "Header 'Idempotency-Key' contem caracteres nao imprimiveis"
        )
    return key


ServiceDep = Annotated[IngestionService, Depends(get_service)]
IdempotencyKeyDep = Annotated[str, Depends(require_idempotency_key)]


# ---------------------------------------------------------------------- ciclo de vida


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, settings.service_name)
    logger.info(
        "service_starting",
        extra={"environment": settings.env, "version": __version__, "table": settings.dynamo_table},
    )
    yield
    logger.info("service_stopping")


app = FastAPI(
    title="Nexus Ingestion",
    description=(
        "Entrada de dados do Nexus Architecture. Todos os dados sao sinteticos.\n\n"
        "O header `Idempotency-Key` e obrigatorio nas operacoes de ingestao."
    ),
    version=__version__,
    lifespan=lifespan,
)
app.add_middleware(ObservabilityMiddleware)

# O Control Center roda em outra origem (porta 5173 em desenvolvimento, dominio proprio
# em producao), entao o navegador exige CORS. A lista de origens e explicita e o "*" e
# recusado na configuracao: as rotas de /v1/ops disparam trabalho, e um curinga aqui
# permitiria que qualquer pagina as chamasse pelo navegador de quem a visitasse.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().cors_allowed_origins),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["content-type", "authorization", "idempotency-key", "x-correlation-id"],
    # A interface le os dois: o primeiro para rastrear, o segundo para distinguir
    # replay de ingestao nova.
    expose_headers=["x-correlation-id", "idempotency-replayed"],
    allow_credentials=False,
    max_age=300,
)


# -------------------------------------------------------------------- tratamento de erro


@app.exception_handler(NexusError)
async def handle_nexus_error(request: Request, exc: NexusError) -> JSONResponse:
    """Erros de dominio viram respostas previsiveis, sem detalhe interno."""
    payload = ErrorOut(
        code=exc.code,
        message=exc.message,
        correlation_id=get_correlation_id() or "",
        details=exc.details or None,
    )
    return JSONResponse(status_code=exc.status_code, content=payload.model_dump(exclude_none=True))


@app.exception_handler(RequestValidationError)
async def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Erro de validacao: 422 com o campo ofensor, nunca 500."""
    fields = [
        {
            "field": ".".join(str(part) for part in error.get("loc", ()) if part != "body"),
            "message": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in exc.errors()
    ]
    payload = ErrorOut(
        code="validation_error",
        message="Payload invalido",
        correlation_id=get_correlation_id() or "",
        details={"fields": fields},
    )
    return JSONResponse(status_code=422, content=payload.model_dump(exclude_none=True))


@app.exception_handler(Exception)
async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
    """Falha inesperada: o detalhe vai para o log, nunca para a resposta.

    Stack traces e nomes de tabela em respostas HTTP sao vazamento de informacao.
    O cliente recebe o ``correlation_id``, que permite rastrear o caso sem expor nada.
    """
    correlation_id = get_correlation_id() or ""
    logger.exception("unhandled_error", extra={"path": request.url.path})
    payload = ErrorOut(
        code="internal_error",
        message="Erro interno",
        correlation_id=correlation_id,
    )
    return JSONResponse(status_code=500, content=payload.model_dump(exclude_none=True))


# ------------------------------------------------------------------------- utilitarios


def _to_detail(record: StoredRecord, entity_id: str | None = None) -> RecordDetail:
    return RecordDetail(
        record_id=record.record_id,
        record_type=record.record_type.value,
        source=record.source,
        record_fingerprint=record.record_fingerprint,
        payload=dict(record.payload),
        normalized=dict(record.normalized),
        correlation_id=record.correlation_id,
        created_at=record.created_at.isoformat(),
        seen_count=record.seen_count,
        entity_id=entity_id,
    )


def _response(result: IngestionResult) -> JSONResponse:
    headers = {"Idempotency-Replayed": "true"} if result.replayed else None
    return JSONResponse(status_code=result.status_code, content=result.body, headers=headers)


# ------------------------------------------------------------------------------ rotas


@app.post(
    "/v1/records/person",
    response_model=RecordOut,
    status_code=202,
    summary="Ingestao de registro de pessoa",
    responses={
        200: {"model": RecordOut, "description": "Replay ou conteudo ja observado"},
        400: {"model": ErrorOut, "description": "Header Idempotency-Key ausente ou invalido"},
        409: {"model": ErrorOut, "description": "Chave de idempotencia reusada com outro corpo"},
        422: {"model": ErrorOut, "description": "Payload invalido"},
    },
    tags=["ingestion"],
)
async def ingest_person(
    payload: PersonIn,
    request: Request,
    service: ServiceDep,
    idempotency_key: IdempotencyKeyDep,
) -> JSONResponse:
    return await _ingest(RecordType.PERSON, payload, request, service, idempotency_key)


@app.post(
    "/v1/records/organization",
    response_model=RecordOut,
    status_code=202,
    summary="Ingestao de registro de organizacao",
    responses={
        200: {"model": RecordOut, "description": "Replay ou conteudo ja observado"},
        400: {"model": ErrorOut, "description": "Header Idempotency-Key ausente ou invalido"},
        409: {"model": ErrorOut, "description": "Chave de idempotencia reusada com outro corpo"},
        422: {"model": ErrorOut, "description": "Payload invalido"},
    },
    tags=["ingestion"],
)
async def ingest_organization(
    payload: OrganizationIn,
    request: Request,
    service: ServiceDep,
    idempotency_key: IdempotencyKeyDep,
) -> JSONResponse:
    return await _ingest(RecordType.ORGANIZATION, payload, request, service, idempotency_key)


async def _ingest(
    record_type: RecordType,
    payload: PersonIn | OrganizationIn,
    request: Request,
    service: IngestionService,
    idempotency_key: str,
) -> JSONResponse:
    # O corpo bruto distingue replay legitimo de reuso indevido da chave (ADR-002).
    # Starlette ja o leu para validar o modelo; esta chamada devolve o valor em cache.
    raw_body = await request.body()
    correlation_id = getattr(request.state, "correlation_id", "")

    # boto3 e sincrono. Executar no threadpool evita bloquear o event loop — sem isso,
    # uma unica requisicao lenta travaria todas as demais sob carga.
    result = await run_in_threadpool(
        service.ingest,
        record_type,
        payload.model_dump(mode="json", exclude_none=True),
        raw_body=raw_body,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )
    return _response(result)


@app.get(
    "/v1/records/{record_id}",
    response_model=RecordDetail,
    summary="Consulta de observacao",
    responses={404: {"model": ErrorOut, "description": "Registro inexistente"}},
    tags=["records"],
)
async def get_record(
    record_id: Annotated[str, Path(min_length=1, max_length=64)],
    repository: RepositoryDep = None,  # type: ignore[assignment]
) -> RecordDetail:
    record = await run_in_threadpool(repository.get_record, record_id)
    if record is None:
        raise RecordNotFoundError("Registro nao encontrado", details={"record_id": record_id})
    # Observacao e vinculo compartilham particao: descobrir a entidade custa uma
    # consulta barata na mesma chave. Ver docs/architecture/access-patterns.md.
    entity_id = await run_in_threadpool(repository.find_entity_id_for_record, record_id)
    return _to_detail(record, entity_id)


@app.get(
    "/v1/records",
    response_model=RecordPage,
    summary="Listagem paginada de observacoes",
    tags=["records"],
)
async def list_records(
    repository: RepositoryDep,
    settings: SettingsDep,
    record_type: Annotated[RecordType, Query(description="Tipo de registro")] = RecordType.PERSON,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
) -> RecordPage:
    page = await run_in_threadpool(
        repository.list_records,
        record_type,
        limit=min(limit, settings.max_page_size),
        cursor=cursor,
    )
    return RecordPage(
        items=[_to_detail(record) for record in page.items],
        next_cursor=page.next_cursor,
    )


@app.get("/health", response_model=HealthOut, summary="Verificacao de saude", tags=["ops"])
async def health(repository: RepositoryDep, queue: QueueDep, settings: SettingsDep) -> HealthOut:
    persistence_ok = await run_in_threadpool(repository.ping)
    return HealthOut(
        status="ok" if persistence_ok else "degraded",
        environment=settings.env,
        version=__version__,
        persistence="ok" if persistence_ok else "unavailable",
        queue="enabled" if queue.is_enabled else "not_implemented",
        trail_enabled=settings.trail_enabled,
    )


@app.get("/metrics", summary="Metricas operacionais", tags=["ops"])
async def metrics(
    repository: RepositoryDep, queue: QueueDep, settings: SettingsDep
) -> dict[str, Any]:
    """Metricas do processo.

    ``scope: in_process`` nao e decorativo: estes numeros zeram a cada reinicio e nao
    sao agregados entre replicas. Apresenta-los como metricas de plataforma seria falso.
    """
    snapshot = registry.snapshot()
    try:
        backlog: int | None = await run_in_threadpool(repository.count_pending_outbox)
    except Exception:
        logger.warning("backlog_unavailable")
        backlog = None

    try:
        stats = await run_in_threadpool(queue.stats)
        queue_depth: dict[str, int] | None = {
            "pending": stats.pending,
            "in_flight": stats.in_flight,
            "dead": stats.dead,
        }
    except Exception:
        logger.warning("queue_stats_unavailable")
        queue_depth = None

    # Amostragem oportunista — ADR-010. Reaproveita as duas leituras acima: a rota
    # mais chamada do painel paga, no maximo, uma escrita condicional por balde, e
    # nenhuma leitura extra. Falhar aqui nao pode falhar /metrics.
    sample_written = False
    try:
        valores: dict[str, float] = {}
        if backlog is not None:
            valores["outbox_pending"] = float(backlog)
        if queue_depth is not None:
            valores.update({f"queue_{k}": float(v) for k, v in queue_depth.items()})
        if valores:
            sampler = _get_sampler(repository, queue, settings)
            sample_written = (await run_in_threadpool(sampler.sample, values=valores)).written
    except Exception:
        logger.warning("sample_failed")

    return {
        "scope": "in_process",
        "environment": settings.env,
        "series_sampled": sample_written,
        "outbox_pending": backlog,
        # Profundidade da fila vem do armazenamento, nao de contadores em memoria:
        # sobrevive a reinicio e e consistente entre processos, ao contrario de
        # "counters" e "latency_ms" abaixo.
        "queue": queue_depth,
        # Derivado do que esta de fato configurado, nunca fixo no codigo.
        #
        # Este dicionario tinha "entity_resolution": "not_implemented" escrito a mao
        # desde a Fase 2. A Fase 5 implementou a resolucao e esqueceu de atualizar
        # aqui, entao a API passou a declarar uma capacidade que ela tinha — o
        # oposto do erro que a regra "nao anuncie o que nao existe" pretende evitar,
        # e igualmente enganoso.
        #
        # O defeito so apareceu quando o Control Center mostrou o campo numa tela.
        "modules": {
            "ingestion": "implemented",
            "queue_engine": "implemented" if queue.is_enabled else "disabled",
            "entity_resolution": (
                "implemented"
                if build_processor(settings, repository).version.startswith("resolution")
                else "not_implemented"
            ),
            "observability": "implemented",
        },
        **snapshot,
    }


# ----------------------------------------------------------------------------- ops
#
# Endpoints operacionais. Todo o modelo de custo depende de execucao sob demanda: nada
# processa sozinho, alguem precisa pedir. Sao estas rotas que o Control Center da
# Fase 4 chama.
#
# ATENCAO: nao ha autenticacao. A API so e exposta no ambiente local — ver SECURITY.md.
# Autenticacao e requisito da Fase 3, antes de qualquer exposicao publica.


@app.post(
    "/v1/ops/dispatch",
    response_model=DispatchOut,
    summary="Publica eventos pendentes do outbox na fila",
    tags=["ops"],
)
async def ops_dispatch(
    repository: RepositoryDep,
    queue: QueueDep,
    settings: SettingsDep,
    body: DispatchRequest | None = None,
) -> DispatchOut:
    request_body = body or DispatchRequest()
    dispatcher = OutboxDispatcher(repository, queue, settings)
    report = await run_in_threadpool(dispatcher.dispatch_once, limit=request_body.limit)
    return DispatchOut(
        scanned=report.scanned,
        dispatched=report.dispatched,
        duplicates=report.duplicates,
        rescheduled=report.rescheduled,
        missing=report.missing,
    )


@app.post(
    "/v1/ops/process",
    response_model=ProcessOut,
    summary="Consome um lote da fila",
    tags=["ops"],
)
async def ops_process(
    repository: RepositoryDep,
    queue: QueueDep,
    settings: SettingsDep,
    body: ProcessRequest | None = None,
) -> ProcessOut:
    request_body = body or ProcessRequest()
    worker = Worker(repository, queue, settings=settings)
    report = await run_in_threadpool(worker.process_once, max_messages=request_body.max_messages)
    return ProcessOut(
        received=report.received,
        processed=report.processed,
        skipped_duplicate=report.skipped_duplicate,
        retried=report.retried,
        dead_lettered=report.dead_lettered,
        duration_ms=round(report.duration_ms, 3),
    )


@app.get(
    "/v1/ops/queue",
    response_model=QueueStatsOut,
    summary="Profundidade da fila e do outbox",
    tags=["ops"],
)
async def ops_queue(
    repository: RepositoryDep, queue: QueueDep, settings: SettingsDep
) -> QueueStatsOut:
    stats = await run_in_threadpool(queue.stats)
    backlog = await run_in_threadpool(repository.count_pending_outbox)
    return QueueStatsOut(
        backend=settings.queue_backend,
        enabled=queue.is_enabled,
        pending=stats.pending,
        in_flight=stats.in_flight,
        dead=stats.dead,
        outbox_pending=backlog,
    )


@app.post(
    "/v1/ops/redrive",
    response_model=RedriveOut,
    summary="Devolve mensagens da DLQ para a fila",
    tags=["ops"],
)
async def ops_redrive(queue: QueueDep, body: RedriveRequest | None = None) -> RedriveOut:
    request_body = body or RedriveRequest()
    count = await run_in_threadpool(queue.redrive, limit=request_body.limit)
    return RedriveOut(redriven=count)


# ---------------------------------------------------------------------- resolution
#
# Entity Resolution expoe o que decidiu e **por que**. A evidencia campo a campo nao e
# detalhe de depuracao: e o que permite auditar uma fusao e ajustar pesos com dado em
# vez de palpite.


def _member_out(member: EntityMember) -> EntityMemberOut:
    return EntityMemberOut(
        record_id=member.record_id,
        joined_at=member.joined_at.isoformat(),
        score=member.score,
        matched_record_id=member.matched_record_id,
        evidence=dict(member.evidence),
    )


def _merge_out(event: MergeEvent) -> MergeEventOut:
    return MergeEventOut(
        event_id=event.event_id,
        source_entity_id=event.source_entity_id,
        record_a=event.record_a,
        record_b=event.record_b,
        score=event.score,
        moved_members=event.moved_members,
        created_at=event.created_at.isoformat(),
    )


def _entity_out(entity: Entity, members: list[EntityMember], merges: list[MergeEvent]) -> EntityOut:
    return EntityOut(
        entity_id=entity.entity_id,
        record_type=entity.record_type.value,
        member_count=entity.member_count,
        version=entity.version,
        created_at=entity.created_at.isoformat(),
        updated_at=entity.updated_at.isoformat(),
        flagged=entity.flagged,
        flag_reason=entity.flag_reason,
        members=[_member_out(member) for member in members],
        merges=[_merge_out(event) for event in merges],
    )


def _review_out(item: ReviewItem) -> ReviewOut:
    return ReviewOut(
        pair_id=item.pair_id,
        record_a=item.record_a,
        record_b=item.record_b,
        record_type=item.record_type.value,
        score=item.score,
        status=item.status.value,
        created_at=item.created_at.isoformat(),
        decided_at=item.decided_at.isoformat() if item.decided_at else None,
        reason=item.reason,
        evidence=dict(item.evidence),
    )


@app.get(
    "/v1/resolution/entities/{entity_id}",
    response_model=EntityOut,
    summary="Entidade canonica com vinculos e historico de fusoes",
    responses={404: {"model": ErrorOut, "description": "Entidade inexistente"}},
    tags=["resolution"],
)
async def get_entity(
    entity_id: Annotated[str, Path(min_length=1, max_length=64)],
    repository: RepositoryDep = None,  # type: ignore[assignment]
) -> EntityOut:
    entity = await run_in_threadpool(repository.get_entity, entity_id)
    if entity is None:
        raise RecordNotFoundError("Entidade nao encontrada", details={"entity_id": entity_id})
    members = await run_in_threadpool(repository.list_entity_members, entity_id)
    merges = await run_in_threadpool(repository.list_merge_events, entity_id)
    return _entity_out(entity, members, merges)


@app.get(
    "/v1/resolution/reviews",
    response_model=ReviewPage,
    summary="Pares aguardando decisao humana",
    tags=["resolution"],
)
async def list_reviews(
    repository: RepositoryDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
) -> ReviewPage:
    items = await run_in_threadpool(repository.list_pending_reviews, limit=limit)
    return ReviewPage(items=[_review_out(item) for item in items])


@app.post(
    "/v1/resolution/reviews/{pair_id}",
    response_model=ReviewOut,
    summary="Decide um par em duvida",
    responses={404: {"model": ErrorOut, "description": "Par inexistente"}},
    tags=["resolution"],
)
async def decide_review(
    pair_id: Annotated[str, Path(min_length=1, max_length=64)],
    body: ReviewDecisionRequest,
    repository: RepositoryDep,
    settings: SettingsDep,
) -> ReviewOut:
    """Confirma ou recusa uma correspondencia provavel.

    Confirmar funde os clusters, exatamente como uma correspondencia certa faria.
    Recusar registra a decisao — e, por ja existir o par, impede que reprocessamentos
    futuros o recriem.
    """
    item = await run_in_threadpool(repository.get_review, pair_id)
    if item is None:
        raise RecordNotFoundError("Par de revisao nao encontrado", details={"pair_id": pair_id})

    if body.decision == "confirm":
        manager = ClusterManager(repository, settings)
        await run_in_threadpool(
            manager.link,
            item.record_a,
            item.record_b,
            item.record_type,
            item.score,
            dict(item.evidence),
        )
        status = ReviewStatus.CONFIRMED
    else:
        status = ReviewStatus.REJECTED

    decided = await run_in_threadpool(repository.decide_review, pair_id, status, body.reason)
    logger.info(
        "review_decided",
        extra={"pair_id": pair_id, "decision": body.decision},
    )
    return _review_out(decided)


@app.get(
    "/v1/resolution/stats",
    response_model=ResolutionStatsOut,
    summary="Contadores de resolucao",
    tags=["resolution"],
)
async def resolution_stats(repository: RepositoryDep, settings: SettingsDep) -> ResolutionStatsOut:
    counters = await run_in_threadpool(repository.get_resolution_stats)
    pending = await run_in_threadpool(repository.list_pending_reviews, limit=100)
    processor = build_processor(settings, repository)
    return ResolutionStatsOut(
        processor_version=processor.version,
        pending_reviews=len(pending),
        counters=counters,
    )


@app.post(
    "/v1/ops/reprocess",
    response_model=ReprocessOut,
    summary="Reenfileira observacoes sem resultado na versao corrente",
    tags=["ops"],
)
async def ops_reprocess(
    repository: RepositoryDep,
    queue: QueueDep,
    settings: SettingsDep,
    body: ReprocessRequest | None = None,
) -> ReprocessOut:
    """Traz o acervo existente para a versao atual do processador — ADR-007.

    Registros ja consumidos nao tem mais mensagem na fila. Rodar duas vezes nao duplica
    trabalho: apenas o que falta na versao corrente e reenfileirado.
    """
    request_body = body or ReprocessRequest()
    processor = build_processor(settings, repository)
    reprocessor = Reprocessor(repository, queue, processor.version, settings)
    report = await run_in_threadpool(reprocessor.run, limit=request_body.limit)
    return ReprocessOut(
        version=processor.version,
        scanned=report.scanned,
        enqueued=report.enqueued,
        already_processed=report.already_processed,
    )


# ------------------------------------------------------------------ observability
#
# A trilha responde "o que aconteceu com este registro" atravessando os processos que
# o tocaram. Ate a Fase 5 essa pergunta nao tinha resposta: o `correlation_id` era
# propagado corretamente, mas a metade do worker so existia no terminal de quem rodou
# o comando, e na Lambda nem isso haveria.
#
# Nada aqui e autenticado no ambiente local — ver SECURITY.md.


# Um amostrador por processo: a memoria do ultimo balde so economiza leitura se
# sobreviver entre requisicoes. Reconstruido quando o repositorio muda, o que acontece
# nos testes que substituem a dependencia.
_sampler: MetricSampler | None = None
_sampler_repo: RecordRepository | None = None


def _get_sampler(
    repository: RecordRepository, queue: QueueClient, settings: Settings
) -> MetricSampler:
    global _sampler, _sampler_repo
    if _sampler is None or _sampler_repo is not repository:
        _sampler = MetricSampler(repository, queue, settings)
        _sampler_repo = repository
    return _sampler


@app.get(
    "/v1/observability/trail/{record_id}",
    response_model=TrailOut,
    summary="Jornada completa de uma observacao",
    tags=["observability"],
)
async def observability_trail(
    record_id: Annotated[str, Path(min_length=1, max_length=64)],
    repository: RepositoryDep = None,  # type: ignore[assignment]
) -> TrailOut:
    """Reconstroi a jornada do registro, com o tempo entre marcos.

    O delta e o que torna a trilha util. O total diz que o registro levou oito
    segundos; o delta diz **onde** eles foram. Oito segundos entre `published` e
    `consumed` sao espera na fila e nenhuma otimizacao do processador os recupera.

    Trilha vazia nao e erro: ela e best-effort e tem TTL de sete dias. Um registro
    antigo, ou um cujas escritas de trilha falharam, devolve a lista vazia — e dizer
    "sem trilha" e mais honesto que um 404 sugerindo que o registro nao existe.
    """
    eventos = await run_in_threadpool(repository.get_trail, record_id)

    saida: list[TrailEventOut] = []
    anterior = None
    for evento in eventos:
        delta = None if anterior is None else (evento.occurred_at - anterior).total_seconds() * 1000
        saida.append(
            TrailEventOut(
                stage=evento.stage.value,
                occurred_at=evento.occurred_at,
                correlation_id=evento.correlation_id,
                service=evento.service,
                detail=evento.detail,
                delta_ms=None if delta is None else round(delta, 3),
            )
        )
        anterior = evento.occurred_at

    total = None
    if len(eventos) > 1:
        bruto = (eventos[-1].occurred_at - eventos[0].occurred_at).total_seconds() * 1000
        total = round(bruto, 3)

    return TrailOut(
        record_id=record_id,
        events=saida,
        total_ms=total,
        services=sorted({e.service for e in eventos}),
    )


@app.get(
    "/v1/observability/series",
    response_model=SeriesOut,
    summary="Serie persistida de profundidade da plataforma",
    tags=["observability"],
)
async def observability_series(
    repository: RepositoryDep,
    queue: QueueDep,
    settings: SettingsDep,
    window: Annotated[int, Query(ge=1, le=1440, description="Janela em minutos")] = 60,
) -> SeriesOut:
    """Devolve a serie gravada, nao contadores em memoria.

    Ao contrario dos graficos da Fase 4, isto sobrevive a recarregar a pagina e a
    reiniciar a API — era a limitacao que o ADR-009 registrou.
    """
    sampler = _get_sampler(repository, queue, settings)
    amostras = await run_in_threadpool(sampler.read, window_minutes=window)

    # Baldes esperados menos baldes medidos. A amostragem e oportunista: com a
    # plataforma parada ninguem passa por /metrics e nada e gravado. A interface
    # precisa do numero para explicar o buraco em vez de desenhar uma reta sobre ele.
    esperados = max(1, (window * 60) // settings.series_interval_seconds)
    return SeriesOut(
        metric=PLATFORM_SERIES,
        origin="persistido",
        interval_seconds=settings.series_interval_seconds,
        window_minutes=window,
        points=[SeriesPointOut(bucket=a.bucket, values=a.values) for a in amostras],
        gaps=max(0, esperados - len(amostras)),
    )


@app.get(
    "/v1/observability/alerts",
    response_model=AlertsOut,
    summary="Condicoes ativas, derivadas do estado real",
    tags=["observability"],
)
async def observability_alerts(
    repository: RepositoryDep, queue: QueueDep, settings: SettingsDep
) -> AlertsOut:
    """Avalia as condicoes no instante da pergunta.

    Nenhuma delas e configurada em outro lugar. Estado declarado envelhece em silencio
    — foi assim que a API passou tres fases anunciando `entity_resolution:
    not_implemented` depois que a Fase 5 a implementou.
    """
    avaliador = AlertEvaluator(repository, queue, settings)
    ativos = await run_in_threadpool(avaliador.evaluate)
    return AlertsOut(
        alerts=[
            AlertOut(
                id=a.id,
                severity=a.severity.value,
                title=a.title,
                detail=a.detail,
                origin=a.origin.value,
                value=a.value,
                threshold=a.threshold,
                context=a.context,
            )
            for a in ativos
        ],
        evaluated_at=utcnow(),
    )


@app.post(
    "/v1/ops/sample",
    response_model=SampleOut,
    summary="Forca uma amostra da janela deslizante",
    tags=["ops"],
)
async def ops_sample(
    repository: RepositoryDep, queue: QueueDep, settings: SettingsDep
) -> SampleOut:
    """Amostra sob demanda, para o EventBridge Scheduler.

    O Scheduler cobre a janela em que ninguem olha o painel. Usa ``force`` porque a
    memoria local do processo nao vale para ele — numa Lambda fria ela esta sempre
    vazia, e numa quente poderia pular a amostragem que o Scheduler existe para fazer.
    A unicidade do balde continua garantida pela escrita condicional.
    """
    sampler = _get_sampler(repository, queue, settings)
    resultado = await run_in_threadpool(sampler.sample, force=True)
    return SampleOut(
        written=resultado.written,
        bucket=resultado.bucket,
        values=resultado.values,
        reason=resultado.reason,
    )
