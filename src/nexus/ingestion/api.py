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
from fastapi.responses import JSONResponse

from nexus import __version__
from nexus.ingestion.schemas import (
    DispatchOut,
    DispatchRequest,
    ErrorOut,
    HealthOut,
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
)
from nexus.ingestion.service import IngestionResult, IngestionService
from nexus.observability.metrics import registry
from nexus.observability.middleware import ObservabilityMiddleware
from nexus.persistence import get_repository
from nexus.persistence.models import RecordType, StoredRecord
from nexus.persistence.repository import RecordRepository
from nexus.queue import get_queue_client
from nexus.queue.client import QueueClient
from nexus.queue.dispatcher import OutboxDispatcher
from nexus.queue.worker import Worker
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


def _to_detail(record: StoredRecord) -> RecordDetail:
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
    return _to_detail(record)


@app.get(
    "/v1/records",
    response_model=RecordPage,
    summary="Listagem paginada de observacoes",
    tags=["records"],
)
async def list_records(
    repository: RepositoryDep,
    record_type: Annotated[RecordType, Query(description="Tipo de registro")] = RecordType.PERSON,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: Annotated[str | None, Query(max_length=2048)] = None,
) -> RecordPage:
    settings = get_settings()
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
async def health(repository: RepositoryDep, queue: QueueDep) -> HealthOut:
    settings = get_settings()
    persistence_ok = await run_in_threadpool(repository.ping)
    return HealthOut(
        status="ok" if persistence_ok else "degraded",
        environment=settings.env,
        version=__version__,
        persistence="ok" if persistence_ok else "unavailable",
        queue="enabled" if queue.is_enabled else "not_implemented",
    )


@app.get("/metrics", summary="Metricas operacionais", tags=["ops"])
async def metrics(repository: RepositoryDep, queue: QueueDep) -> dict[str, Any]:
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

    return {
        "scope": "in_process",
        "environment": get_settings().env,
        "outbox_pending": backlog,
        # Profundidade da fila vem do armazenamento, nao de contadores em memoria:
        # sobrevive a reinicio e e consistente entre processos, ao contrario de
        # "counters" e "latency_ms" abaixo.
        "queue": queue_depth,
        "modules": {
            "ingestion": "implemented",
            "queue_engine": "implemented" if queue.is_enabled else "disabled",
            "entity_resolution": "not_implemented",
            "observability": "partial",
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
