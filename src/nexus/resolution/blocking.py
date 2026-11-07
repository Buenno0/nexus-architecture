"""Blocking: selecao de candidatos.

Comparar todos contra todos e O(n²) — inviavel. O blocking reduz o universo: cada
registro produz varias chaves, e dois registros so sao comparados se compartilham ao
menos uma.

## O erro do blocking e assimetrico

| Erro | Consequencia |
|---|---|
| Incluir candidato demais | Comparacoes extras, que o score descarta. Custa tempo. |
| Perder um par verdadeiro | **Definitivo.** Nenhuma pontuacao posterior o recupera. |

Por isso as chaves sao generosas e a normalizacao e agressiva (`resolution/text.py`).
Errar para o lado de agrupar demais e a escolha correta aqui — e seria destrutiva na
ingestao, onde o mesmo erro descartaria dados.

## Multiplas chaves, nao uma composta

Uma chave unica combinando documento e nome so encontraria registros que concordam em
**ambos**. Chaves independentes encontram quem concorda em **qualquer um** — que e o
caso interessante: a mesma pessoa cadastrada uma vez com documento e outra sem.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from nexus.resolution.comparators import PHONE_SUFFIX_DIGITS
from nexus.resolution.text import alnum, digits, fold, tokens

#: Tokens sem poder discriminante em nomes de organizacao. Bloquear por eles agruparia
#: metade do cadastro numa particao so.
ORGANIZATION_STOPWORDS = frozenset(
    {
        "ltda",
        "sa",
        "s",
        "a",
        "me",
        "epp",
        "eireli",
        "mei",
        "cia",
        "comercio",
        "servicos",
        "industria",
        "e",
        "de",
        "da",
        "do",
        "das",
        "dos",
        "the",
        "inc",
        "llc",
        "corp",
        "group",
        "grupo",
    }
)

#: Minimo de caracteres para uma chave de nome valer. Chaves curtas demais agrupam
#: registros sem relacao e estouram o teto de candidatos sem beneficio.
MIN_NAME_KEY_LENGTH = 3


def _document_key(normalized: Mapping[str, Any]) -> str | None:
    value = alnum(normalized.get("document"))
    return f"doc:{value}" if value else None


def _email_key(normalized: Mapping[str, Any]) -> str | None:
    value = fold(normalized.get("email"))
    return f"email:{value}" if value else None


def _phone_key(normalized: Mapping[str, Any]) -> str | None:
    value = digits(normalized.get("phone"))
    if len(value) < PHONE_SUFFIX_DIGITS:
        return None
    return f"phone:{value[-PHONE_SUFFIX_DIGITS:]}"


def _person_name_key(normalized: Mapping[str, Any]) -> str | None:
    """Inicial do primeiro nome mais o ultimo sobrenome.

    Sobrevive a abreviacao ("Maria Aparecida Souza" e "M. A. Souza" caem no mesmo bloco)
    e a nomes do meio ausentes, que sao as variacoes mais comuns entre fontes.
    """
    parts = tokens(normalized.get("full_name"))
    if not parts:
        return None
    if len(parts) == 1:
        return f"name:{parts[0]}" if len(parts[0]) >= MIN_NAME_KEY_LENGTH else None
    last = parts[-1]
    if len(last) < MIN_NAME_KEY_LENGTH:
        return None
    return f"name:{parts[0][0]}|{last}"


def _organization_name_key(normalized: Mapping[str, Any]) -> str | None:
    """Dois primeiros tokens significativos da razao social."""
    parts = [
        token
        for token in tokens(normalized.get("legal_name"))
        if token not in ORGANIZATION_STOPWORDS and len(token) >= 2
    ]
    if not parts:
        return None
    key = "-".join(parts[:2])
    return f"name:{key}" if len(key) >= MIN_NAME_KEY_LENGTH else None


_KEY_BUILDERS = {
    "person": (_document_key, _email_key, _person_name_key, _phone_key),
    "organization": (_document_key, _email_key, _organization_name_key, _phone_key),
}


def blocking_keys(record_type: str, normalized: Mapping[str, Any]) -> list[str]:
    """Chaves de bloco de um registro, sem duplicatas e em ordem estavel.

    A ordem estavel importa para teste e para log: a mesma entrada produz sempre a mesma
    sequencia.
    """
    builders = _KEY_BUILDERS.get(record_type, ())
    keys: list[str] = []
    for builder in builders:
        key = builder(normalized)
        if key and key not in keys:
            keys.append(key)
    return keys
