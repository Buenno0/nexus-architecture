"""Normalizacao de campos — funcoes puras.

## Principio: normalizacao conservadora

A normalizacao na ingestao remove apenas variacao que **com certeza** nao carrega
informacao: espacos em excesso, forma de codificacao Unicode, pontuacao de documentos e
telefones, caixa do e-mail.

Ela deliberadamente **nao** remove acentos nem uniformiza a caixa de nomes. "Jose" e
"Jose" com acento podem ser a mesma pessoa — mas isso e uma hipotese com grau de
confianca, nao um fato. Decidir isso e trabalho do Entity Resolution, onde a diferenca
vira pontuacao auditavel em vez de decisao silenciosa e irreversivel.

Se normalizassemos agressivamente aqui, os dois registros teriam o mesmo fingerprint e o
segundo seria tratado como duplicata exata — uma decisao de identidade tomada pela
camada que menos informacao tem para toma-la.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any

_WHITESPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^0-9A-Za-z]")
_NON_DIGIT = re.compile(r"\D")


def normalize_text(value: str | None) -> str | None:
    """Colapsa espacos e normaliza a forma Unicode.

    NFC garante que caracteres compostos e decompostos ("e" + acento combinante versus
    o caractere unico) produzam a mesma sequencia de bytes. Isso e ruido de codificacao,
    nao diferenca de conteudo — sem isso, dois textos visualmente identicos gerariam
    fingerprints diferentes.
    """
    if value is None:
        return None
    collapsed = _WHITESPACE.sub(" ", unicodedata.normalize("NFC", value)).strip()
    return collapsed or None


def normalize_email(value: str | None) -> str | None:
    """Normaliza e-mail para minusculas.

    O dominio e insensivel a caixa por especificacao. A parte local tecnicamente nao e,
    mas na pratica nenhum provedor relevante diferencia — tratar "Maria@" e "maria@"
    como enderecos distintos produziria duplicatas que nao existem no mundo real.
    """
    text = normalize_text(value)
    return text.lower() if text else None


def normalize_document(value: str | None) -> str | None:
    """Remove pontuacao de documentos, preservando digitos e letras.

    Letras sao preservadas porque identificadores de organizacao podem ser
    alfanumericos. A saida e maiuscula para que a caixa nao gere variacao.
    """
    text = normalize_text(value)
    if text is None:
        return None
    stripped = _NON_ALNUM.sub("", text).upper()
    return stripped or None


def normalize_phone(value: str | None) -> str | None:
    """Reduz telefone a digitos.

    Parenteses, tracos e espacos sao formatacao, nao conteudo. O prefixo internacional
    nao e inferido: adivinhar o pais a partir do comprimento produziria dados errados
    com aparencia de corretos.
    """
    text = normalize_text(value)
    if text is None:
        return None
    digits = _NON_DIGIT.sub("", text)
    return digits or None


def normalize_name(value: str | None) -> str | None:
    """Normaliza nome preservando acentos e caixa.

    Apenas espacos sao tratados. Ver o principio no topo do modulo.
    """
    return normalize_text(value)


#: Normalizador aplicado a cada campo, por nome.
_FIELD_NORMALIZERS = {
    "full_name": normalize_name,
    "legal_name": normalize_name,
    "trade_name": normalize_name,
    "email": normalize_email,
    "document": normalize_document,
    "phone": normalize_phone,
    "country": normalize_document,
    "source": normalize_text,
}


def normalize_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Aplica a normalizacao campo a campo.

    Campos sem normalizador declarado passam por ``normalize_text`` se forem texto, e
    sao mantidos como estao caso contrario (datas, por exemplo, ja foram validadas e
    convertidas pelo Pydantic).

    Chaves cujo valor resulte em ``None`` sao **removidas**. Isso importa para o
    fingerprint: um campo ausente e um campo presente e vazio devem produzir o mesmo
    hash, senao `""` e `null` gerariam observacoes distintas do mesmo conteudo.
    """
    normalized: dict[str, Any] = {}
    for key, value in payload.items():
        normalizer = _FIELD_NORMALIZERS.get(key)
        if normalizer is not None:
            result: Any = normalizer(value if isinstance(value, str) else None)
        elif isinstance(value, str):
            result = normalize_text(value)
        else:
            result = value
        if result is not None:
            normalized[key] = result
    return normalized
