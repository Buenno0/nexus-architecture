"""Fonte de tempo da plataforma.

Centralizada para que todo carimbo tenha a mesma precisao e o mesmo fuso. Carimbos com
precisoes diferentes comparam mal quando usados como chave de ordenacao, e tempo local
em sistema distribuido e fonte de bug silencioso.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Agora, em UTC, truncado para milissegundos.

    A truncagem casa com a precisao do ULID: identificador e carimbo de tempo ordenam
    de forma consistente entre si.
    """
    now = datetime.now(UTC)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)
