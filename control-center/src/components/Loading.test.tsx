import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Loading } from "./Loading";

describe("Loading", () => {
  it("anuncia o carregamento a leitores de tela", () => {
    render(<Loading />);
    expect(screen.getByText("carregando…")).toHaveAttribute("aria-busy", "true");
  });

  it("aceita texto proprio", () => {
    render(<Loading texto="consultando a fila…" />);
    expect(screen.getByText("consultando a fila…")).toBeInTheDocument();
  });
});
