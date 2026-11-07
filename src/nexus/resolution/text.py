"""Normalizacao agressiva para comparacao.

**Esta normalizacao e o oposto da normalizacao da ingestao, de proposito.**

| | Ingestao (`ingestion/normalization.py`) | Aqui |
|---|---|---|
| Objetivo | Preservar sinal | Maximizar recall |
| Acentos | Preservados | Removidos |
| Caixa de nomes | Preservada | Minusculas |
| Erra para | Nao agrupar demais | Agrupar demais |

A ingestao grava o dado como ele chegou, porque acento e caixa sao evidencia para o
resolvedor. Aqui, comparando, essas diferencas viram ruido: "Jose" e "Jose" com acento
precisam colidir no mesmo bloco para que o score possa avalia-los.

Agrupar demais custa comparacoes extras, que o score descarta. Agrupar de menos perde o
par para sempre — **o falso negativo do blocking e definitivo**, nenhuma pontuacao
posterior o recupera.
"""

from __future__ import annotations

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^0-9a-z]+")
_NON_DIGIT = re.compile(r"\D")
_WHITESPACE = re.compile(r"\s+")


def fold(value: str | None) -> str:
    """Remove acentos, baixa a caixa e colapsa espacos.

    Devolve string vazia para ``None`` — simplifica os comparadores, que nunca precisam
    verificar nulo antes de comparar.
    """
    if not value:
        return ""
    decomposed = unicodedata.normalize("NFKD", value)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return _WHITESPACE.sub(" ", without_marks).strip().lower()


def tokens(value: str | None) -> list[str]:
    """Divide em tokens alfanumericos, ja normalizados."""
    folded = fold(value)
    return [token for token in _NON_ALNUM.split(folded) if token]


def alnum(value: str | None) -> str:
    """Mantem apenas letras e digitos, normalizados."""
    return _NON_ALNUM.sub("", fold(value))


def digits(value: str | None) -> str:
    """Mantem apenas digitos."""
    return _NON_DIGIT.sub("", value or "")
