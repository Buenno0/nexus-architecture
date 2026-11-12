"""Erros de dominio da plataforma.

Cada erro carrega o codigo HTTP correspondente e um ``code`` estavel para o cliente.
A mensagem exposta ao cliente nunca contem detalhe interno (tabela, ARN, stack trace);
o detalhe completo vai para o log estruturado.
"""

from __future__ import annotations

from typing import Any


class NexusError(Exception):
    """Base de todos os erros de dominio."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        """Representacao segura para resposta HTTP."""
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


class MissingIdempotencyKeyError(NexusError):
    """Header ``Idempotency-Key`` ausente ou vazio — ADR-002."""

    status_code = 400
    code = "missing_idempotency_key"


class IdempotencyConflictError(NexusError):
    """Chave de idempotencia reusada com corpo diferente — ADR-002.

    Devolver a resposta anterior esconderia um bug do cliente.
    """

    status_code = 409
    code = "idempotency_conflict"


class RecordNotFoundError(NexusError):
    """Registro inexistente."""

    status_code = 404
    code = "record_not_found"


class InvalidPaginationCursorError(NexusError):
    """Cursor de paginacao malformado ou adulterado."""

    status_code = 400
    code = "invalid_cursor"


class PersistenceError(NexusError):
    """Falha ao falar com a camada de persistencia."""

    status_code = 503
    code = "persistence_unavailable"


class QueuePublishError(NexusError):
    """Falha ao publicar na fila.

    Nao e fatal para a ingestao: o evento permanece pendente no outbox e sera
    recuperado pelo dispatcher — ADR-003.
    """

    status_code = 503
    code = "queue_unavailable"


class DemoDisabledError(NexusError):
    """Rota de demonstracao chamada fora do modo demo.

    ``404`` em vez de ``403``: fora do modo demonstracao esta rota nao existe, e dizer
    "existe, mas voce nao pode" entrega informacao sobre a plataforma sem necessidade.
    """

    status_code = 404
    code = "not_found"


class DemoQuotaExceededError(NexusError):
    """Teto acumulado de semeadura atingido.

    ``429`` e nao ``403``: o pedido e legitimo e o limite e de taxa acumulada, nao de
    permissao. O cliente nao deve reescrever a chamada, deve parar.
    """

    status_code = 429
    code = "demo_quota_exceeded"
