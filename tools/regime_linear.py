"""Medicao no regime nao saturado — Fase 7.

As repeticoes sob 200 usuarios deram coeficiente de variacao de 10% a 40%. Nesse
regime quase todo o tempo de resposta e espera em fila, e fila amplifica qualquer
perturbacao do ambiente — outro processo no laptop, o escalonador do Docker, o
coletor de lixo do JVM. Medir o **custo de um trabalho** ali e tentar pesar uma carta
dentro de um elevador em movimento.

Este script mede onde o sistema nao esta saturado: 10 usuarios, onde a campanha
mostrou P95 de 31 ms. A latencia ali reflete o trabalho que a requisicao faz, nao
quanto tempo ela esperou pela anterior.

Duas perguntas, com repeticao:

1. **Quanto custa a trilha da Fase 6?** Com e sem, no caminho de ingestao.
2. **De onde vem o custo fixo de uma requisicao?** O cenario `replay` sai cedo com um
   unico `GetItem`; comparar o teto dele com o do caminho completo separa "custo de
   atender" de "custo de ingerir".
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from campanha import ACERVO_PADRAO, corrida, pre_carregar, reiniciar

REPETICOES = 3
USUARIOS = 10


def main() -> int:
    # --- 1. custo da trilha, fora da saturacao
    for i in range(1, REPETICOES + 1):
        for ligada in (True, False):
            reiniciar(trilha=ligada)
            pre_carregar(ACERVO_PADRAO)
            corrida(
                f"linear-trilha-{'on' if ligada else 'off'}-{i}",
                usuarios=USUARIOS,
                duracao="45s",
                acervo=ACERVO_PADRAO,
                taxa=10,
                nota=f"regime linear, repeticao {i}, trilha {'on' if ligada else 'off'}",
            )

    # --- 2. capacidade por caminho, sob saturacao e com um cenario de cada vez
    for cenario in ("replay", "novo"):
        os.environ["NEXUS_LOAD_SCENARIO"] = cenario
        reiniciar()
        pre_carregar(ACERVO_PADRAO)
        corrida(
            f"capacidade-{cenario}",
            usuarios=200,
            duracao="45s",
            acervo=ACERVO_PADRAO,
            taxa=50,
            nota=f"somente o cenario {cenario}, para medir o teto daquele caminho",
        )
    os.environ.pop("NEXUS_LOAD_SCENARIO", None)

    reiniciar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
