/**
 * Consultas e operacoes contra a API.
 *
 * Leituras usam polling com o intervalo configurado. Operacoes invalidam as consultas
 * afetadas para que a tela reflita o efeito sem esperar o proximo ciclo.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { config } from "./config";
import { novaChaveDeIdempotencia, request } from "./client";
import type {
  Alerts,
  DispatchResult,
  Entity,
  Health,
  Metrics,
  ProcessResult,
  QueueStats,
  RecordOut,
  RecordPage,
  RedriveResult,
  ReprocessResult,
  ResolutionStats,
  ReviewPage,
  Series,
  Trail,
} from "./types";

const polling = { refetchInterval: config.pollIntervalMs, refetchOnWindowFocus: true } as const;

export const chaves = {
  health: ["health"] as const,
  metrics: ["metrics"] as const,
  queue: ["ops", "queue"] as const,
  resolution: ["resolution", "stats"] as const,
  reviews: ["resolution", "reviews"] as const,
  records: (tipo: string, limite: number) => ["records", tipo, limite] as const,
  entity: (id: string) => ["resolution", "entity", id] as const,
  alerts: ["observability", "alerts"] as const,
  series: (janela: number) => ["observability", "series", janela] as const,
  trail: (id: string) => ["observability", "trail", id] as const,
};

export function useHealth() {
  return useQuery({
    queryKey: chaves.health,
    queryFn: () => request<Health>("/health"),
    ...polling,
  });
}

export function useMetrics() {
  return useQuery({
    queryKey: chaves.metrics,
    queryFn: () => request<Metrics>("/metrics"),
    ...polling,
  });
}

export function useQueueStats() {
  return useQuery({
    queryKey: chaves.queue,
    queryFn: () => request<QueueStats>("/v1/ops/queue"),
    ...polling,
  });
}

export function useResolutionStats() {
  return useQuery({
    queryKey: chaves.resolution,
    queryFn: () => request<ResolutionStats>("/v1/resolution/stats"),
    ...polling,
  });
}

export function useReviews(limite = 25) {
  return useQuery({
    queryKey: [...chaves.reviews, limite],
    queryFn: () => request<ReviewPage>(`/v1/resolution/reviews?limit=${limite}`),
    ...polling,
  });
}

export function useRecords(tipo: "person" | "organization" = "person", limite = 10) {
  return useQuery({
    queryKey: chaves.records(tipo, limite),
    queryFn: () => request<RecordPage>(`/v1/records?record_type=${tipo}&limit=${limite}`),
    ...polling,
  });
}

export function useEntity(id: string | null) {
  return useQuery({
    queryKey: chaves.entity(id ?? ""),
    queryFn: () => request<Entity>(`/v1/resolution/entities/${id}`),
    enabled: id !== null,
  });
}

/** Invalida tudo que uma operacao pode ter mudado. */
function useInvalidarTudo() {
  const cliente = useQueryClient();
  return () => {
    void cliente.invalidateQueries({ queryKey: chaves.metrics });
    void cliente.invalidateQueries({ queryKey: chaves.queue });
    void cliente.invalidateQueries({ queryKey: chaves.resolution });
    void cliente.invalidateQueries({ queryKey: chaves.reviews });
    void cliente.invalidateQueries({ queryKey: ["records"] });
  };
}

export function useDispatch() {
  const invalidar = useInvalidarTudo();
  return useMutation({
    mutationFn: (limit: number) =>
      request<DispatchResult>("/v1/ops/dispatch", { method: "POST", body: { limit } }),
    onSuccess: invalidar,
  });
}

export function useProcess() {
  const invalidar = useInvalidarTudo();
  return useMutation({
    mutationFn: (maxMessages: number) =>
      request<ProcessResult>("/v1/ops/process", {
        method: "POST",
        body: { max_messages: maxMessages },
      }),
    onSuccess: invalidar,
  });
}

export function useRedrive() {
  const invalidar = useInvalidarTudo();
  return useMutation({
    mutationFn: (limit: number) =>
      request<RedriveResult>("/v1/ops/redrive", { method: "POST", body: { limit } }),
    onSuccess: invalidar,
  });
}

export function useReprocess() {
  const invalidar = useInvalidarTudo();
  return useMutation({
    mutationFn: (limit: number) =>
      request<ReprocessResult>("/v1/ops/reprocess", { method: "POST", body: { limit } }),
    onSuccess: invalidar,
  });
}

export function useDecidirRevisao() {
  const invalidar = useInvalidarTudo();
  return useMutation({
    mutationFn: ({
      pairId,
      decisao,
      motivo,
    }: {
      pairId: string;
      decisao: "confirm" | "reject";
      motivo?: string;
    }) =>
      request(`/v1/resolution/reviews/${pairId}`, {
        method: "POST",
        body: { decision: decisao, ...(motivo ? { reason: motivo } : {}) },
      }),
    onSuccess: invalidar,
  });
}

/** Ingestao de um registro sintetico. Cada envio e uma operacao distinta — ADR-002. */
export function ingerir(
  tipo: "person" | "organization",
  payload: Record<string, unknown>,
): Promise<RecordOut> {
  return request<RecordOut>(`/v1/records/${tipo}`, {
    method: "POST",
    body: payload,
    idempotencyKey: novaChaveDeIdempotencia(),
  });
}

// ------------------------------------------------------------- observabilidade

/**
 * Alertas ativos, consultados em todas as telas.
 *
 * Avaliados no servidor a partir do estado real a cada chamada. O navegador nao
 * decide nada: um limiar duplicado aqui divergiria do backend no primeiro ajuste.
 */
export function useAlerts() {
  return useQuery({
    queryKey: chaves.alerts,
    queryFn: () => request<Alerts>("/v1/observability/alerts"),
    ...polling,
  });
}

/**
 * Serie persistida da profundidade da plataforma.
 *
 * Ao contrario de `useSessionSeries`, isto sobrevive a recarregar a pagina e a
 * reiniciar a API — era a limitacao que o ADR-009 registrou.
 */
export function usePersistedSeries(janelaMinutos: number) {
  return useQuery({
    queryKey: chaves.series(janelaMinutos),
    queryFn: () => request<Series>(`/v1/observability/series?window=${janelaMinutos}`),
    ...polling,
  });
}

/**
 * Jornada de uma observacao. So busca quando ha um identificador.
 *
 * Trilha vazia nao e erro: ela e best-effort e expira em sete dias.
 */
export function useTrail(recordId: string) {
  return useQuery({
    queryKey: chaves.trail(recordId),
    queryFn: () => request<Trail>(`/v1/observability/trail/${encodeURIComponent(recordId)}`),
    enabled: recordId.length > 0,
    refetchOnWindowFocus: false,
  });
}
