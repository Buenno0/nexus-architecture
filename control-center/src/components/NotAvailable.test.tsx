import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NotAvailable } from "./NotAvailable";

describe("NotAvailable", () => {
  it("explica em vez de mostrar numero", () => {
    render(
      <NotAvailable
        rotulo="workers ativos"
        explicacao="A execucao e sob demanda: o worker consome um lote e termina."
      />,
    );

    expect(screen.getByText("workers ativos")).toBeInTheDocument();
    expect(screen.getByText(/sob demanda/)).toBeInTheDocument();
    expect(screen.getByText("nao se aplica")).toBeInTheDocument();
  });

  it("nao renderiza digito nenhum", () => {
    // O ponto do componente: a ausencia de um numero nao pode virar um zero.
    const { container } = render(
      <NotAvailable rotulo="workers ativos" explicacao="Execucao sob demanda." />,
    );
    expect(container.textContent).not.toMatch(/\d/);
  });
});
