import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "./provider";
import { Login } from "../screens/Login";

function Sonda() {
  const { autenticado, modo, usuario, sair } = useAuth();
  return (
    <div>
      <span data-testid="modo">{modo}</span>
      <span data-testid="autenticado">{String(autenticado)}</span>
      <span data-testid="usuario">{usuario ?? "—"}</span>
      <button type="button" onClick={sair}>
        sair
      </button>
    </div>
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  // Guardado: um erro aqui impediria a limpeza de DOM do Testing Library, e os
  // testes seguintes encontrariam elementos duplicados da renderizacao anterior.
  globalThis.localStorage?.clear();
  globalThis.sessionStorage?.clear();
});

describe("modo none", () => {
  it("considera autenticado sem login", () => {
    render(
      <AuthProvider modo="none">
        <Sonda />
      </AuthProvider>,
    );
    expect(screen.getByTestId("modo")).toHaveTextContent("none");
    expect(screen.getByTestId("autenticado")).toHaveTextContent("true");
    expect(screen.getByTestId("usuario")).toHaveTextContent("—");
  });
});

describe("modo cognito", () => {
  it("comeca nao autenticado", () => {
    render(
      <AuthProvider modo="cognito">
        <Sonda />
      </AuthProvider>,
    );
    expect(screen.getByTestId("autenticado")).toHaveTextContent("false");
  });

  it("sair nao quebra quando nao ha sessao", async () => {
    render(
      <AuthProvider modo="cognito">
        <Sonda />
      </AuthProvider>,
    );
    await userEvent.click(screen.getByRole("button", { name: "sair" }));
    expect(screen.getByTestId("autenticado")).toHaveTextContent("false");
  });
});

describe("armazenamento do token", () => {
  it("nao escreve em localStorage nem em sessionStorage", () => {
    // Em localStorage o token sobrevive ao fechamento da aba e fica legivel por
    // qualquer script da pagina. O custo de manter em memoria e um login por recarga.
    render(
      <AuthProvider modo="cognito">
        <Sonda />
      </AuthProvider>,
    );
    expect(globalThis.localStorage?.length ?? 0).toBe(0);
    expect(globalThis.sessionStorage?.length ?? 0).toBe(0);
  });
});

describe("useAuth", () => {
  it("exige o provedor acima na arvore", () => {
    // Sem provedor, o erro precisa ser imediato e claro — nao um undefined que
    // quebra paginas adiante.
    const silencio = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(() => render(<Sonda />)).toThrow(/AuthProvider/);
    silencio.mockRestore();
  });
});

describe("tela de login", () => {
  it("pede usuario e senha", async () => {
    render(
      <AuthProvider modo="cognito">
        <Login />
      </AuthProvider>,
    );
    const usuario = screen.getByLabelText(/Usuario/);
    expect(usuario).toBeInTheDocument();
    expect(screen.getByLabelText(/Senha/)).toBeInTheDocument();

    await userEvent.type(usuario, "operador");
    expect(usuario).toHaveValue("operador");
  });

  it("explica por que o login aparece", () => {
    render(
      <AuthProvider modo="cognito">
        <Login />
      </AuthProvider>,
    );
    expect(screen.getByText(/exige autenticacao/)).toBeInTheDocument();
  });
});
