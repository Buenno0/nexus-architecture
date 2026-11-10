import { describe, expect, it } from "vitest";

import { descreverCobertura, paraPontos } from "./persisted";
import type { Series } from "../api/types";

const BASE: Series = {
  metric: "platform",
  origin: "persistido",
  interval_seconds: 15,
  window_minutes: 60,
  gaps: 0,
  points: [],
};

describe("paraPontos", () => {
  it("traduz os nomes gravados para os rotulos do grafico", () => {
    const pontos = paraPontos(
      [{ bucket: "2026-11-10T12:00:00+00:00", values: { queue_pending: 3 } }],
      { queue_pending: "aguardando" },
    );

    expect(pontos[0]?.aguardando).toBe(3);
    expect(pontos[0]?.instante).toBe(Date.parse("2026-11-10T12:00:00+00:00"));
  });

  it("omite a chave ausente em vez de gravar zero", () => {
    /* Zero e um numero; "nao medido" nao e. O grafico interrompe a linha, que e a
       representacao correta de um balde em que a fonte estava indisponivel. */
    const pontos = paraPontos(
      [{ bucket: "2026-11-10T12:00:00+00:00", values: {} }],
      { queue_pending: "aguardando" },
    );

    expect("aguardando" in (pontos[0] ?? {})).toBe(false);
  });
});

describe("descreverCobertura", () => {
  it("explica a janela sem amostra em vez de ficar em branco", () => {
    const texto = descreverCobertura({ ...BASE, gaps: 240 });
    expect(texto).toMatch(/oportunista/);
  });

  it("informa a cobertura e o que os baldes vazios significam", () => {
    const texto = descreverCobertura({
      ...BASE,
      gaps: 120,
      points: [{ bucket: "2026-11-10T12:00:00+00:00", values: { queue_pending: 1 } }],
    });

    expect(texto).toMatch(/1 amostras/);
    expect(texto).toMatch(/nao foram medidos/);
    expect(texto).toMatch(/nao como zero/);
  });

  it("nao menciona buracos quando a janela esta completa", () => {
    const texto = descreverCobertura({
      ...BASE,
      points: [{ bucket: "2026-11-10T12:00:00+00:00", values: {} }],
    });

    expect(texto).not.toMatch(/nao foram medidos/);
  });
});
