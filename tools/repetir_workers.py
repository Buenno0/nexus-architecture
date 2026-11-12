"""Repeticao controlada do eixo de workers — Fase 7.

A primeira tentativa comparou 1 e 4 processos com uma corrida cada e concluiu que 4
eram piores. A segunda, controlada por CPU, concluiu o contrario. A terceira — tres
repeticoes alternadas sem reiniciar — mostrou por que: desvio padrao de 23% a 40% da
media, e uma queda monotonica dentro de cada serie conforme o acervo crescia.

Alternar nao resolveu porque a tabela cresce ao longo das seis corridas: o w4 rodou
sempre com um acervo um pouco maior. Este script zera e pre-carrega **antes de cada
corrida**, que e a unica forma de a comparacao significar alguma coisa.

Tres repeticoes por configuracao. Nao e muito; e o suficiente para dizer se a
diferenca sobrevive a dispersao, que e a pergunta.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from campanha import ACERVO_PADRAO, corrida, pre_carregar, reiniciar

REPETICOES = 3


def main() -> int:
    for i in range(1, REPETICOES + 1):
        for workers in (1, 4):
            reiniciar(workers=workers)
            pre_carregar(ACERVO_PADRAO)
            corrida(
                f"ctrl-w{workers}-{i}",
                usuarios=200,
                duracao="45s",
                acervo=ACERVO_PADRAO,
                taxa=50,
                nota=f"repeticao {i} com {workers} processo(s), estado zerado antes",
            )
    reiniciar()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
