"""Campanha de carga da Fase 7.

Executa a bateria inteira em condicoes comparaveis e grava um resultado por corrida.
O ponto nao e automatizar por automatizar: e que **cada corrida comece do mesmo
estado**. Sem isso, a segunda medicao herda o acervo da primeira e a diferenca entre
elas confunde duas causas — mais dados na tabela e mais carga — que sao exatamente o
que a campanha quer separar.

Quatro eixos, uma pergunta cada:

| Eixo | Pergunta |
|---|---|
| volume | A latencia degrada com o tamanho do acervo? |
| concorrencia | Onde a curva vira, e o que satura primeiro? |
| workers | O teto e do desenho ou do processo unico? |
| trilha | Quanto a observabilidade da Fase 6 custa ao que observa? |

Uso::

    .venv/bin/python tools/campanha.py --eixo volume
    .venv/bin/python tools/campanha.py --tudo
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PY_BIN = sys.executable
API = "http://localhost:8080"

#: Parametros fixos das corridas comparativas. Variar mais de uma coisa por vez
#: produziria diferencas que nao se sabe a quem atribuir.
USUARIOS_PADRAO = 50
TAXA_PADRAO = 25
DURACAO_PADRAO = "60s"
ACERVO_PADRAO = 1_000


def executar(comando: list[str], *, env: dict[str, str] | None = None) -> None:
    ambiente = None
    if env is not None:
        import os

        ambiente = {**os.environ, **env}
    resultado = subprocess.run(comando, env=ambiente, check=False)
    if resultado.returncode != 0:
        raise RuntimeError(f"falhou: {' '.join(comando)}")


def esperar_api(tentativas: int = 60) -> None:
    for _ in range(tentativas):
        try:
            with urllib.request.urlopen(f"{API}/health", timeout=3) as r:
                if r.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(2)
    raise RuntimeError("a API nao respondeu apos subir")


def reiniciar(*, workers: int = 1, trilha: bool = True) -> None:
    """Derruba tudo, **apaga os volumes** e sobe de novo.

    Apagar e o ponto: tabela e fila voltam vazias, e a corrida seguinte mede o que o
    seu proprio acervo provoca, nao o que sobrou da anterior.
    """
    print(f"\n  reiniciando: workers={workers} trilha={'on' if trilha else 'off'}", flush=True)
    executar(["docker", "compose", "down", "-v"])
    executar(
        ["docker", "compose", "up", "-d"],
        env={
            "NEXUS_API_WORKERS": str(workers),
            "NEXUS_TRAIL_ENABLED": "true" if trilha else "false",
        },
    )
    esperar_api()


def pre_carregar(quantidade: int) -> None:
    if quantidade <= 0:
        return
    print(f"  pre-carregando {quantidade} registros…", flush=True)
    executar(
        [
            PY_BIN,
            str(RAIZ / "tools" / "generator.py"),
            "--count",
            str(quantidade),
            "--duplicate-rate",
            "0.1",
            "--variant-rate",
            "0.2",
            "--post",
            "--seed",
            "707",
        ]
    )
    # Esvazia a fila antes de medir. Sem isso a corrida comecaria com o worker
    # devendo trabalho do pre-carregamento, e a profundidade medida no fim seria a
    # soma de duas coisas diferentes.
    drenar = ["python", "-m", "nexus.queue.worker", "--drain"]
    executar(["docker", "compose", "exec", "-T", "api", *drenar])


def corrida(
    nome: str, *, usuarios: int, duracao: str, acervo: int, nota: str, taxa: float = TAXA_PADRAO
) -> None:
    executar(
        [
            PY_BIN,
            str(RAIZ / "tools" / "loadtest.py"),
            "--nome",
            nome,
            "--usuarios",
            str(usuarios),
            "--taxa",
            str(taxa),
            "--duracao",
            duracao,
            "--acervo",
            str(acervo),
            "--nota",
            nota,
        ]
    )


# --------------------------------------------------------------------------- eixos


def eixo_volume() -> None:
    for acervo in (100, 1_000, 10_000):
        reiniciar()
        pre_carregar(acervo)
        corrida(
            f"volume-{acervo}",
            usuarios=USUARIOS_PADRAO,
            duracao=DURACAO_PADRAO,
            acervo=acervo,
            nota=f"acervo de {acervo} registros; carga fixa",
        )


def eixo_concorrencia() -> None:
    for usuarios in (10, 50, 200):
        reiniciar()
        pre_carregar(ACERVO_PADRAO)
        corrida(
            f"concorrencia-{usuarios}",
            usuarios=usuarios,
            duracao=DURACAO_PADRAO,
            acervo=ACERVO_PADRAO,
            taxa=min(usuarios, 50),
            nota=f"{usuarios} usuarios simultaneos; acervo fixo",
        )


def eixo_workers() -> None:
    for workers in (1, 4):
        reiniciar(workers=workers)
        pre_carregar(ACERVO_PADRAO)
        corrida(
            f"workers-{workers}",
            usuarios=200,
            duracao=DURACAO_PADRAO,
            acervo=ACERVO_PADRAO,
            taxa=50,
            nota=f"{workers} processo(s) uvicorn sob 200 usuarios",
        )


def eixo_trilha() -> None:
    for ligada in (True, False):
        reiniciar(trilha=ligada)
        pre_carregar(ACERVO_PADRAO)
        corrida(
            f"trilha-{'on' if ligada else 'off'}",
            usuarios=USUARIOS_PADRAO,
            duracao=DURACAO_PADRAO,
            acervo=ACERVO_PADRAO,
            nota=f"instrumentacao da Fase 6 {'ligada' if ligada else 'desligada'}",
        )


EIXOS = {
    "volume": eixo_volume,
    "concorrencia": eixo_concorrencia,
    "workers": eixo_workers,
    "trilha": eixo_trilha,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Campanha de carga da Fase 7.")
    parser.add_argument("--eixo", choices=sorted(EIXOS))
    parser.add_argument("--tudo", action="store_true")
    args = parser.parse_args(argv)

    if not args.tudo and not args.eixo:
        parser.error("informe --eixo ou --tudo")

    escolhidos = list(EIXOS) if args.tudo else [args.eixo]
    for nome in escolhidos:
        print(f"\n=== eixo: {nome} ===", flush=True)
        EIXOS[nome]()  # type: ignore[operator]

    # Deixa a stack no estado padrao: a campanha nao deve mudar o ambiente de
    # desenvolvimento de quem a executou.
    reiniciar()
    print("\ncampanha concluida. Resultados em docs/performance/runs/", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
