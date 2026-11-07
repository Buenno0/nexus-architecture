"""Logging estruturado em JSON com ``correlation_id`` propagado.

Uma linha JSON por evento. O ``correlation_id`` e gerado na borda da API e propagado
por ``contextvars`` — inclusive atraves de ``await`` — ate a persistencia, e segue na
mensagem de fila para que o worker continue a mesma trilha.

Isso e o que permite reconstruir a jornada completa de um registro em um sistema onde
as etapas rodam em processos diferentes.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

# Atributos internos do LogRecord: tudo que nao estiver aqui e tratado como campo extra.
_RESERVED: frozenset[str] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


def new_correlation_id() -> str:
    """Gera um novo identificador de correlacao."""
    return uuid.uuid4().hex


def set_correlation_id(value: str) -> None:
    """Fixa o identificador de correlacao do contexto atual."""
    _correlation_id.set(value)


def get_correlation_id() -> str | None:
    """Devolve o identificador de correlacao do contexto atual, se houver."""
    return _correlation_id.get()


class JsonFormatter(logging.Formatter):
    """Serializa cada registro de log como uma unica linha JSON."""

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "event": record.getMessage(),
        }

        correlation_id = get_correlation_id()
        if correlation_id is not None:
            payload["correlation_id"] = correlation_id

        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", service_name: str = "nexus") -> None:
    """Configura o logging do processo. Idempotente."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service_name))

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Uvicorn traz handlers proprios que quebrariam o formato de uma linha JSON.
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(noisy)
        logger.handlers.clear()
        logger.propagate = True


def get_logger(name: str) -> logging.Logger:
    """Atalho para obter um logger nomeado."""
    return logging.getLogger(name)
