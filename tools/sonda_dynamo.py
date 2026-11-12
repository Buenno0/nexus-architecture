"""Sonda a latencia do DynamoDB Local — Fase 7.

A medicao de CPU mostrou que, sob carga, nem a API nem o banco encostam no proprio
teto: 24% e 18% na mediana, com P50 de 780 ms na API. Tempo de espera, nao de calculo.

Esta sonda isola a pergunta seguinte: **uma unica operacao no banco fica mais lenta
quando ha concorrencia?** Ela executa a operacao mais barata que existe no modelo — um
`GetItem` por chave primaria, O(1), sem indice — e reporta a distribuicao.

Rodar com a plataforma ociosa e depois sob carga responde se o gargalo esta dentro do
armazenamento. Se a mesma operacao triplica de custo enquanto a CPU sobra, o limite e
de concorrencia interna, nao de capacidade.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nexus.persistence.dynamo import DynamoRecordRepository
from nexus.persistence.models import RecordType
from nexus.persistence.tables import build_client
from nexus.shared.config import Settings


def percentil(valores: list[float], fracao: float) -> float:
    ordenados = sorted(valores)
    indice = min(len(ordenados) - 1, int(fracao * len(ordenados)))
    return round(ordenados[indice], 2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mede a latencia de um GetItem.")
    parser.add_argument("--rotulo", required=True, help="ocioso ou sob-carga")
    parser.add_argument("--amostras", type=int, default=200)
    args = parser.parse_args()

    settings = Settings(
        env="local",
        dynamo_endpoint="http://localhost:8000",
        dynamo_table="nexus-records",
    )
    repo = DynamoRecordRepository(build_client(settings), settings)

    pagina = repo.list_records(RecordType.PERSON, limit=1, cursor=None)
    if not pagina.items:
        print("tabela vazia; pre-carregue registros antes de sondar", file=sys.stderr)
        return 1
    alvo = pagina.items[0].record_id

    duracoes: list[float] = []
    for _ in range(args.amostras):
        inicio = time.perf_counter()
        repo.get_record(alvo)
        duracoes.append((time.perf_counter() - inicio) * 1000)

    resultado = {
        "rotulo": args.rotulo,
        "operacao": "GetItem por chave primaria",
        "amostras": len(duracoes),
        "p50_ms": percentil(duracoes, 0.50),
        "p95_ms": percentil(duracoes, 0.95),
        "p99_ms": percentil(duracoes, 0.99),
        "max_ms": round(max(duracoes), 2),
    }
    destino = Path(__file__).resolve().parent.parent / "docs" / "performance" / "runs"
    (destino / f"sonda-{args.rotulo}.json").write_text(
        json.dumps(resultado, indent=2, ensure_ascii=False) + "\n"
    )
    print(json.dumps(resultado, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
