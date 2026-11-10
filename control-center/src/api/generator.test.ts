import { describe, expect, it } from "vitest";

import { montarLote } from "./generator";

describe("montarLote", () => {
  it("gera a quantidade pedida", () => {
    expect(montarLote(50, "teste", 0.2, 0.2)).toHaveLength(50);
  });

  it("sem duplicatas nem variantes, cada registro e uma entidade", () => {
    const lote = montarLote(30, "teste", 0, 0);
    expect(new Set(lote.map((r) => r.entidade)).size).toBe(30);
  });

  it("duplicatas e variantes herdam a entidade do original", () => {
    // E isso que torna o lote um gabarito: o resolvedor pode ser medido contra ele.
    const lote = montarLote(200, "teste", 0.3, 0.3);
    const entidades = new Set(lote.map((r) => r.entidade));
    expect(entidades.size).toBeLessThan(lote.length);
  });

  it("duplicata tem payload identico ao original", () => {
    const lote = montarLote(200, "teste", 0.9, 0);
    const porEntidade = new Map<number, Record<string, unknown>[]>();
    for (const r of lote) {
      const lista = porEntidade.get(r.entidade) ?? [];
      lista.push(r.payload);
      porEntidade.set(r.entidade, lista);
    }
    const grupo = [...porEntidade.values()].find((g) => g.length > 1);
    expect(grupo).toBeDefined();
    expect(JSON.stringify(grupo?.[0])).toBe(JSON.stringify(grupo?.[1]));
  });

  it("variante difere do original mas mantem a entidade", () => {
    const lote = montarLote(400, "teste", 0, 0.9);
    const porEntidade = new Map<number, Record<string, unknown>[]>();
    for (const r of lote) {
      const lista = porEntidade.get(r.entidade) ?? [];
      lista.push(r.payload);
      porEntidade.set(r.entidade, lista);
    }
    const grupos = [...porEntidade.values()].filter((g) => g.length > 1);
    expect(grupos.length).toBeGreaterThan(0);

    // Ao menos uma variante precisa diferir; se todas fossem iguais, a demonstracao
    // seria trivial e nao exercitaria a resolucao.
    const alguemDiferente = grupos.some((g) =>
      g.some((p) => JSON.stringify(p) !== JSON.stringify(g[0])),
    );
    expect(alguemDiferente).toBe(true);
  });

  it("todo registro tem os campos que a API exige", () => {
    for (const r of montarLote(20, "teste", 0, 0)) {
      expect(r.payload.source).toBe("teste");
      expect(typeof r.payload.full_name).toBe("string");
      expect(String(r.payload.email)).toMatch(/@/);
    }
  });

  it("e-mail nao leva acento nem espaco", () => {
    // Enderecos invalidos seriam recusados com 422 e o lote inteiro falharia por
    // defeito do gerador, nao da plataforma.
    for (const r of montarLote(100, "teste", 0, 0)) {
      expect(String(r.payload.email)).toMatch(/^[a-z0-9.@-]+$/);
    }
  });

  it("lote vazio e valido", () => {
    expect(montarLote(0, "teste", 0.5, 0.5)).toEqual([]);
  });
});
