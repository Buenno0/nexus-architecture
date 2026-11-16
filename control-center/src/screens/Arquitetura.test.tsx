import { fireEvent, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Arquitetura } from "./Arquitetura";
import { renderizar } from "../test-utils";

function render() {
  renderizar(<Arquitetura />);
  fireEvent.click(screen.getByText("Quer entender como funciona por dentro?"));
}

describe("tela de arquitetura", () => {
  it("lista os cinco mecanismos na ordem da jornada", () => {
    render();
    const nomes = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent).filter((h) => h !== "Ingestion API");
    expect(nomes.slice(-5)).toEqual([
      "Idempotencia",
      "Transactional outbox",
      "Fila, retentativa e DLQ",
      "Resolucao de identidade",
      "Trilha",
    ]);
  });

  it("explica dependencias e limites do componente escolhido", () => {
    render();
    fireEvent.click(screen.getByRole("button", { name: "Observability" }));
    expect(screen.getByText(/camada transversal, nao servico separado/)).toBeInTheDocument();
    expect(screen.getByText(/Trilha best-effort pode ter lacunas/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "ADR-010 ↗" })).toHaveAttribute("href", expect.stringContaining("ADR-010-observabilidade.md"));
  });

  it("cada desenho tem descricao textual", () => {
    // SVG sem alternativa textual e decoracao para quem usa leitor de tela, e estes
    // desenhos carregam a explicacao, nao enfeite.
    render();
    // O mapa da jornada, o fluxograma anterior e os cinco mecanismos.
    const desenhos = screen.getAllByRole("img");
    expect(desenhos).toHaveLength(7);
    for (const d of desenhos) {
      expect(d.getAttribute("aria-label")?.length ?? 0).toBeGreaterThan(20);
    }
  });

  it("nao depende de nenhuma chamada a API", () => {
    // De proposito: e a unica tela que funciona com a plataforma fora do ar, e e
    // justamente ela que explica o que o visitante deveria estar vendo.
    render();
    expect(screen.getByText(/Uma mesma pessoa/)).toBeInTheDocument();
  });
});
