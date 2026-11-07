"""Camada de persistencia.

A fabrica ``get_repository`` e o unico ponto onde o ambiente decide a implementacao.
Nenhum outro modulo deve ramificar por ``NEXUS_ENV``.
"""

from __future__ import annotations

from functools import lru_cache

from nexus.persistence.repository import RecordRepository


@lru_cache(maxsize=1)
def get_repository() -> RecordRepository:
    """Devolve o repositorio configurado para o ambiente atual."""
    from nexus.persistence.dynamo import DynamoRecordRepository

    # DynamoDB Local e DynamoDB gerenciado compartilham a mesma implementacao;
    # o que muda e apenas o endpoint. Ver ADR-001.
    return DynamoRecordRepository()


__all__ = ["RecordRepository", "get_repository"]
