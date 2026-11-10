/**
 * Tipos da API do Nexus.
 *
 * Espelham os schemas Pydantic de `src/nexus/ingestion/schemas.py`. Divergir aqui
 * produz um erro que o TypeScript nao pega — ele confia nestas declaracoes — e que so
 * aparece como campo vazio na tela.
 */

export type RecordType = "person" | "organization";
export type ModuleStatus = "implemented" | "not_implemented" | "partial" | "disabled";

/** De onde um numero veio, e que garantia ele carrega. Ver ADR-009. */
export type Origem = "persistido" | "processo" | "sessao";

export interface Health {
  status: "ok" | "degraded";
  environment: string;
  version: string;
  persistence: "ok" | "unavailable";
  queue: "enabled" | "not_implemented";
}

export interface LatencySummary {
  count: number;
  min: number;
  max: number;
  mean: number;
  p50: number;
  p95: number;
  p99: number;
}

export interface QueueDepth {
  pending: number;
  in_flight: number;
  dead: number;
}

/**
 * Resposta de `/metrics`.
 *
 * `scope: "in_process"` nao e decorativo: estes numeros zeram a cada reinicio da API e
 * nao agregam entre replicas. `queue` e `outbox_pending`, ao contrario, vem do
 * armazenamento.
 */
export interface Metrics {
  scope: "in_process";
  environment: string;
  outbox_pending: number | null;
  queue: QueueDepth | null;
  modules: Record<string, ModuleStatus>;
  counters: Record<string, number>;
  latency_ms: Record<string, LatencySummary>;
}

export interface QueueStats {
  backend: string;
  enabled: boolean;
  pending: number;
  in_flight: number;
  dead: number;
  outbox_pending: number;
}

export interface DispatchResult {
  scanned: number;
  dispatched: number;
  duplicates: number;
  rescheduled: number;
  missing: number;
}

export interface ProcessResult {
  received: number;
  processed: number;
  skipped_duplicate: number;
  retried: number;
  dead_lettered: number;
  duration_ms: number;
}

export interface RedriveResult {
  redriven: number;
}

export interface ReprocessResult {
  version: string;
  scanned: number;
  enqueued: number;
  already_processed: number;
}

export interface RecordOut {
  record_id: string;
  record_type: RecordType;
  status: "accepted" | "duplicate";
  record_fingerprint: string;
  correlation_id: string;
  seen_count: number;
}

export interface RecordDetail {
  record_id: string;
  record_type: RecordType;
  source: string;
  record_fingerprint: string;
  payload: Record<string, unknown>;
  normalized: Record<string, unknown>;
  correlation_id: string;
  created_at: string;
  seen_count: number;
  entity_id: string | null;
}

export interface RecordPage {
  items: RecordDetail[];
  next_cursor: string | null;
}

/** Contribuicao de um campo para o score. E isto que torna a fusao auditavel. */
export interface FieldScore {
  field: string;
  weight: number;
  score: number;
  left: string | null;
  right: string | null;
}

export interface Evidence {
  total: number;
  decision: "MATCH" | "POSSIBLE_MATCH" | "NO_MATCH";
  compared_fields: number;
  reason: string;
  fields: FieldScore[];
}

export interface ReviewItem {
  pair_id: string;
  record_a: string;
  record_b: string;
  record_type: RecordType;
  score: number;
  status: "pending" | "confirmed" | "rejected";
  created_at: string;
  decided_at: string | null;
  reason: string | null;
  evidence: Evidence;
}

export interface ReviewPage {
  items: ReviewItem[];
}

export interface EntityMember {
  record_id: string;
  joined_at: string;
  score: number;
  matched_record_id: string | null;
  evidence: Evidence | Record<string, never>;
}

export interface MergeEvent {
  event_id: string;
  source_entity_id: string;
  record_a: string;
  record_b: string;
  score: number;
  moved_members: number;
  created_at: string;
}

export interface Entity {
  entity_id: string;
  record_type: RecordType;
  member_count: number;
  version: number;
  created_at: string;
  updated_at: string;
  flagged: boolean;
  flag_reason: string | null;
  members: EntityMember[];
  merges: MergeEvent[];
}

export interface ResolutionStats {
  processor_version: string;
  pending_reviews: number;
  counters: Record<string, number>;
}

export interface ApiError {
  code: string;
  message: string;
  correlation_id: string;
  details?: Record<string, unknown>;
}

// ------------------------------------------------------------- observabilidade

/** Marco na jornada de uma observacao — ADR-010. */
export interface TrailEvent {
  stage: "accepted" | "published" | "consumed" | "resolved" | "failed" | "dead_lettered";
  occurred_at: string;
  correlation_id: string;
  service: string;
  detail: Record<string, unknown>;
  /**
   * Tempo desde o marco anterior; `null` no primeiro.
   *
   * E aqui que o gargalo aparece. O total diz que o registro levou oito segundos; o
   * delta diz que sete foram entre `published` e `consumed` — espera na fila, que
   * nenhuma otimizacao do processador recupera.
   */
  delta_ms: number | null;
}

export interface Trail {
  record_id: string;
  events: TrailEvent[];
  total_ms: number | null;
  /** Varios nomes aqui provam que a trilha atravessa processos. */
  services: string[];
}

export interface SeriesPoint {
  bucket: string;
  values: Record<string, number>;
}

export interface Series {
  metric: string;
  /** Sempre "persistido": vem do armazenamento, nao da memoria desta aba. */
  origin: Origem;
  interval_seconds: number;
  window_minutes: number;
  points: SeriesPoint[];
  /** Baldes sem amostra. A amostragem e oportunista — ver ADR-010. */
  gaps: number;
}

export interface Alert {
  id: string;
  severity: "error" | "warning";
  title: string;
  detail: string;
  origin: Origem;
  value: number | null;
  threshold: number | null;
  context: Record<string, unknown>;
}

export interface Alerts {
  alerts: Alert[];
  evaluated_at: string;
}
