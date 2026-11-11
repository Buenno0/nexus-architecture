"""Analise da particao quente do `gsi_recency` — Fase 7.

`docs/architecture/access-patterns.md` registra desde a Fase 1 que o `gsi_recency` usa
`PK = "RECORDS#<tipo>"` — um unico valor de particao para todos os registros de um
tipo — e afirma que o limite de 1.000 WCU/s "nao e alcancado nos volumes deste
projeto". A afirmacao estava certa por intuicao e **nunca tinha sido medida**.

Este script fecha isso. Ele nao estima o tamanho do item: usa o mesmo serializador que
grava na tabela, e aplica a regra de cobranca do DynamoDB (nome + valor, em bytes
UTF-8, arredondado para cima em blocos de 1 KB).
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nexus.persistence.dynamo import _record_to_item
from nexus.persistence.models import RecordType, StoredRecord
from nexus.shared.clock import utcnow
from nexus.shared.identity import new_ulid

#: Teto de escrita por particao na AWS. Vale por particao fisica, nao por tabela.
WCU_POR_PARTICAO = 1_000
BYTES_POR_WCU = 1_024


def tamanho(valor: Any) -> int:
    """Bytes que o DynamoDB cobra por um valor.

    Regra da documentacao: strings e binarios valem os proprios bytes; numeros tem
    tamanho variavel e sao aproximados pelo comprimento da representacao decimal;
    mapas e listas somam os filhos mais 1 byte por elemento.
    """
    if isinstance(valor, str):
        return len(valor.encode("utf-8"))
    if isinstance(valor, bool):
        return 1
    if isinstance(valor, int | float | Decimal):
        return max(1, len(str(valor)))
    if isinstance(valor, dict):
        return sum(len(k.encode("utf-8")) + tamanho(v) + 1 for k, v in valor.items())
    if isinstance(valor, list | tuple):
        return sum(tamanho(v) + 1 for v in valor)
    if valor is None:
        return 1
    return len(str(valor).encode("utf-8"))


def tamanho_do_item(item: dict[str, Any]) -> int:
    return sum(len(nome.encode("utf-8")) + tamanho(valor) for nome, valor in item.items())


def registro_representativo() -> StoredRecord:
    """Um registro como o gerador produz, com os campos todos preenchidos.

    Campos vazios tornariam o item menor e o resultado otimista. O caso que importa e
    o registro completo, que e o que a API aceita no caminho feliz.
    """
    normalizado = {
        "full_name": "maria aparecida souza",
        "email": "maria.aparecida.souza@example.com",
        "document": "12345678909",
        "phone": "5511987654321",
        "birth_date": "1988-04-17",
    }
    return StoredRecord(
        record_id=new_ulid(),
        record_type=RecordType.PERSON,
        source="synthetic-generator",
        natural_key="person|12345678909",
        record_fingerprint="d067d5f2285b86b7d7072fc5c93c85d11a82cbaaac08685c885d5fd6fb0c1f8e",
        payload={
            "source": "synthetic-generator",
            "full_name": "Maria Aparecida Souza",
            "email": "Maria.Aparecida.Souza@Example.com",
            "document": "123.456.789-09",
            "phone": "(11) 98765-4321",
            "birth_date": "1988-04-17",
        },
        normalized=normalizado,
        correlation_id="52015d456696412b8a1cb032b339a67b",
        created_at=utcnow(),
    )


def main() -> int:
    item = _record_to_item(registro_representativo())
    bytes_item = tamanho_do_item(item)

    # Projecao ALL: o indice recebe o item inteiro, nao um recorte. Foi uma escolha
    # para evitar leitura adicional na listagem, e o preco dela aparece aqui.
    wcu_por_registro = max(1, -(-bytes_item // BYTES_POR_WCU))
    registros_por_segundo = WCU_POR_PARTICAO / wcu_por_registro

    resultado = {
        "atributos_do_item": len(item),
        "bytes_do_item": bytes_item,
        "projecao_do_indice": "ALL",
        "wcu_por_escrita_no_indice": wcu_por_registro,
        "teto_da_particao_wcu_s": WCU_POR_PARTICAO,
        "registros_por_segundo_ate_saturar": round(registros_por_segundo, 1),
    }
    print(json.dumps(resultado, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
