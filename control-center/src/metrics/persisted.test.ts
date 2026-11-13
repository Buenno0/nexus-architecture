import { describe, expect, it } from "vitest";

import { descreverCobertura, descreverGraficoVazio, paraPontos } from "./persisted";
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
      points: [
        { bucket: "2026-11-10T12:00:00+00:00", values: { queue_pending: 1 } },
        { bucket: "2026-11-10T12:00:15+00:00", values: { queue_pending: 2 } },
      ],
    });

    expect(texto).toMatch(/2 amostras/);
    expect(texto).toMatch(/nao foram medidos/);
    expect(texto).toMatch(/nao como zero/);
  });

  it("nao anuncia cobertura com uma amostra so, porque o grafico nao desenha", () => {
    // A versao anterior dizia "1 amostras ... (0% da janela)" enquanto o grafico logo
    // abaixo dizia "sem amostras na janela" — duas afirmacoes opostas na mesma caixa.
    const serie = {
      ...BASE,
      gaps: 239,
      points: [{ bucket: "2026-11-10T12:00:00+00:00", values: { queue_pending: 1 } }],
    };

    expect(descreverCobertura(serie)).toMatch(/Uma amostra/);
    expect(descreverCobertura(serie)).toMatch(/a partir da segunda/);
    expect(descreverCobertura(serie)).not.toMatch(/amostras/);
  });

  it("a legenda e o texto do grafico nunca se contradizem", () => {
    const umaSo = {
      ...BASE,
      gaps: 239,
      points: [{ bucket: "2026-11-10T12:00:00+00:00", values: { queue_pending: 1 } }],
    };

    expect(descreverGraficoVazio(umaSo)).toMatch(/Uma amostra so/);
    expect(descreverGraficoVazio({ ...BASE, gaps: 240 })).toMatch(/Sem amostras/);
  });

  it("concorda o singular tambem nos baldes", () => {
    const texto = descreverCobertura({
      ...BASE,
      gaps: 1,
      points: [
        { bucket: "2026-11-10T12:00:00+00:00", values: { queue_pending: 1 } },
        { bucket: "2026-11-10T12:00:15+00:00", values: { queue_pending: 2 } },
      ],
    });

    expect(texto).toMatch(/O balde restante nao foi medido/);
  });

  it("nao menciona buracos quando a janela esta completa", () => {
    const texto = descreverCobertura({
      ...BASE,
      points: [{ bucket: "2026-11-10T12:00:00+00:00", values: {} }],
    });

    expect(texto).not.toMatch(/nao foram medidos/);
  });
});

describe("buracos na serie", () => {
  const mapa = { queue_pending: "aguardando" };

  it("insere um ponto vazio onde faltou balde", () => {
    /* Sem isso, dez minutos sem medicao virariam um segmento reto entre dois
       instantes distantes, e o grafico afirmaria estabilidade onde houve cegueira. */
    const pontos = paraPontos(
      [
        { bucket: "2026-11-10T12:00:00+00:00", values: { queue_pending: 3 } },
        { bucket: "2026-11-10T12:10:00+00:00", values: { queue_pending: 9 } },
      ],
      mapa,
      15,
    );

    expect(pontos).toHaveLength(3);
    expect(pontos[1]?.aguardando).toBeUndefined();
    expect(pontos[1]?.instante).toBe(Date.parse("2026-11-10T12:00:15+00:00"));
  });

  it("baldes consecutivos nao ganham ponto vazio", () => {
    const pontos = paraPontos(
      [
        { bucket: "2026-11-10T12:00:00+00:00", values: { queue_pending: 3 } },
        { bucket: "2026-11-10T12:00:15+00:00", values: { queue_pending: 4 } },
      ],
      mapa,
      15,
    );

    expect(pontos).toHaveLength(2);
  });

  it("sem intervalo informado nao inventa buracos", () => {
    const pontos = paraPontos(
      [
        { bucket: "2026-11-10T12:00:00+00:00", values: { queue_pending: 3 } },
        { bucket: "2026-11-10T12:10:00+00:00", values: { queue_pending: 9 } },
      ],
      mapa,
    );

    expect(pontos).toHaveLength(2);
  });
});
