import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useRates } from "./useSessionSeries";

describe("taxas entre leituras", () => {
  it("usa o tempo da resposta e descarta troca de instancia", async () => {
    const { result, rerender } = renderHook(({ valor, instante, id }) => useRates({ http: valor }, instante, id), {
      initialProps: { valor: 100, instante: 1000, id: "a" as string | undefined },
    });
    await waitFor(() => expect(result.current.instante).toBe(1000));
    expect(result.current.taxas.http).toBeUndefined();
    rerender({ valor: 130, instante: 4000, id: "a" });
    await waitFor(() => expect(result.current.taxas.http).toBe(10));
    rerender({ valor: 500, instante: 7000, id: "b" });
    await waitFor(() => expect(result.current.instante).toBe(7000));
    expect(result.current.taxas.http).toBeUndefined();
    rerender({ valor: 510, instante: 8000, id: undefined });
    await waitFor(() => expect(result.current.instante).toBe(8000));
    expect(result.current.taxas.http).toBeUndefined();
  });
});
