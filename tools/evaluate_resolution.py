#!/usr/bin/env python3
"""Avalia a qualidade da resolucao de identidade contra um gabarito.

Sem gabarito nao e possivel afirmar que a resolucao **funciona** — apenas que ela roda.
O gerador sintetico produz o gabarito com ``--manifest``: cada registro carrega a
entidade verdadeira que o originou.

## Como a medicao e feita

Comparando **pares**, nao clusters. Dois registros formam um par verdadeiro se o
gabarito os coloca na mesma entidade, e um par previsto se o resolvedor os colocou na
mesma entidade.

| | Significado | Custo no mundo real |
|---|---|---|
| Falso positivo | Uniu quem nao devia | **Critico.** Dados de pessoas distintas se misturam |
| Falso negativo | Nao uniu quem devia | Duplicata permanece; corrigivel depois |

Por isso precisao e recall sao reportados separadamente: uma media esconderia
exatamente a assimetria que importa.

Uso::

    python tools/evaluate_resolution.py --manifest gabarito.json
    python tools/evaluate_resolution.py --manifest gabarito.json --show 10
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

import httpx

DEFAULT_URL = "http://localhost:8080"


@dataclass
class Evaluation:
    """Resultado da comparacao entre gabarito e resolucao."""

    records: int
    true_pairs: set[tuple[str, str]]
    predicted_pairs: set[tuple[str, str]]
    unresolved: int

    @property
    def true_positives(self) -> set[tuple[str, str]]:
        return self.true_pairs & self.predicted_pairs

    @property
    def false_positives(self) -> set[tuple[str, str]]:
        return self.predicted_pairs - self.true_pairs

    @property
    def false_negatives(self) -> set[tuple[str, str]]:
        return self.true_pairs - self.predicted_pairs

    @property
    def precision(self) -> float:
        if not self.predicted_pairs:
            return 1.0
        return len(self.true_positives) / len(self.predicted_pairs)

    @property
    def recall(self) -> float:
        if not self.true_pairs:
            return 1.0
        return len(self.true_positives) / len(self.true_pairs)

    @property
    def f1(self) -> float:
        if self.precision + self.recall == 0:
            return 0.0
        return 2 * self.precision * self.recall / (self.precision + self.recall)


def pairs_of(groups: dict[Any, list[str]]) -> set[tuple[str, str]]:
    """Todos os pares nao ordenados dentro de cada grupo."""
    result: set[tuple[str, str]] = set()
    for members in groups.values():
        if len(members) < 2:
            continue
        for left, right in combinations(sorted(members), 2):
            result.add((left, right))
    return result


def fetch_entities(client: httpx.Client, url: str, record_ids: list[str]) -> dict[str, str | None]:
    """Descobre a entidade atribuida a cada registro."""
    assigned: dict[str, str | None] = {}
    for index, record_id in enumerate(record_ids, start=1):
        response = client.get(f"{url}/v1/records/{record_id}", timeout=30.0)
        if response.status_code != 200:
            print(f"  aviso: registro {record_id} devolveu {response.status_code}", file=sys.stderr)
            assigned[record_id] = None
            continue
        assigned[record_id] = response.json().get("entity_id")
        if index % 200 == 0:
            print(f"  ... {index}/{len(record_ids)}", file=sys.stderr)
    return assigned


def evaluate(truth: dict[str, int], assigned: dict[str, str | None]) -> Evaluation:
    verdadeiros: dict[int, list[str]] = defaultdict(list)
    for record_id, entity in truth.items():
        verdadeiros[entity].append(record_id)

    previstos: dict[str, list[str]] = defaultdict(list)
    unresolved = 0
    for record_id, entity_id in assigned.items():
        if entity_id is None:
            # Sem entidade, o registro e um cluster de um so — nao gera par nenhum.
            unresolved += 1
            continue
        previstos[entity_id].append(record_id)

    return Evaluation(
        records=len(truth),
        true_pairs=pairs_of(verdadeiros),
        predicted_pairs=pairs_of(previstos),
        unresolved=unresolved,
    )


def render(evaluation: Evaluation, truth: dict[str, int], show: int) -> None:
    print()
    print("=" * 62)
    print("AVALIACAO DA RESOLUCAO DE IDENTIDADE")
    print("=" * 62)
    print(f"registros avaliados      {evaluation.records}")
    print(f"entidades verdadeiras    {len(set(truth.values()))}")
    print(f"sem entidade atribuida   {evaluation.unresolved}")
    print()
    print(f"pares verdadeiros        {len(evaluation.true_pairs)}")
    print(f"pares previstos          {len(evaluation.predicted_pairs)}")
    print(f"acertos                  {len(evaluation.true_positives)}")
    print(f"falsos positivos         {len(evaluation.false_positives)}  (uniu quem nao devia)")
    print(f"falsos negativos         {len(evaluation.false_negatives)}  (nao uniu quem devia)")
    print()
    print(f"precisao                 {evaluation.precision:.4f}")
    print(f"recall                   {evaluation.recall:.4f}")
    print(f"F1                       {evaluation.f1:.4f}")

    if show and evaluation.false_positives:
        print()
        print(f"--- falsos positivos (ate {show}) ---")
        for left, right in sorted(evaluation.false_positives)[:show]:
            print(f"  {left}  +  {right}")

    if show and evaluation.false_negatives:
        print()
        print(f"--- falsos negativos (ate {show}) ---")
        for left, right in sorted(evaluation.false_negatives)[:show]:
            print(f"  {left}  x  {right}")

    print()
    if evaluation.false_positives:
        print("ATENCAO: falso positivo une pessoas distintas e e o risco critico do projeto.")
        print("Considere elevar resolution_match_threshold ou revisar os pesos.")
    elif evaluation.false_negatives:
        print("Sem falsos positivos. Os falsos negativos sugerem blocking estreito ou")
        print("limiar alto demais — ambos corrigiveis sem risco de corromper dados.")
    else:
        print("Nenhum erro de pareamento neste conjunto.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--manifest", required=True, help="gabarito gerado por tools/generator.py")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--show", type=int, default=5, help="exemplos de erro a listar")
    args = parser.parse_args(argv)

    caminho = Path(args.manifest)
    if not caminho.exists():
        print(f"erro: gabarito nao encontrado: {caminho}", file=sys.stderr)
        return 2

    dados = json.loads(caminho.read_text(encoding="utf-8"))
    truth: dict[str, int] = dados["truth"]
    if not truth:
        print("erro: gabarito vazio", file=sys.stderr)
        return 2

    print(f"Consultando {len(truth)} registros em {args.url} ...", file=sys.stderr)
    with httpx.Client() as client:
        assigned = fetch_entities(client, args.url, list(truth))

    evaluation = evaluate(truth, assigned)
    render(evaluation, truth, args.show)
    # Falso positivo e o unico erro que corrompe dados; ele define o codigo de saida.
    return 1 if evaluation.false_positives else 0


if __name__ == "__main__":
    sys.exit(main())
