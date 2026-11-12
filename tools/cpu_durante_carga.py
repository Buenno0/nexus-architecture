"""Amostra o consumo de CPU dos containers durante uma corrida — Fase 7.

A campanha mostrou que **aumentar os processos da API piorou** o resultado: 1 worker
deu 163 req/s e 4 workers deram 150. Isso elimina o processo unico como gargalo, mas
nao diz onde o gargalo esta. Atribuir por eliminacao seria palpite; este script mede.

Se o DynamoDB Local fica colado no seu teto enquanto a API sobra, o gargalo e o
armazenamento. Se os dois sobram, e o gerador ou a rede. Se so a API encosta no teto,
ai sim o gargalo e ela.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CONTAINERS = ("nexus-api", "nexus-dynamodb")


def amostrar(destino: list[dict[str, float]], parar: threading.Event) -> None:
    while not parar.is_set():
        try:
            saida = subprocess.run(
                [
                    "docker",
                    "stats",
                    "--no-stream",
                    "--format",
                    "{{.Name}} {{.CPUPerc}}",
                    *CONTAINERS,
                ],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        amostra: dict[str, float] = {}
        for linha in saida.strip().splitlines():
            partes = linha.split()
            if len(partes) == 2:
                amostra[partes[0]] = float(partes[1].rstrip("%"))
        if amostra:
            destino.append(amostra)
        time.sleep(1)


def cpu_do_gerador(destino: list[float], parar: threading.Event) -> None:
    """Amostra a CPU do processo Locust no host.

    O gerador e um processo Python, limitado pelo GIL a um nucleo. Se ele encosta em
    100%, o numero medido e o teto do gerador e nao diz nada sobre a plataforma. O
    aviso do proprio Locust nem sempre dispara, entao nao da para confiar so nele.
    """
    while not parar.is_set():
        try:
            saida = subprocess.run(
                ["ps", "-A", "-o", "%cpu,comm,args"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        total = 0.0
        for linha in saida.splitlines():
            if "locust" in linha and "tools/loadtest" not in linha and "ps -A" not in linha:
                try:
                    total += float(linha.split()[0])
                except (ValueError, IndexError):
                    continue
        if total:
            destino.append(total)
        time.sleep(1)


def resumir(amostras: list[dict[str, float]], nome: str, teto: float) -> dict[str, float]:
    valores = sorted(a[nome] for a in amostras if nome in a)
    if not valores:
        return {}
    meio = valores[len(valores) // 2]
    pico = valores[-1]
    return {
        "mediana_pct": round(meio, 1),
        "pico_pct": round(pico, 1),
        "teto_pct": teto,
        # Quanto do proprio teto o container usou na mediana. E a fracao que importa:
        # 180% num container de 2 CPUs e saturacao; 180% num de 4 nao e.
        "uso_do_teto_mediana": round(meio / teto, 2),
        "amostras": len(valores),
    }


def main() -> int:
    amostras: list[dict[str, float]] = []
    gerador: list[float] = []
    parar = threading.Event()
    coletor = threading.Thread(target=amostrar, args=(amostras, parar), daemon=True)
    coletor.start()
    coletor_gerador = threading.Thread(target=cpu_do_gerador, args=(gerador, parar), daemon=True)
    coletor_gerador.start()

    corrida = subprocess.run(
        [
            sys.executable,
            str(RAIZ / "tools" / "loadtest.py"),
            "--nome",
            "gargalo",
            "--usuarios",
            "200",
            "--taxa",
            "50",
            "--duracao",
            "60s",
            "--nota",
            "corrida instrumentada para atribuir o gargalo",
        ],
        check=False,
    )
    parar.set()
    coletor.join(timeout=5)
    coletor_gerador.join(timeout=5)

    # O teto vem do docker-compose: 2 CPUs por container, que o docker reporta como 200%.
    ordenado = sorted(gerador)
    relatorio = {
        "nexus-api": resumir(amostras, "nexus-api", 200.0),
        "nexus-dynamodb": resumir(amostras, "nexus-dynamodb", 200.0),
        # Um processo Python nao passa de ~100%: e um nucleo, por causa do GIL. O teto
        # declarado aqui e esse, nao o numero de nucleos da maquina.
        "locust-no-host": (
            {
                "mediana_pct": round(ordenado[len(ordenado) // 2], 1),
                "pico_pct": round(ordenado[-1], 1),
                "teto_pct": 100.0,
                "uso_do_teto_mediana": round(ordenado[len(ordenado) // 2] / 100.0, 2),
                "amostras": len(ordenado),
            }
            if ordenado
            else {}
        ),
    }
    destino = RAIZ / "docs" / "performance" / "runs" / "gargalo-cpu.json"
    destino.write_text(json.dumps(relatorio, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(relatorio, indent=2, ensure_ascii=False))
    return corrida.returncode


if __name__ == "__main__":
    raise SystemExit(main())
