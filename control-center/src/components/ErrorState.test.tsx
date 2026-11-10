import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ErrorState } from "./ErrorState";
import { NexusApiError } from "../api/client";

describe("ErrorState", () => {
  it("mostra o correlation_id, que liga a tela ao log do servidor", () => {
    const erro = new NexusApiError(503, {
      code: "persistence_unavailable",
      message: "Falha ao acessar a camada de persistencia",
      correlation_id: "abc123",
    });

    render(<ErrorState erro={erro} />);

    expect(screen.getByText("503 persistence_unavailable")).toBeInTheDocument();
    expect(screen.getByText("abc123")).toBeInTheDocument();
  });

  it("orienta quando a API nao respondeu", () => {
    render(<ErrorState erro={new TypeError("Failed to fetch")} />);
    expect(screen.getByText("Sem resposta da API")).toBeInTheDocument();
    expect(screen.getByText(/make up/)).toBeInTheDocument();
  });

  it("usa papel de alerta para leitores de tela", () => {
    render(<ErrorState erro={new Error("x")} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("chama a funcao de nova tentativa", async () => {
    const tentar = vi.fn();
    render(<ErrorState erro={new Error("x")} onTentarNovamente={tentar} />);
    await userEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
    expect(tentar).toHaveBeenCalledOnce();
  });
});
