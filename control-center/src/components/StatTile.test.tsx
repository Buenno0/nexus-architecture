import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StatTile, formatarValor } from "./StatTile";

describe("formatarValor", () => {
  it("formata inteiro com separador", () => {
    expect(formatarValor(1234567)).toBe("1.234.567");
  });

  it("limita casas decimais", () => {
    expect(formatarValor(3.14159)).toBe("3,14");
  });

  it("passa texto adiante", () => {
    expect(formatarValor("implemented")).toBe("implemented");
  });

  it.each([null, undefined, NaN, Infinity])("devolve travessao para %s", (valor) => {
    expect(formatarValor(valor as number | null)).toBe("—");
  });
});

describe("StatTile", () => {
  it("exibe o valor e a unidade", () => {
    render(<StatTile rotulo="latencia" valor={42} unidade="ms" origem="processo" />);
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("ms")).toBeInTheDocument();
  });

  it("exibe travessao quando nao ha valor, nunca zero", () => {
    // A regra da secao 7: zero no lugar de "nao sei" e uma afirmacao falsa.
    render(<StatTile rotulo="pendentes" valor={null} origem="persistido" />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("nao exibe unidade quando nao ha valor", () => {
    render(<StatTile rotulo="latencia" valor={null} unidade="ms" origem="processo" />);
    expect(screen.queryByText("ms")).not.toBeInTheDocument();
  });

  it("distingue zero real de ausencia", () => {
    render(<StatTile rotulo="dlq" valor={0} origem="persistido" />);
    expect(screen.getByText("0")).toBeInTheDocument();
    expect(screen.queryByText("—")).not.toBeInTheDocument();
  });

  it("sempre mostra o rotulo de origem", () => {
    render(<StatTile rotulo="x" valor={1} origem="sessao" />);
    expect(screen.getByText("sessao")).toBeInTheDocument();
  });

  it("mostra reticencias enquanto carrega", () => {
    render(<StatTile rotulo="x" valor={null} origem="processo" carregando />);
    expect(screen.getByText("…")).toBeInTheDocument();
  });
});
