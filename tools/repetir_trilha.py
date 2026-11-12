"""Repeticao controlada do eixo da trilha — Fase 7.

A campanha mediu 147 req/s sem trilha contra 128 com — uma diferenca de 13%. Depois de
descobrir que a dispersao entre corridas chega a 23%, essa diferenca deixou de ser
conclusiva: pode ser o custo da instrumentacao ou pode ser ruido.

A latencia mediana conta outra historia — 11 ms contra 21 ms, quase o dobro — e e um
efeito grande demais para ruido. Mas "grande demais" tambem e intuicao, e a Fase 7
existe justamente para parar de decidir assim.

Tres repeticoes de cada lado, com estado zerado antes de cada corrida. A carga aqui e
de 50 usuarios, nao 200: o objetivo e medir o custo da trilha no caminho de ingestao,
nao sob saturacao, onde tudo vira fila e a diferenca some no enfileiramento.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from campanha import ACERVO_PADRAO, corrida, pre_carregar, reiniciar

REPETICOES = 3


def main() -> int:
    for i in range(1, REPETICOES + 1):
        for ligada in (True, False):
            reiniciar(trilha=ligada)
            pre_carregar(ACERVO_PADRAO)
            corrida(
                f"ctrl-trilha-{'on' if ligada else 'off'}-{i}",
                usuarios=50,
                duracao="45s",
                acervo=ACERVO_PADRAO,
                taxa=25,
                nota=f"repeticao {i}, trilha {'ligada' if ligada else 'desligada'}",
            )
    reiniciar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
