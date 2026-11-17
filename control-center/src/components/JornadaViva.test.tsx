import { fireEvent, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderizar } from "../test-utils";
import { JornadaViva } from "./JornadaViva";

afterEach(() => vi.unstubAllGlobals());

const ev = (stage: string, service: string, delta: number | null, detail = {}) => ({
  stage, service, delta_ms: delta, detail, correlation_id: "c", occurred_at: "2026-01-01T00:00:00Z",
});

function api(trilha: () => unknown[], extra: (path: string) => unknown = () => undefined) {
  vi.stubGlobal("fetch", vi.fn((url: string, opcoes?: RequestInit) => {
    const path = new URL(url).pathname;
    let body: unknown = extra(path);
    if (body === undefined) {
      if (path === "/v1/records/person" && opcoes?.method === "POST") body = { record_id: "reg-1", status: "accepted" };
      else if (path.startsWith("/v1/observability/trail/")) body = { record_id: "reg-1", events: trilha(), services: ["api"], total_ms: null };
      else if (path === "/v1/ops/process") body = { received: 0 };
      else if (path.startsWith("/v1/records/")) body = { record_id: "reg-1", payload: {}, entity_id: null };
      else body = {};
    }
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }));
  }));
}

it("mostra o que a API e o armazenamento gravaram, e a fila esperando", async () => {
  api(() => [ev("accepted", "api", null), ev("published", "dispatcher", 412)]);
  renderizar(<JornadaViva />);
  fireEvent.click(screen.getByRole("button", { name: /Enviar 8 registros/ }));

  expect(await screen.findByText(/202 · 1 aceitos/)).toBeInTheDocument();
  expect(await screen.findByText("publicado", {}, { timeout: 3000 })).toBeInTheDocument();
  expect(screen.getByText("até alguém pedir")).toBeInTheDocument();
  expect(screen.getByText(/\+412 ms/)).toBeInTheDocument();
});

it("sem par associado, diz isso em vez de inventar uma comparacao", async () => {
  let processou = false;
  api(
    () => processou
      ? [ev("accepted", "api", null), ev("published", "dispatcher", 10), ev("consumed", "worker", 1500), ev("resolved", "worker", 70, { candidates: 3, matches: 0 })]
      : [ev("accepted", "api", null)],
    (path) => { if (path === "/v1/ops/dispatch") { processou = true; return {}; } return undefined; },
  );
  renderizar(<JornadaViva />);
  fireEvent.click(screen.getByRole("button", { name: /Enviar 8 registros/ }));
  await screen.findByText(/202 · 1 aceitos/);
  fireEvent.click(screen.getByRole("button", { name: /Processar agora/ }));

  expect(await screen.findByText(/3 candidatos · 0 correspondências/, {}, { timeout: 4000 })).toBeInTheDocument();
  expect(screen.getByText(/Nenhum par associado neste lote/)).toBeInTheDocument();
  expect(screen.getByText("1.5 s")).toBeInTheDocument();
});
