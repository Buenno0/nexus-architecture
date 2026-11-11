"""Compara corridas de carga — Fase 7.

Le os resultados de ``docs/performance/runs/`` e monta as tabelas do relatorio. Existe
para que a analise seja derivada dos arquivos, nao transcrita a mao: numero copiado e
numero que pode estar errado, e a Fase 6 ja custou uma correcao por causa disso.

Toda tabela traz P95 e P99 ao lado da media. A media sozinha esconde a cauda, e a
cauda e o que o usuario sente.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

RUNS = Path(__file__).resolve().parent.parent / "docs" / "performance" / "runs"

EIXOS = {
    "volume": ("volume-", "Acervo"),
    "concorrencia": ("concorrencia-", "Usuarios"),
    "workers": ("workers-", "Processos"),
    "trilha": ("trilha-", "Trilha"),
}


def carregar(prefixo: str) -> list[dict[str, Any]]:
    corridas = []
    for arquivo in sorted(RUNS.glob(f"{prefixo}*.json")):
        corridas.append(json.loads(arquivo.read_text()))
    return sorted(corridas, key=lambda c: _ordem(c["nome"]))


def _ordem(nome: str) -> tuple[int, str]:
    sufixo = nome.split("-", 1)[1] if "-" in nome else nome
    return (int(sufixo), "") if sufixo.isdigit() else (0, sufixo)


def linha_de(corrida: dict[str, Any]) -> dict[str, Any]:
    agregado = corrida["latencia"]["agregado"]
    novos = corrida["contadores_delta"].get("ingestion_accepted_total{record_type=person}", 0)
    return {
        "rotulo": corrida["nome"].split("-", 1)[1],
        "rps": agregado["rps"],
        "p50": agregado["p50_ms"],
        "p95": agregado["p95_ms"],
        "p99": agregado["p99_ms"],
        "media": agregado["media_ms"],
        "max": agregado["max_ms"],
        "falhas": agregado["falhas"],
        "aceitos": novos,
        "fila_depois": corrida["fila"]["depois"]["pending"],
        "outbox_depois": corrida["outbox"]["depois"],
        "saturado": corrida["gerador_saturado"],
        "aquecimento_p50": corrida["latencia"].get("aquecimento", {}).get("p50_ms"),
    }


def tabela(eixo: str) -> str:
    prefixo, titulo = EIXOS[eixo]
    corridas = carregar(prefixo)
    if not corridas:
        return f"_Sem corridas para o eixo `{eixo}`._\n"

    cabecalho = (
        f"| {titulo} | req/s | P50 | P95 | P99 | media | max | falhas | "
        "aceitos | fila ao fim |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
    )
    linhas = ""
    avisos = []
    for corrida in corridas:
        d = linha_de(corrida)
        linhas += (
            f"| {d['rotulo']} | {d['rps']} | {d['p50']} ms | {d['p95']} ms | "
            f"{d['p99']} ms | {d['media']} ms | {d['max']} ms | {d['falhas']} | "
            f"{d['aceitos']} | {d['fila_depois']} |\n"
        )
        if d["saturado"]:
            avisos.append(
                f"- **A corrida `{d['rotulo']}` saturou o gerador.** O numero mede a "
                "maquina de origem, nao a plataforma."
            )
        if d["outbox_depois"]:
            avisos.append(
                f"- A corrida `{d['rotulo']}` terminou com {d['outbox_depois']} eventos "
                "pendentes no outbox: a publicacao inline nao deu conta."
            )
    return cabecalho + linhas + ("\n" + "\n".join(avisos) + "\n" if avisos else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compara corridas de carga.")
    parser.add_argument("--eixo", choices=sorted(EIXOS))
    args = parser.parse_args(argv)

    for eixo in [args.eixo] if args.eixo else EIXOS:
        print(f"\n### {eixo}\n")
        print(tabela(eixo))
    return 0


if __name__ == "__main__":
    sys.exit(main())
