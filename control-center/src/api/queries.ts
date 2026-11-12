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

/**
 * Polling.
 *
 * `refetchIntervalInBackground: false` e o padrao do TanStack Query, e esta explicito
 * porque e uma decisao de custo, nao um detalhe: com ele, uma aba oculta para de
 * consultar. Sem ele, uma aba esquecida aberta geraria chamadas indefinidamente — na
 * demonstracao publica, a cada 30s, por tempo indeterminado, e sao essas chamadas que
 * dominariam a fatura, nao os cliques dos visitantes.
 *
 * Aba VISIVEL e esquecida continua consultando: e por isso que o intervalo da
 * demonstracao e maior que o do desenvolvimento.
 */
const polling = {
  refetchInterval: config.pollIntervalMs,
  refetchOnWindowFocus: true,
  refetchIntervalInBackground: false,
} as const;

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

export function useHealth(habilitado = true) {
  return useQuery({
    queryKey: chaves.health,
    queryFn: () => request<Health>("/health"),
    enabled: habilitado,
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

/** Resultado da semeadura no servidor — modo demonstracao. */
export interface SemeaduraOut {
  requested: number;
  accepted: number;
  duplicate: number;
  failed: number;
  quota_used: number;
  quota_total: number;
}

/**
 * Semeia o acervo pelo servidor, em modo demonstracao.
 *
 * O visitante escolhe quantos registros, nunca o que eles dizem.
 */
export function semear(
  quantidade: number,
  tipo: "person" | "organization" = "person",
): Promise<SemeaduraOut> {
  return request<SemeaduraOut>("/v1/demo/seed", {
    method: "POST",
    body: { count: quantidade, record_type: tipo },
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
/**
 * Alertas ativos.
 *
 * `habilitado` existe porque este hook e chamado no `App`, **antes** da barreira de
 * autenticacao — hooks do React rodam incondicionalmente, entao sem a trava ele
 * dispararia enquanto o token do convidado ainda nem existe. O resultado era uma
 * sequencia de `401` no console e, com polling de 30s na demonstracao, ate meio minuto
 * de painel vazio na primeira visita.
 */
export function useAlerts(habilitado = true) {
  return useQuery({
    queryKey: chaves.alerts,
    queryFn: () => request<Alerts>("/v1/observability/alerts"),
    enabled: habilitado,
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
