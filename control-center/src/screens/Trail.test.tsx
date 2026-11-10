import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Trail } from "./Trail";
import { mockarApi, renderizar, trilhaFalsa } from "../test-utils";

const API = {
  "/v1/records": { items: [{ record_id: "01TESTE" }], next_cursor: null },
  "/v1/observability/trail/01TESTE": trilhaFalsa,
  "/v1/observability/trail/01VAZIO": {
    record_id: "01VAZIO",
    events: [],
    total_ms: null,
    services: [],
  },
};

afterEach(() => vi.unstubAllGlobals());

async function consultar(id: string) {
  const usuario = userEvent.setup();
  await usuario.type(screen.getByLabelText("record_id"), id);
  await usuario.click(screen.getByRole("button", { name: "Consultar" }));
}

describe("Trail", () => {
  it("nao consulta nada antes de receber um record_id", () => {
    mockarApi(API);
    renderizar(<Trail />);

    expect(screen.getByText("Nenhum registro consultado")).toBeInTheDocument();
  });

  it("mostra os marcos em ordem", async () => {
    mockarApi(API);
    renderizar(<Trail />);
    await consultar("01TESTE");

    await screen.findByText("aceito");
    const marcos = screen.getAllByText(/^(aceito|publicado|consumido|resolvido)$/);
    expect(marcos.map((m) => m.textContent)).toEqual([
      "aceito",
      "publicado",
      "consumido",
      "resolvido",
    ]);
  });

  it("mostra os dois processos que contribuiram", async () => {
    /* E o ponto da fase: ate aqui a metade do worker so existia no terminal de quem
       rodou o comando, e a trilha era irrecuperavel. */
    mockarApi(API);
    renderizar(<Trail />);
    await consultar("01TESTE");

    expect(await screen.findByText("api, worker")).toBeInTheDocument();
  });

  it("mostra o delta que localiza o gargalo", async () => {
    mockarApi(API);
    renderizar(<Trail />);
    await consultar("01TESTE");

    await screen.findByText("consumido");
    expect(screen.getByText(/\+6\.960 ms/)).toBeInTheDocument();
    expect(screen.getByText(/espera na fila/)).toBeInTheDocument();
  });

  it("registro sem trilha e explicado, nao tratado como inexistente", async () => {
    /* A trilha e best-effort e expira em 7 dias. Dizer "registro nao existe" seria
       outra afirmacao, e provavelmente falsa. */
    mockarApi(API);
    renderizar(<Trail />);
    await consultar("01VAZIO");

    expect(await screen.findByText("Sem trilha para este registro")).toBeInTheDocument();
    expect(screen.getByText(/continuam intactos/)).toBeInTheDocument();
  });

  it("carregando nao e renderizado como vazio", async () => {
    let liberar: (() => void) | undefined;
    const espera = new Promise<void>((r) => (liberar = r));
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        const caminho = new URL(url, "http://x").pathname;
        if (caminho.includes("/trail/")) await espera;
        const corpo = caminho.includes("/trail/")
          ? trilhaFalsa
          : { items: [{ record_id: "01TESTE" }], next_cursor: null };
        return new Response(JSON.stringify(corpo), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }),
    );

    renderizar(<Trail />);
    await consultar("01TESTE");

    expect(await screen.findByText("carregando a trilha…")).toBeInTheDocument();
    expect(screen.queryByText("Sem trilha para este registro")).not.toBeInTheDocument();

    liberar?.();
    await waitFor(() => expect(screen.getByText("aceito")).toBeInTheDocument());
  });
});
