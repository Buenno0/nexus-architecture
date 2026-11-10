import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { OriginBadge } from "./OriginBadge";
import type { Origem } from "../api/types";

describe("OriginBadge", () => {
  it.each<[Origem, string]>([
    ["persistido", "persistido"],
    ["processo", "processo"],
    ["sessao", "sessao"],
  ])("rotula a origem %s", (origem, texto) => {
    render(<OriginBadge origem={origem} />);
    expect(screen.getByText(texto)).toBeInTheDocument();
  });

  it("explica a garantia de cada origem ao passar o mouse", () => {
    // O rotulo sozinho nao basta: quem olha precisa saber o que ele significa.
    const { rerender } = render(<OriginBadge origem="processo" />);
    expect(screen.getByText("processo")).toHaveAttribute(
      "title",
      expect.stringContaining("Zera a cada reinicio"),
    );

    rerender(<OriginBadge origem="sessao" />);
    expect(screen.getByText("sessao")).toHaveAttribute(
      "title",
      expect.stringContaining("Recarregar zera"),
    );
  });
});
