import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ObservabilityCenter } from "./ObservabilityCenter";
import { alertasVazios, metricsFalso, mockarApi, queueFalso, renderizar, serieFalsa } from "../test-utils";

afterEach(() => vi.unstubAllGlobals());

describe("Observability Center", () => {
  it("identifica fontes e mostra percentis por rota, com amostras", async () => {
    mockarApi({ "/metrics": metricsFalso, "/v1/ops/queue": { ...queueFalso, backend: "sqs" }, "/v1/observability/alerts": alertasVazios, "/v1/observability/series": serieFalsa });
    renderizar(<ObservabilityCenter />);
    expect(await screen.findByText(/estimativas do SQS e podem demorar/)).toBeInTheDocument();
    expect(await screen.findByText(/API pode não compartilhar processo com o worker/)).toBeInTheDocument();
    const rota = await screen.findByText("POST /v1/records/person");
    expect(within(rota.closest("tr")!).getByText("9 ms")).toBeInTheDocument();
    expect(screen.getByText(/ausência de alerta não comprova saúde integral/)).toBeInTheDocument();
  });

  it("mantém fila e série visíveis quando métricas de processo falham", async () => {
    mockarApi({ "/v1/ops/queue": queueFalso, "/v1/observability/alerts": alertasVazios, "/v1/observability/series": serieFalsa });
    renderizar(<ObservabilityCenter />);
    expect(await screen.findByText("sqlite")).toBeInTheDocument();
    expect(await screen.findByText(/4 amostras de 15s/)).toBeInTheDocument();
    const processo = screen.getByRole("heading", { name: "API e processamento" }).closest("section")!;
    await waitFor(() => expect(within(processo).getByRole("alert")).toBeInTheDocument());
    expect(within(processo).queryByText("registros processados")).not.toBeInTheDocument();
  });

  it("mostra erro da série em vez de dizer que não há amostras", async () => {
    mockarApi({ "/metrics": metricsFalso, "/v1/ops/queue": queueFalso, "/v1/observability/alerts": alertasVazios });
    renderizar(<ObservabilityCenter />);
    const serie = screen.getByRole("heading", { name: "Histórico de profundidade" }).closest("section")!;
    await waitFor(() => expect(within(serie).getByRole("alert")).toBeInTheDocument());
    expect(within(serie).queryByText(/Sem amostras na janela/)).not.toBeInTheDocument();
  });

  it("não transforma ausência de métricas de worker em zero", async () => {
    mockarApi({ "/metrics": { ...metricsFalso, counters: {}, latency_ms: {} }, "/v1/ops/queue": queueFalso, "/v1/observability/alerts": alertasVazios, "/v1/observability/series": serieFalsa });
    renderizar(<ObservabilityCenter />);
    const rotulo = await screen.findByText("registros processados");
    expect(rotulo.closest(".tile")).toHaveTextContent("—");
  });
});
