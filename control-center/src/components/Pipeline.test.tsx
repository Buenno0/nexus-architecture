import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { Pipeline } from "./Pipeline";

describe("fluxograma da plataforma", () => {
  it("tem alternativa textual carregando a mesma afirmacao da figura", () => {
    // SVG sem nome acessivel e decoracao para quem usa leitor de tela — e este
    // desenho carrega o mecanismo, nao enfeite.
    render(<Pipeline />);
    const figura = screen.getByRole("img");
    expect(figura.getAttribute("aria-label")).toMatch(/transacao/);
    expect(figura.getAttribute("aria-label")).toMatch(/DLQ/);
  });

  it("o ramo de falha comeca apagado e so acende quando pedido", async () => {
    // Desenhar os dois caminhos com o mesmo peso diria que falhar e tao comum
    // quanto dar certo.
    const { container } = render(<Pipeline />);
    expect(container.querySelector(".flux")).not.toHaveClass("flux--com-falha");

    await userEvent.click(screen.getByRole("button", { name: /Mostrar o caminho de falha/ }));

    expect(container.querySelector(".flux")).toHaveClass("flux--com-falha");
  });

  it("declara que nao le o sistema", () => {
    render(<Pipeline />);
    expect(screen.getByText(/nao le o sistema/)).toBeInTheDocument();
  });

  it("toda aresta tem rotulo: seta sem rotulo e 'relacionado de algum jeito'", () => {
    const { container } = render(<Pipeline />);
    const arestas = container.querySelectorAll(".flux__aresta");
    const rotulos = container.querySelectorAll(".flux__rotulo");
    expect(arestas.length).toBeGreaterThan(0);
    expect(rotulos).toHaveLength(arestas.length);
  });

  it("a espera na fila esta no desenho, nao so no texto", () => {
    // keyPoints "0;0;1" e a pausa antes do movimento: a mensagem publicada que
    // ainda nao foi consumida.
    const { container } = render(<Pipeline />);
    const pausas = container.querySelectorAll('animateMotion[keyPoints="0;0;1"]');
    expect(pausas).toHaveLength(1);
  });
});
