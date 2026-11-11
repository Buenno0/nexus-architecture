"""Arnes de carga — Fase 7.

Executa um cenario do Locust contra a stack local, captura o estado da plataforma
antes e depois, e grava um resultado em JSON. Existe para que a campanha seja
**reproduzivel**: um numero de desempenho sem a receita que o produziu nao e medicao,
e anedota.

O que ele captura alem da latencia:

- **Delta dos contadores de `/metrics`**, para saber quantas ingestoes de fato
  ocorreram — e nao supor pelo numero de requisicoes.
- **Profundidade de fila e outbox**, antes e depois. Se o outbox cresce enquanto a
  latencia da API se mantem, o gargalo e consumo, nao ingestao. Sao conclusoes opostas
  e sem estes dois numeros nao da para distingui-las.
- **Saturacao do proprio gerador.** O Locust avisa quando passa de 90% de CPU; esse
  aviso e capturado e vai para o relatorio. Gerador saturado mede a maquina de origem,
  nao o sistema sob teste, e omitir isso invalidaria tudo o que vem junto.

Uso::

    .venv/bin/python tools/loadtest.py --nome base --usuarios 50 --duracao 60s
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "docs" / "performance" / "runs"
API = "http://localhost:8080"

#: O Locust emite este aviso quando o proprio processo passa de 90% de CPU.
AVISO_CPU = re.compile(r"CPU usage above 90%|high CPU usage", re.IGNORECASE)


def ler(caminho: str) -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(f"{API}{caminho}", timeout=10) as resposta:
            data: dict[str, Any] = json.load(resposta)
            return data
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def estado() -> dict[str, Any]:
    """Fotografia da plataforma: contadores, fila e outbox."""
    metrics = ler("/metrics") or {}
    fila = ler("/v1/ops/queue") or {}
    return {
        "contadores": metrics.get("counters", {}),
        "outbox_pending": fila.get("outbox_pending"),
        "fila": {
            "pending": fila.get("pending"),
            "in_flight": fila.get("in_flight"),
            "dead": fila.get("dead"),
        },
    }


def delta(antes: dict[str, Any], depois: dict[str, Any]) -> dict[str, int]:
    """Quanto cada contador andou durante a janela de medicao.

    Contadores sao cumulativos e do processo. Um valor que diminuiu significa que a
    API reiniciou no meio da corrida — o resultado nao vale, e e melhor dizer isso do
    que publicar uma diferenca negativa como se fosse trabalho realizado.
    """
    saida: dict[str, int] = {}
    for chave, valor in depois["contadores"].items():
        anterior = int(antes["contadores"].get(chave, 0))
        movimento = int(valor) - anterior
        if movimento:
            saida[chave] = movimento
    return saida


def executar_locust(
    *, usuarios: int, taxa: float, duracao: str, prefixo: Path
) -> tuple[list[dict[str, str]], bool, str]:
    comando = [
        sys.executable.replace("/python", "/locust"),
        "-f",
        str(RAIZ / "tests" / "load" / "locustfile.py"),
        "--host",
        API,
        "--headless",
        "-u",
        str(usuarios),
        "-r",
        str(taxa),
        "-t",
        duracao,
        "--csv",
        str(prefixo),
        "--only-summary",
    ]
    processo = subprocess.run(comando, capture_output=True, text=True, check=False)
    saida = processo.stdout + processo.stderr
    saturado = bool(AVISO_CPU.search(saida))

    arquivo = prefixo.with_name(prefixo.name + "_stats.csv")
    if not arquivo.exists():
        raise RuntimeError(f"Locust nao produziu estatisticas.\n{saida[-2000:]}")
    with arquivo.open(newline="") as f:
        linhas = list(csv.DictReader(f))
    return linhas, saturado, saida


def resumir(linhas: list[dict[str, str]]) -> dict[str, Any]:
    """Converte o CSV do Locust em algo legivel, sem media sozinha.

    A media de latencia esconde a cauda, e a cauda e o que o usuario sente. P95 e P99
    vao sempre juntos; a media aparece apenas ao lado deles.
    """
    cenarios: dict[str, Any] = {}
    agregado: dict[str, Any] = {}
    for linha in linhas:
        nome = linha["Name"]
        dado = {
            "requisicoes": int(linha["Request Count"]),
            "falhas": int(linha["Failure Count"]),
            "rps": round(float(linha["Requests/s"]), 2),
            "media_ms": round(float(linha["Average Response Time"]), 2),
            "p50_ms": round(float(linha["50%"]), 2),
            "p95_ms": round(float(linha["95%"]), 2),
            "p99_ms": round(float(linha["99%"]), 2),
            "max_ms": round(float(linha["Max Response Time"]), 2),
        }
        if linha["Type"] == "" or nome == "Aggregated":
            agregado = dado
        else:
            cenarios[f"{linha['Type']} {nome}"] = dado
    return {"agregado": agregado, "cenarios": cenarios}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Executa uma corrida de carga.")
    parser.add_argument("--nome", required=True, help="identificador da corrida")
    parser.add_argument("--usuarios", type=int, default=50)
    parser.add_argument("--taxa", type=float, default=10)
    parser.add_argument("--duracao", default="60s")
    parser.add_argument("--nota", default="", help="o que esta corrida quer responder")
    args = parser.parse_args(argv)

    SAIDA.mkdir(parents=True, exist_ok=True)
    prefixo = SAIDA / args.nome

    saude = ler("/health")
    if saude is None or saude.get("status") != "ok":
        print("API indisponivel. Suba a stack com `make up` antes de medir.", file=sys.stderr)
        return 1

    antes = estado()
    inicio = time.perf_counter()
    linhas, saturado, bruto = executar_locust(
        usuarios=args.usuarios, taxa=args.taxa, duracao=args.duracao, prefixo=prefixo
    )
    decorrido = time.perf_counter() - inicio
    depois = estado()

    resultado = {
        "nome": args.nome,
        "nota": args.nota,
        "quando": datetime.now(UTC).isoformat(),
        "parametros": {
            "usuarios": args.usuarios,
            "taxa_de_subida": args.taxa,
            "duracao": args.duracao,
            "decorrido_s": round(decorrido, 1),
        },
        "ambiente": {
            "trail_enabled": saude.get("trail_enabled"),
            "api_workers": saude.get("api_workers"),
            "environment": saude.get("environment"),
        },
        "latencia": resumir(linhas),
        "contadores_delta": delta(antes, depois),
        "fila": {"antes": antes["fila"], "depois": depois["fila"]},
        "outbox": {"antes": antes["outbox_pending"], "depois": depois["outbox_pending"]},
        "gerador_saturado": saturado,
    }

    destino = SAIDA / f"{args.nome}.json"
    destino.write_text(json.dumps(resultado, indent=2, ensure_ascii=False) + "\n")

    agregado = resultado["latencia"]["agregado"]
    print(
        f"{args.nome}: {agregado.get('rps')} req/s  "
        f"p50={agregado.get('p50_ms')}ms  p95={agregado.get('p95_ms')}ms  "
        f"p99={agregado.get('p99_ms')}ms  falhas={agregado.get('falhas')}"
    )
    if saturado:
        print(
            "  AVISO: o gerador de carga saturou a CPU. O numero mede a maquina de "
            "origem, nao a plataforma.",
            file=sys.stderr,
        )
    if not bruto:
        print("  (sem saida do Locust)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
