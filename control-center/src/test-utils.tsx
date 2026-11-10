/** Utilitarios de teste: renderiza telas com as consultas isoladas. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { vi } from "vitest";

import type { Metrics, QueueStats, ResolutionStats, ReviewPage } from "./api/types";

export function renderizar(ui: ReactElement) {
  const cliente = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchInterval: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  return render(<QueryClientProvider client={cliente}>{ui}</QueryClientProvider>);
}

export const metricsFalso: Metrics = {
  scope: "in_process",
  environment: "local",
  outbox_pending: 0,
  queue: { pending: 3, in_flight: 1, dead: 0 },
  modules: {
    ingestion: "implemented",
    queue_engine: "implemented",
    entity_resolution: "implemented",
    observability: "partial",
  },
  counters: {
    "ingestion_accepted_total{record_type=person}": 42,
    ingestion_duplicate_total: 7,
    "http_requests_total{method=POST,path=/v1/records/person,status=202}": 42,
    "http_requests_total{method=GET,path=/v1/records/{record_id},status=404}": 2,
    worker_processed_total: 40,
    worker_skipped_duplicate_total: 2,
  },
  latency_ms: {
    "http_request_duration{method=POST,path=/v1/records/person}": {
      count: 42, min: 2, max: 38, mean: 5, p50: 4, p95: 9, p99: 21,
    },
    worker_record_duration: { count: 40, min: 1, max: 9, mean: 3, p50: 2, p95: 6, p99: 8 },
    worker_batch_duration: { count: 5, min: 10, max: 90, mean: 40, p50: 35, p95: 80, p99: 88 },
  },
};

export const queueFalso: QueueStats = {
  backend: "sqlite",
  enabled: true,
  pending: 3,
  in_flight: 1,
  dead: 0,
  outbox_pending: 0,
};

export const resolucaoFalsa: ResolutionStats = {
  processor_version: "resolution-v1",
  pending_reviews: 1,
  counters: {
    records_analyzed: 40,
    candidates_compared: 12,
    matches: 6,
    possible_matches: 1,
    entities_created: 5,
    merges: 1,
    refused_too_large: 0,
    reviews_created: 1,
  },
};

export const revisoesFalsas: ReviewPage = {
  items: [
    {
      pair_id: "par-1",
      record_a: "01AAA",
      record_b: "01BBB",
      record_type: "person",
      score: 0.727,
      status: "pending",
      created_at: "2026-11-09T12:00:00+00:00",
      decided_at: null,
      reason: null,
      evidence: {
        total: 0.727,
        decision: "POSSIBLE_MATCH",
        compared_fields: 4,
        reason: "entre os limiares; exige revisao",
        fields: [
          { field: "document", weight: 0.45, score: 0.394, left: "11122233344", right: "11122233345" },
          { field: "email", weight: 0.25, score: 1, left: "a@b.com", right: "a@b.com" },
          { field: "full_name", weight: 0.2, score: 1, left: "Maria Souza", right: "Maria Souza" },
          { field: "phone", weight: 0.1, score: 1, left: "11999", right: "11999" },
        ],
      },
    },
  ],
};

/** Responde por rota. Rotas nao mapeadas devolvem 503. */
export function mockarApi(mapa: Record<string, unknown>) {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => {
      const caminho = new URL(url, "http://localhost").pathname;
      const corpo = mapa[caminho];
      if (corpo === undefined) {
        return Promise.resolve(
          new Response(JSON.stringify({ code: "nao_mapeado", message: caminho, correlation_id: "c-test" }), {
            status: 503,
            headers: { "content-type": "application/json" },
          }),
        );
      }
      return Promise.resolve(
        new Response(JSON.stringify(corpo), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    }),
  );
}

export function mockarFalhaTotal() {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
}
