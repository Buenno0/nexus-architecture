import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Pipeline } from "./Pipeline";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

/** Um `act` por passo: o efeito que agenda o proximo so roda quando o `act` descarrega. */
function avancar(passos: number) {
  for (let i = 0; i < passos; i += 1) {
    act(() => {
      vi.advanceTimersByTime(5_000);
    });
  }
}

function tocar(nome: RegExp) {
  act(() => {
    screen.getByRole("button", { name: nome }).click();
  });
}

describe("percurso de uma requisicao", () => {
  it("comeca parado, convidando a acao", () => {
    render(<Pipeline />);
    expect(screen.getByText(/Aperte um dos botoes acima/)).toBeInTheDocument();
  });

  it("tem alternativa textual carregando a mesma afirmacao da figura", () => {
    render(<Pipeline />);
    const figura = screen.getByRole("img");
    expect(figura.getAttribute("aria-label")).toMatch(/transacao/);
    expect(figura.getAttribute("aria-label")).toMatch(/DLQ/);
  });

  it("a requisicao sai do cliente e chega ao vinculo", () => {
    render(<Pipeline />);
    tocar(/Enviar uma requisicao/);

    expect(screen.getByText(/A requisicao sai do cliente/)).toBeInTheDocument();
    avancar(8);
    expect(screen.getByText(/Vinculo gravado/)).toBeInTheDocument();
  });

  it("o caminho de falha termina na fila, nao perdido", () => {
    // O ponto da DLQ nao e a mensagem morrer: e ela ficar recuperavel.
    render(<Pipeline />);
    tocar(/Com falha no processamento/);
    avancar(12);

    expect(screen.getByText(/Redrive: de volta a fila/)).toBeInTheDocument();
  });

  it("os botoes ficam travados enquanto o percurso corre", () => {
    render(<Pipeline />);
    tocar(/Enviar uma requisicao/);

    expect(screen.getByRole("button", { name: /em curso/ })).toBeDisabled();
  });

  it("toda aresta tem rotulo: seta sem rotulo e 'relacionado de algum jeito'", () => {
    const { container } = render(<Pipeline />);
    expect(container.querySelectorAll(".flux__rotulo")).toHaveLength(
      container.querySelectorAll(".flux__aresta").length,
    );
  });

  it("declara que nao le o sistema", () => {
    render(<Pipeline />);
    expect(screen.getByText(/nao le o sistema/)).toBeInTheDocument();
  });
});
