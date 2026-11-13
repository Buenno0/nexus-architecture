import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Arquitetura } from "./Arquitetura";

describe("tela de arquitetura", () => {
  it("lista os cinco mecanismos na ordem da jornada", () => {
    render(<Arquitetura />);
    const nomes = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    expect(nomes).toEqual([
      "Idempotencia",
      "Transactional outbox",
      "Fila, retentativa e DLQ",
      "Resolucao de identidade",
      "Trilha",
    ]);
  });

  it("cada desenho tem descricao textual", () => {
    // SVG sem alternativa textual e decoracao para quem usa leitor de tela, e estes
    // desenhos carregam a explicacao, nao enfeite.
    render(<Arquitetura />);
    // Seis: o fluxograma animado no topo, mais um por mecanismo.
    const desenhos = screen.getAllByRole("img");
    expect(desenhos).toHaveLength(6);
    for (const d of desenhos) {
      expect(d.getAttribute("aria-label")?.length ?? 0).toBeGreaterThan(20);
    }
  });

  it("nao depende de nenhuma chamada a API", () => {
    // De proposito: e a unica tela que funciona com a plataforma fora do ar, e e
    // justamente ela que explica o que o visitante deveria estar vendo.
    render(<Arquitetura />);
    expect(screen.getByText(/Como uma observacao atravessa o Nexus/)).toBeInTheDocument();
  });
});
