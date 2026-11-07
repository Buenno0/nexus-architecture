"""Primitivas de identidade — ADR-002.

Tres conceitos distintos, deliberadamente separados:

``idempotency_key``
    Identifica uma **operacao de ingestao**. Vem do cliente, no header
    ``Idempotency-Key``. Replay da mesma operacao devolve a resposta armazenada.

``record_fingerprint``
    Identifica um **conteudo normalizado**. Calculado pelo servidor. Reenvio
    byte-identico nao gera nova observacao.

``natural_key``
    Chave de **agrupamento para consulta**, nao de unicidade. Permite localizar
    observacoes candidatas da mesma entidade sem varrer a tabela. Duas observacoes com
    a mesma ``natural_key`` e fingerprints diferentes sao duas observacoes distintas e
    legitimas — quem decide se representam a mesma entidade e o Entity Resolution.

Confundir os tres produz perda silenciosa de dados. Ver ADR-002.

Todas as funcoes deste modulo sao puras e deterministas, exceto ``new_ulid``.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from collections.abc import Mapping
from typing import Any

# Alfabeto Crockford base32: sem I, L, O e U, para evitar ambiguidade visual.
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

_TIMESTAMP_CHARS = 10  # 50 bits, suficiente para os 48 bits de milissegundos
_RANDOM_CHARS = 16  # 80 bits de aleatoriedade
_MAX_TIMESTAMP_MS = (1 << 48) - 1

#: Grupos de campos candidatos a chave natural, em ordem de preferencia.
#: O primeiro grupo cujos campos estejam todos preenchidos e utilizado.
_NATURAL_KEY_FIELDS: dict[str, tuple[tuple[str, ...], ...]] = {
    "person": (("document",), ("email",), ("full_name", "phone")),
    "organization": (("document",), ("email",), ("legal_name",)),
}


def _encode_crockford(value: int, length: int) -> str:
    chars: list[str] = []
    for _ in range(length):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def new_ulid(timestamp_ms: int | None = None) -> str:
    """Gera um identificador de 26 caracteres ordenavel por tempo.

    Ao contrario do UUID4, ULIDs ordenam lexicograficamente na mesma ordem em que foram
    criados. Isso importa porque o identificador e usado como chave de ordenacao no
    DynamoDB: listar registros em ordem cronologica vira uma ``Query`` ordenada em vez
    de uma ordenacao em memoria.

    :param timestamp_ms: milissegundos desde a epoca. Apenas para testes determinísticos.
    """
    ts = int(time.time() * 1000) if timestamp_ms is None else timestamp_ms
    if not 0 <= ts <= _MAX_TIMESTAMP_MS:
        raise ValueError(f"timestamp fora da faixa representavel: {ts}")
    return _encode_crockford(ts, _TIMESTAMP_CHARS) + _encode_crockford(
        secrets.randbits(80), _RANDOM_CHARS
    )


def canonical_json(payload: Mapping[str, Any]) -> str:
    """Serializa um mapa de forma deterministica.

    Chaves ordenadas e separadores sem espaco: dois mapas equivalentes produzem sempre
    a mesma string, independentemente da ordem de insercao. Sem isso, o fingerprint
    mudaria conforme a ordem dos campos no JSON recebido.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_fingerprint(record_type: str, normalized: Mapping[str, Any]) -> str:
    """Hash deterministico do conteudo normalizado.

    Recebe o payload **ja normalizado**: o fingerprint precisa ser estavel diante de
    variacoes irrelevantes (maiusculas no e-mail, pontuacao no documento, espacos
    extras). Normalizar depois do hash tornaria o hash inutil.

    O tipo entra no hash para que uma pessoa e uma organizacao com os mesmos campos
    nunca colidam.
    """
    return _sha256(f"{record_type}\x00{canonical_json(normalized)}")


def request_hash(raw_body: bytes) -> str:
    """Hash do corpo bruto da requisicao.

    Usado para detectar reuso de ``Idempotency-Key`` com payload diferente, que deve
    resultar em ``409`` — ver ADR-002. Aqui o corpo **bruto** e o correto: queremos
    saber se o cliente enviou algo diferente, nao se o resultado normalizado difere.
    """
    return hashlib.sha256(raw_body).hexdigest()


def natural_key(record_type: str, normalized: Mapping[str, Any]) -> str:
    """Chave de agrupamento para localizar observacoes candidatas.

    **Nao e chave de unicidade.** Duas observacoes podem compartilhar a mesma chave
    natural com conteudos diferentes — e isso e esperado: significa que a mesma entidade
    foi observada duas vezes, possivelmente com dados atualizados.

    Se nenhum campo identificador estiver presente, recai no proprio fingerprint. Nesse
    caso o registro so pode ser deduplicado de forma byte-exata, o que e a unica
    garantia possivel sem informacao identificadora.
    """
    groups = _NATURAL_KEY_FIELDS.get(record_type, ())
    for fields in groups:
        values = [str(normalized.get(field) or "").strip() for field in fields]
        if all(values):
            joined = "\x00".join(values)
            return f"{record_type}|{'+'.join(fields)}|{_sha256(joined)}"
    return f"{record_type}|fingerprint|{record_fingerprint(record_type, normalized)}"


def idempotency_scope(source: str, key: str) -> str:
    """Escopo da chave de idempotencia.

    A chave e escopada por fonte: duas fontes independentes podem legitimamente escolher
    a mesma chave sem interferir uma na outra.
    """
    return f"{source}\x00{key}"
