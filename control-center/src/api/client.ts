/**
 * Cliente HTTP da API do Nexus.
 *
 * Duas responsabilidades alem de buscar dados:
 *
 * 1. **Preservar o `correlation_id`.** Quando algo falha, e ele que liga o que o
 *    usuario viu na tela a trilha de log no servidor. Descarta-lo transformaria um
 *    problema rastreavel num "deu erro".
 * 2. **Nunca devolver dado parcial como se fosse completo.** Resposta de erro vira
 *    excecao, e a interface mostra o estado de falha — nunca o numero anterior como
 *    se ainda valesse.
 */

import { config } from "./config";
import type { ApiError } from "./types";

export class NexusApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly correlationId: string;
  readonly details: Record<string, unknown> | undefined;

  constructor(status: number, corpo: Partial<ApiError>) {
    super(corpo.message ?? `Falha HTTP ${status}`);
    this.name = "NexusApiError";
    this.status = status;
    this.code = corpo.code ?? "unknown_error";
    this.correlationId = corpo.correlation_id ?? "";
    this.details = corpo.details;
  }
}

/** Fonte do token. Implementada por `auth/`; aqui e so uma funcao. */
export type TokenProvider = () => Promise<string | null>;

let obterToken: TokenProvider = async () => null;

export function setTokenProvider(provider: TokenProvider): void {
  obterToken = provider;
}

interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
  /** Exigido pelos POST de ingestao — ADR-002. */
  idempotencyKey?: string;
  signal?: AbortSignal;
}

export async function request<T>(caminho: string, opcoes: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, idempotencyKey, signal } = opcoes;

  const headers: Record<string, string> = {};
  if (body !== undefined) headers["content-type"] = "application/json";
  if (idempotencyKey) headers["idempotency-key"] = idempotencyKey;

  const token = await obterToken();
  if (token) headers["authorization"] = `Bearer ${token}`;

  const resposta = await fetch(`${config.apiUrl}${caminho}`, {
    method,
    headers,
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    ...(signal ? { signal } : {}),
  });

  if (!resposta.ok) {
    let corpo: Partial<ApiError> = {};
    try {
      corpo = (await resposta.json()) as Partial<ApiError>;
    } catch {
      // Resposta sem JSON — API Gateway e proxies devolvem texto em alguns erros.
      corpo = { message: resposta.statusText };
    }
    // O header vale mais que o corpo: ele chega mesmo quando o erro vem de uma
    // camada que nao conhece o formato da aplicacao.
    const doHeader = resposta.headers.get("x-correlation-id");
    if (doHeader) corpo.correlation_id = doHeader;
    throw new NexusApiError(resposta.status, corpo);
  }

  if (resposta.status === 204) return undefined as T;
  return (await resposta.json()) as T;
}

/** Cada requisicao de ingestao e uma operacao distinta — ADR-002. */
export function novaChaveDeIdempotencia(): string {
  return crypto.randomUUID();
}
