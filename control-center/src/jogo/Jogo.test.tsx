import { fireEvent, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderizar } from "../test-utils";
import { Jogo } from "./Jogo";

afterEach(() => vi.unstubAllGlobals());

const evidencia = {
  total: 0.77, decision: "POSSIBLE_MATCH", compared_fields: 2, reason: "",
  fields: [
    { field: "email", weight: 0.25, score: 0.72, left: "rafael.uchoa.5600@example.com", right: "rafael.uchoa.1829@example.com" },
    { field: "full_name", weight: 0.2, score: 0.83, left: "Rafael Cardoso Uchoa", right: "Rafael Uchoa" },
  ],
};

it("mostra o par, aceita o palpite e revela a decisao real", async () => {
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    const path = new URL(url).pathname;
    const body = path === "/v1/resolution/reviews"
      ? { items: [{ pair_id: "p1", record_a: "a", record_b: "b", record_type: "person", score: 0.77, status: "pending", created_at: "", decided_at: null, reason: null, evidence: evidencia }] }
      : { items: [], next_cursor: null };
    return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }));
  }));
  renderizar(<Jogo sair={() => {}} />);

  expect(await screen.findByText("Rafael Cardoso Uchoa")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Mesma pessoa/ }));

  expect(await screen.findByText("O Nexus decidiu diferente")).toBeInTheDocument();
  expect(screen.getByText(/mandou para um humano/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /Ver resultado/ }));
  expect(await screen.findByText("Difícil, né?")).toBeInTheDocument();
});
