import { afterEach, describe, expect, it, vi } from "vitest";

import { NexusApiError, request, setTokenProvider } from "./client";

function respostaFalsa(corpo: unknown, init: ResponseInit & { headers?: Record<string, string> } = {}) {
  return new Response(JSON.stringify(corpo), {
    status: init.status ?? 200,
    headers: { "content-type": "application/json", ...(init.headers ?? {}) },
  });
}

/** Le os headers da primeira chamada. `noUncheckedIndexedAccess` exige a checagem. */
function headersDaChamada(fetchFalso: ReturnType<typeof vi.fn>): Record<string, string> {
  const chamada = fetchFalso.mock.calls[0];
  if (!chamada) throw new Error("fetch nao foi chamado");
  return (chamada[1] as RequestInit).headers as Record<string, string>;
}

afterEach(() => {
  vi.unstubAllGlobals();
  setTokenProvider(async () => null);
});

describe("request", () => {
  it("devolve o corpo em caso de sucesso", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respostaFalsa({ status: "ok" })));
    await expect(request<{ status: string }>("/health")).resolves.toEqual({ status: "ok" });
  });

  it("envia a chave de idempotencia quando informada", async () => {
    const fetchFalso = vi.fn().mockResolvedValue(respostaFalsa({}));
    vi.stubGlobal("fetch", fetchFalso);

    await request("/v1/records/person", { method: "POST", body: {}, idempotencyKey: "k-1" });

    expect(headersDaChamada(fetchFalso)["idempotency-key"]).toBe("k-1");
  });

  it("nao envia Authorization quando nao ha token", async () => {
    const fetchFalso = vi.fn().mockResolvedValue(respostaFalsa({}));
    vi.stubGlobal("fetch", fetchFalso);

    await request("/health");

    expect(headersDaChamada(fetchFalso).authorization).toBeUndefined();
  });

  it("envia Authorization quando ha token", async () => {
    const fetchFalso = vi.fn().mockResolvedValue(respostaFalsa({}));
    vi.stubGlobal("fetch", fetchFalso);
    setTokenProvider(async () => "jwt-token");

    await request("/health");

    expect(headersDaChamada(fetchFalso).authorization).toBe("Bearer jwt-token");
  });

  it("transforma erro da API em excecao com o codigo e o correlation_id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        respostaFalsa(
          { code: "missing_idempotency_key", message: "Header obrigatorio", correlation_id: "c-9" },
          { status: 400 },
        ),
      ),
    );

    const erro = await request("/v1/records/person").catch((e: unknown) => e);
    expect(erro).toBeInstanceOf(NexusApiError);
    const api = erro as NexusApiError;
    expect(api.status).toBe(400);
    expect(api.code).toBe("missing_idempotency_key");
    expect(api.correlationId).toBe("c-9");
  });

  it("prefere o correlation_id do header ao do corpo", async () => {
    // O header chega mesmo quando o erro vem de uma camada que nao conhece o formato
    // da aplicacao — API Gateway, por exemplo.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        respostaFalsa(
          { code: "x", message: "y", correlation_id: "do-corpo" },
          { status: 500, headers: { "x-correlation-id": "do-header" } },
        ),
      ),
    );

    const erro = (await request("/x").catch((e: unknown) => e)) as NexusApiError;
    expect(erro.correlationId).toBe("do-header");
  });

  it("lida com resposta de erro sem JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("<html>502</html>", { status: 502, statusText: "Bad Gateway" })),
    );

    const erro = (await request("/x").catch((e: unknown) => e)) as NexusApiError;
    expect(erro).toBeInstanceOf(NexusApiError);
    expect(erro.status).toBe(502);
  });

  it("nunca devolve dado parcial: erro vira excecao", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(respostaFalsa({ pending: 5 }, { status: 503 })));
    await expect(request("/v1/ops/queue")).rejects.toBeInstanceOf(NexusApiError);
  });
});
