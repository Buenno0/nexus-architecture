import { describe, expect, it } from "vitest";

import { HistoricoDeSessao } from "./history";

describe("HistoricoDeSessao", () => {
  it("guarda os pontos registrados", () => {
    const historico = new HistoricoDeSessao();
    historico.registrar({ req: 1 }, 1000);
    historico.registrar({ req: 2 }, 2000);

    expect(historico.tamanho).toBe(2);
    expect(historico.listar()[0]).toEqual({ instante: 1000, req: 1 });
  });

  it("respeita o limite descartando o mais antigo", () => {
    const historico = new HistoricoDeSessao(3);
    for (let i = 0; i < 10; i += 1) historico.registrar({ v: i }, i);

    expect(historico.tamanho).toBe(3);
    expect(historico.listar().map((p) => p.v)).toEqual([7, 8, 9]);
  });

  it("calcula a janela coberta", () => {
    const historico = new HistoricoDeSessao();
    historico.registrar({ v: 1 }, 0);
    historico.registrar({ v: 2 }, 30_000);
    expect(historico.janelaSegundos).toBe(30);
  });

  it("janela e zero com menos de dois pontos", () => {
    const historico = new HistoricoDeSessao();
    expect(historico.janelaSegundos).toBe(0);
    historico.registrar({ v: 1 }, 0);
    expect(historico.janelaSegundos).toBe(0);
  });

  it("limpar esvazia", () => {
    const historico = new HistoricoDeSessao();
    historico.registrar({ v: 1 }, 0);
    historico.limpar();
    expect(historico.tamanho).toBe(0);
  });

  it("aceita varias series no mesmo ponto", () => {
    const historico = new HistoricoDeSessao();
    historico.registrar({ pendentes: 5, dlq: 1 }, 1000);
    expect(historico.listar()[0]).toEqual({ instante: 1000, pendentes: 5, dlq: 1 });
  });
});
