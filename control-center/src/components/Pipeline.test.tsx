import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Pipeline } from "./Pipeline";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

/**
 * Avanca `passos` etapas.
 *
 * Um `act` por passo, de proposito: o efeito que agenda o proximo temporizador so roda
 * quando o `act` descarrega, entao um unico `advanceTimersByTime` longo avanca uma
 * etapa so, por mais tempo que se passe nele.
 */
function avancarPassos(passos: number) {
  for (let i = 0; i < passos; i += 1) {
    act(() => {
      vi.advanceTimersByTime(5_000);
    });
  }
}

describe("pipeline interativo", () => {
  it("comeca parado, sem marco e sem etapa ativa", () => {
    render(<Pipeline />);
    expect(screen.getByText(/Aperte um dos botoes acima/)).toBeInTheDocument();
    expect(screen.getByText(/Nenhum marco ainda/)).toBeInTheDocument();
  });

  it("declara que nao le o sistema", () => {
    // O aviso nao e decorativo: animacao que parece medicao seria dado ficticio
    // apresentado como real, que e o que a secao 7 do projeto proibe.
    render(<Pipeline />);
    expect(screen.getByText(/nao uma leitura do sistema/)).toBeInTheDocument();
  });

  it("grava os marcos na ordem, com o processo que emitiu cada um", () => {
    render(<Pipeline />);
    act(() => {
      screen.getByText("Executar uma observacao").click();
    });

    expect(screen.getByText("accepted")).toBeInTheDocument();
    avancarPassos(3);
    expect(screen.getByText("published")).toBeInTheDocument();
    avancarPassos(3);

    const marcos = screen.getAllByText(/accepted|published|consumed|resolved/);
    expect(marcos.map((m) => m.textContent?.replace(/api|worker|fila/g, ""))).toEqual([
      "accepted",
      "published",
      "consumed",
      "resolved",
    ]);
  });

  it("o caminho de falha termina na DLQ, nao em resolved", () => {
    render(<Pipeline />);
    act(() => {
      screen.getByText("Simular uma falha").click();
    });
    avancarPassos(8);

    expect(screen.getByText("dead_lettered")).toBeInTheDocument();
    expect(screen.queryByText("resolved")).not.toBeInTheDocument();
  });
});
