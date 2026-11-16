import { fireEvent, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderizar } from "../test-utils";
import { JornadaViva } from "./JornadaViva";

afterEach(() => vi.unstubAllGlobals());

it("acompanha os marcos do registro enviado sem inventar o resultado", async () => {
  vi.stubGlobal("fetch", vi.fn((url: string, opcoes?: RequestInit) => {
    const path = new URL(url).pathname;
    const body = path === "/v1/records/person" && opcoes?.method === "POST"
      ? { record_id: "exemplo-1" }
      : path === "/v1/records/exemplo-1" ? { record_id: "exemplo-1", payload: { full_name: "Pessoa Exemplo" } } : { record_id: "exemplo-1", events: [
          { stage: "accepted", correlation_id: "c", service: "api", occurred_at: "2026-01-01T00:00:00Z", detail: {}, delta_ms: null },
          { stage: "published", correlation_id: "c", service: "api", occurred_at: "2026-01-01T00:00:01Z", detail: {}, delta_ms: 1000 },
        ], services: ["api"], total_ms: 1000 };
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }));
  }));
  renderizar(<JornadaViva />);
  fireEvent.click(screen.getByRole("button", { name: /Enviar exemplo/ }));
  expect(await screen.findByText(/Uma mensagem foi publicada na fila/)).toBeInTheDocument();
  expect(screen.getByText(/Ainda não há um resultado de processamento/)).toBeInTheDocument();
  expect(screen.getByText(/PUBLISHED/)).toBeInTheDocument();
});

it("mostra somente o resultado informado pelo evento de processamento", async () => {
  vi.stubGlobal("fetch", vi.fn((url: string, opcoes?: RequestInit) => {
    const path = new URL(url).pathname;
    const body = path === "/v1/records/person" && opcoes?.method === "POST"
      ? { record_id: "exemplo-2", status: "accepted" }
      : path === "/v1/records/exemplo-2"
        ? { record_id: "exemplo-2", payload: { full_name: "Ana Exemplo" } }
        : { record_id: "exemplo-2", events: [{ stage: "resolved", occurred_at: "2026-01-01T00:00:01Z", correlation_id: "c", service: "worker", detail: { candidates: 2, matches: 0 }, delta_ms: null }], services: ["worker"], total_ms: null };
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }));
  }));
  renderizar(<JornadaViva />);
  fireEvent.click(screen.getByRole("button", { name: /Enviar exemplo/ }));
  expect(await screen.findByText(/2 candidato\(s\) comparado\(s\). 0 correspondência/)).toBeInTheDocument();
  expect(screen.getByText(/não significa que houve uma correspondência/)).toBeInTheDocument();
});
