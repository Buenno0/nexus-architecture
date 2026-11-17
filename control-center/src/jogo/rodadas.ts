/**
 * Rodadas do jogo, montadas com pares que o Nexus de fato julgou.
 *
 * Duas fontes, so leitura (funciona na demonstracao publica):
 * - fila de revisao: pares POSSIBLE_MATCH, a faixa de duvida;
 * - entidades com mais de um membro: pares MATCH, com a evidencia da associacao.
 *
 * NO_MATCH fica de fora: o Nexus nao grava evidencia de par descartado, e inventar
 * uma rodada "sao diferentes" exigiria um score que o sistema nunca calculou.
 */

import { request } from "../api/client";
import type { Entity, Evidence, RecordDetail, RecordPage, ReviewPage } from "../api/types";

export type Resposta = "mesma" | "diferentes" | "duvida";

export interface Rodada {
  id: string;
  evidencia: Evidence;
  resposta: Resposta;
}

export const DA_DECISAO: Record<Evidence["decision"], Resposta> = {
  MATCH: "mesma",
  POSSIBLE_MATCH: "duvida",
  NO_MATCH: "diferentes",
};

const POR_TIPO = 3;
export const TOTAL = 5;

function embaralhar<T>(lista: T[]): T[] {
  const copia = [...lista];
  for (let i = copia.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [copia[i], copia[j]] = [copia[j] as T, copia[i] as T];
  }
  return copia;
}

const comCampos = (e: unknown): e is Evidence =>
  typeof e === "object" && e !== null && Array.isArray((e as Evidence).fields) && (e as Evidence).fields.length > 0;

async function duvidas(): Promise<Rodada[]> {
  const pagina = await request<ReviewPage>("/v1/resolution/reviews?limit=25");
  return pagina.items
    .filter((r) => comCampos(r.evidence))
    .map((r) => ({ id: r.pair_id, evidencia: r.evidence, resposta: DA_DECISAO[r.evidence.decision] }));
}

async function associados(): Promise<Rodada[]> {
  // A listagem nao traz `entity_id` (so o detalhe de cada registro traz), entao o
  // prototipo consulta uma amostra. Uma rota "pares associados" no servidor faria
  // isso numa chamada so.
  const pagina = await request<RecordPage>("/v1/records?limit=60");
  const amostra = embaralhar(pagina.items).slice(0, 24);
  // Em blocos de 6: 24 chamadas de uma vez estouram a concorrencia das Lambdas na
  // demonstracao e voltam 503.
  const detalhes: PromiseSettledResult<RecordDetail>[] = [];
  for (let k = 0; k < amostra.length; k += 6) {
    detalhes.push(
      ...(await Promise.allSettled(
        amostra.slice(k, k + 6).map((r) => request<RecordDetail>(`/v1/records/${encodeURIComponent(r.record_id)}`)),
      )),
    );
  }
  const entidades = embaralhar([
    ...new Set(
      detalhes.flatMap((d) => (d.status === "fulfilled" && d.value.entity_id ? [d.value.entity_id] : [])),
    ),
  ]);
  const achados: Rodada[] = [];
  // Poucas entidades tem par; consultar ate achar o suficiente, sem varrer o acervo.
  for (const id of entidades.slice(0, 12)) {
    if (achados.length >= POR_TIPO + 1) break;
    try {
      const entidade = await request<Entity>(`/v1/resolution/entities/${encodeURIComponent(id)}`);
      const membro = entidade.members.find((m) => m.matched_record_id && comCampos(m.evidence));
      if (membro && comCampos(membro.evidence)) {
        achados.push({ id: membro.record_id, evidencia: membro.evidence, resposta: DA_DECISAO[membro.evidence.decision] });
      }
    } catch {
      // uma entidade inacessivel nao derruba o jogo
    }
  }
  return achados;
}

export async function montarRodadas(): Promise<Rodada[]> {
  const [a, b] = await Promise.allSettled([associados(), duvidas()]);
  const mesmos = a.status === "fulfilled" ? embaralhar(a.value) : [];
  const incertos = b.status === "fulfilled" ? embaralhar(b.value) : [];
  // Mistura os dois tipos para a resposta nao ser sempre a mesma.
  const escolhidas = [...mesmos.slice(0, POR_TIPO), ...incertos.slice(0, TOTAL - Math.min(POR_TIPO, mesmos.length))];
  return embaralhar(escolhidas).slice(0, TOTAL);
}
