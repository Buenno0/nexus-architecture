import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderizar } from "../test-utils";
import { Decisoes, Experimentos, Infraestrutura } from "./EngineeringLab";

afterEach(() => vi.unstubAllGlobals());

describe("fontes do laboratorio", () => {
  it("exibe repeticoes reais e identifica as corridas descartadas", () => {
    render(<Experimentos />);
    expect(screen.getByRole("button", { name: "ctrl-w1-1" })).toBeInTheDocument();
    expect(screen.getByText("63,61 req/s")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Conjunto de corridas"), { target: { value: "inconclusivas" } });
    expect(screen.getByText(/Inconclusiva ou descartada/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "capacidade-replay" })).toBeInTheDocument();
  });

  it("navega entre ADRs usando o texto e a fonte versionados", () => {
    render(<Decisoes />);
    const indice = screen.getByRole("navigation", { name: "Decisoes de arquitetura" });
    fireEvent.click(within(indice).getByRole("button", { name: /ADR-011/ }));
    expect(screen.getByText(/A credencial de convidado esta no bundle publico/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Abrir fonte/ })).toHaveAttribute("href", expect.stringContaining("ADR-011-demonstracao-somente-leitura.md"));
  });

  it("mostra indisponibilidade do CI sem inventar resultado", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("sem rede")));
    renderizar(<Infraestrutura />);
    expect(await screen.findByText(/Estado do CI indisponivel/)).toBeInTheDocument();
    expect(await screen.findByText(/API indisponivel/)).toBeInTheDocument();
  });
});
