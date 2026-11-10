import { screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiMonitoring } from "./ApiMonitoring";
import { EntityResolution } from "./EntityResolution";
import { Overview } from "./Overview";
import { QueueMonitoring } from "./QueueMonitoring";
import { WorkerMonitoring } from "./WorkerMonitoring";
import {
  metricsFalso,
  mockarApi,
  mockarFalhaTotal,
  queueFalso,
  renderizar,
  resolucaoFalsa,
  revisoesFalsas,
} from "../test-utils";

const API_COMPLETA = {
  "/metrics": metricsFalso,
  "/v1/ops/queue": queueFalso,
  "/v1/resolution/stats": resolucaoFalsa,
  "/v1/resolution/reviews": revisoesFalsas,
  "/health": { status: "ok", environment: "local", version: "0.1.0", persistence: "ok", queue: "enabled" },
  "/v1/records": { items: [], next_cursor: null },
};

afterEach(() => vi.unstubAllGlobals());

describe("Overview", () => {
  it("mostra contadores de ingestao e profundidade de fila", async () => {
    mockarApi(API_COMPLETA);
    renderizar(<Overview />);

    expect(await screen.findByText("42")).toBeInTheDocument();
    expect(await screen.findByText("registros aceitos")).toBeInTheDocument();
  });

  it("rotula a origem de cada numero", async () => {
    mockarApi(API_COMPLETA);
    renderizar(<Overview />);

    await screen.findByText("registros aceitos");
    expect(screen.getAllByText("processo").length).toBeGreaterThan(0);
    expect(screen.getAllByText("persistido").length).toBeGreaterThan(0);
  });
});

describe("ApiMonitoring", () => {
  it("agrega requisicoes por rota", async () => {
    mockarApi(API_COMPLETA);
    renderizar(<ApiMonitoring />);

    expect(await screen.findByText("/v1/records/person")).toBeInTheDocument();
    // A rota com parametro precisa sobreviver ao parsing — ver parse.test.ts.
    expect(screen.getByText("/v1/records/{record_id}")).toBeInTheDocument();
  });

  it("separa respostas por status", async () => {
    mockarApi(API_COMPLETA);
    renderizar(<ApiMonitoring />);
    expect(await screen.findByText("HTTP 202")).toBeInTheDocument();
    expect(screen.getByText("HTTP 404")).toBeInTheDocument();
  });
});

describe("QueueMonitoring", () => {
  it("mostra a profundidade vinda do armazenamento", async () => {
    mockarApi(API_COMPLETA);
    renderizar(<QueueMonitoring />);
    // Espera por um valor que so existe apos a resposta: "aguardando" e rotulo
    // estatico e aparece antes mesmo do dado chegar.
    expect(await screen.findByText("sqlite")).toBeInTheDocument();
    expect(screen.getByText("aguardando")).toBeInTheDocument();
  });

  it("desabilita devolver da DLQ quando ela esta vazia", async () => {
    mockarApi(API_COMPLETA);
    renderizar(<QueueMonitoring />);
    const botao = await screen.findByRole("button", { name: "Devolver da DLQ" });
    expect(botao).toBeDisabled();
  });

  it("oferece os volumes de geracao", async () => {
    mockarApi(API_COMPLETA);
    renderizar(<QueueMonitoring />);
    expect(await screen.findByRole("button", { name: "Gerar 100" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Gerar 10.000" })).toBeInTheDocument();
  });
});

describe("WorkerMonitoring", () => {
  it("explica que nao ha worker residente para contar", async () => {
    mockarApi(API_COMPLETA);
    renderizar(<WorkerMonitoring />);

    expect(await screen.findByText("workers ativos")).toBeInTheDocument();
    expect(screen.getByText(/sob demanda/)).toBeInTheDocument();
    expect(screen.getByText("nao se aplica")).toBeInTheDocument();
  });

  it("mostra duracao por registro e por lote", async () => {
    mockarApi(API_COMPLETA);
    renderizar(<WorkerMonitoring />);
    expect(await screen.findByText("por registro p95")).toBeInTheDocument();
    expect(screen.getByText("por lote p95")).toBeInTheDocument();
  });
});

describe("EntityResolution", () => {
  it("lista a revisao com a evidencia campo a campo", async () => {
    mockarApi(API_COMPLETA);
    renderizar(<EntityResolution />);

    expect(await screen.findByText("0.727")).toBeInTheDocument();
    expect(screen.getByText("entre os limiares; exige revisao")).toBeInTheDocument();
    // A evidencia e o que justifica a tela: sem ela a decisao seria um palpite.
    expect(screen.getByText("document")).toBeInTheDocument();
    expect(screen.getByText("0.394")).toBeInTheDocument();
    expect(screen.getByText("11122233344")).toBeInTheDocument();
  });

  it("oferece confirmar e recusar, nunca fundindo sozinho", async () => {
    mockarApi(API_COMPLETA);
    renderizar(<EntityResolution />);
    expect(await screen.findByRole("button", { name: "Confirmar fusao" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Recusar" })).toBeInTheDocument();
  });
});

describe("regra: falha nunca vira numero", () => {
  it.each([
    ["Overview", <Overview key="o" />],
    ["ApiMonitoring", <ApiMonitoring key="a" />],
    ["QueueMonitoring", <QueueMonitoring key="q" />],
    ["WorkerMonitoring", <WorkerMonitoring key="w" />],
    ["EntityResolution", <EntityResolution key="e" />],
  ])("%s mostra erro em vez de valores quando a API cai", async (_nome, elemento) => {
    mockarFalhaTotal();
    renderizar(elemento);

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByText("Sem resposta da API")).toBeInTheDocument();
  });
});

describe("regra: carregando nunca vira vazio", () => {
  it("a fila de revisao diz que esta consultando, nao que esta vazia", async () => {
    // "Ainda nao sei" e "nao existe" sao afirmacoes diferentes. Exibir a segunda no
    // lugar da primeira leva o operador a concluir que nao ha nada a decidir.
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
    renderizar(<EntityResolution />);

    expect(await screen.findByText("consultando a fila de revisao…")).toBeInTheDocument();
    expect(screen.queryByText(/Nenhum par aguardando/)).not.toBeInTheDocument();
  });

  it("as ultimas observacoes dizem que estao consultando", async () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
    renderizar(<Overview />);

    expect(await screen.findByText("consultando observacoes…")).toBeInTheDocument();
    expect(screen.queryByText(/Nenhuma observacao ainda/)).not.toBeInTheDocument();
  });
});
