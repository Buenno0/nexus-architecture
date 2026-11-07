"""Middleware de observabilidade.

Gera e propaga o ``correlation_id`` e mede a latencia de cada requisicao.

O identificador vem do header ``X-Correlation-ID`` quando o cliente o fornece — o que
permite correlacionar com o sistema de origem — e e gerado quando ausente. Ele volta na
resposta para que o cliente possa citar um identificador rastreavel ao reportar
problemas, sem que precisemos expor detalhes internos no corpo do erro.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from nexus.observability.metrics import registry
from nexus.shared.logging import get_logger, new_correlation_id, set_correlation_id

logger = get_logger(__name__)

CORRELATION_HEADER = "X-Correlation-ID"

#: Rotas excluidas das metricas: observar o proprio endpoint de observabilidade
#: distorceria os numeros com trafego de monitoramento.
_EXCLUDED_PATHS = frozenset({"/metrics", "/health", "/docs", "/openapi.json", "/redoc"})


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        incoming = request.headers.get(CORRELATION_HEADER, "").strip()
        correlation_id = incoming[:64] if incoming else new_correlation_id()
        set_correlation_id(correlation_id)
        request.state.correlation_id = correlation_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            self._record(request, 500, duration_ms)
            logger.exception("request_failed", extra={"path": request.url.path})
            raise

        duration_ms = (time.perf_counter() - started) * 1000
        self._record(request, response.status_code, duration_ms)
        response.headers[CORRELATION_HEADER] = correlation_id

        if request.url.path not in _EXCLUDED_PATHS:
            logger.info(
                "request_completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration_ms, 3),
                },
            )
        return response

    @staticmethod
    def _record(request: Request, status_code: int, duration_ms: float) -> None:
        if request.url.path in _EXCLUDED_PATHS:
            return
        # Template da rota, nao o caminho concreto: /v1/records/{id} em vez de
        # /v1/records/01ABC... — senao cada identificador viraria uma serie propria.
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        registry.increment(
            "http_requests_total",
            method=request.method,
            path=path,
            status=str(status_code),
        )
        registry.observe("http_request_duration", duration_ms, method=request.method, path=path)
