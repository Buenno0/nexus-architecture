/**
 * O estado das secoes 2 e 3: um lote de exemplo e o que o Nexus decidiu sobre ele.
 *
 * DOIS PASSOS, DE PROPOSITO
 *
 * Enviar e processar sao botoes separados porque sao momentos separados na
 * arquitetura. A API aceita, guarda e enfileira — e para por ai. Nada processa
 * sozinho: nao ha worker residente nem gatilho de SQS para Lambda (ADR-003). Juntar
 * os dois num botao so esconderia justamente a decisao que o projeto quer mostrar.
 *
 * TUDO E BUSCADO SOB DEMANDA
 *
 * Nenhuma consulta aqui tem polling. O visitante conduz, entao buscar depois de cada
 * acao mostra o estado tao ao vivo quanto um laco — e nao deixa consulta correndo na
 * aba de quem abriu a pagina e saiu para o cafe.
 *
 * POR QUE OITO REGISTROS
 *
 * Um registro sozinho nunca encontra par: o gerador so produz duplicata ou variante a
 * partir de um original que ja esteja no lote (ver `build_batch` em
 * src/nexus/demo/synthetic.py). Deduplicacao precisa de populacao.
 *
 * O numero vem da conta de qual lote produz um par **resolvivel**. Duplicata exata nao
 * serve: ela e barrada pela deduplicacao por conteudo, devolve o mesmo `record_id` e
 * nunca chega ao resolvedor. So a variante (30% por registro depois do primeiro) gera
 * dois registros distintos que o Nexus precisa comparar. Com cinco registros a chance
 * de haver ao menos uma variante e 1 - 0,7^4 = 76%; com oito, 1 - 0,7^7 = 92%. A
 * diferenca e entre um visitante em quatro e um em doze ver a secao da decisao vazia.
 */

import { useCallback, useState } from "react";

import { request } from "../api/client";
import { config } from "../api/config";
import { montarLote } from "../api/generator";
import { avancar, ingerir, semear } from "../api/queries";
import type { Entity, EntityMember, Evidence, RecordDetail, Trail } from "../api/types";

/** Quantos registros um lote de exemplo cria. Ver a nota acima. */
export const TAMANHO_DO_LOTE = 8;

/**
 * Orcamento de um passo no ambiente local.
 *
 * Espelha `DEMO_ADVANCE_MAX_BATCHES` e `DEMO_ADVANCE_MAX_MESSAGES` de
 * src/nexus/ingestion/api.py. Divergir faria a mesma pagina se comportar de um jeito
 * na demonstracao e de outro no desenvolvimento, que e onde ela e testada.
 */
const RODADAS_DO_PASSO = 12;
const MENSAGENS_POR_RODADA = 10;

export type Fase =
  | "inicio"
  | "enviando"
  | "enfileirado"
  | "processando"
  | "concluido"
  | "erro";

/** O par que o Nexus associou, com a evidencia que sustentou a decisao. */
export interface ParResolvido {
  entityId: string;
  evidencia: Evidence;
  registroA: RecordDetail;
  registroB: RecordDetail;
}

export interface Jornada {
  fase: Fase;
  erro: string;
  /** Identificadores do lote enviado, na ordem em que a API os devolveu. */
  ids: string[];
  /** Trilha do primeiro registro — e ela que move o desenho. */
  trilha: Trail | null;
  registros: RecordDetail[];
  par: ParResolvido | null;
  /**
   * O lote do visitante ainda nao chegou ao fim do processamento.
   *
   * Mede a trilha DELE, nao a profundidade da fila. A fila e compartilhada: ela pode
   * estar cheia de registros de outras visitas, e dizer "ainda falta" por causa
   * disso mandaria o visitante apertar o botao a toa.
   */
  precisaDeOutroPasso: boolean;
  enviar: () => void;
  processar: () => void;
}

function mensagem(causa: unknown, padrao: string): string {
  return causa instanceof Error && causa.message ? causa.message : padrao;
}

/** Busca os detalhes do lote, ignorando os que a API nao devolver. */
async function buscarRegistros(ids: string[]): Promise<RecordDetail[]> {
  const respostas = await Promise.allSettled(
    ids.map((id) => request<RecordDetail>(`/v1/records/${encodeURIComponent(id)}`)),
  );
  return respostas
    .filter((r): r is PromiseFulfilledResult<RecordDetail> => r.status === "fulfilled")
    .map((r) => r.value);
}

/** Uma evidencia vazia chega como `{}`; so interessa a que tem campos comparados. */
function temCampos(evidencia: EntityMember["evidence"]): evidencia is Evidence {
  return "fields" in evidencia && Array.isArray(evidencia.fields) && evidencia.fields.length > 0;
}

/**
 * Acha, no lote, dois registros que o Nexus colocou na mesma entidade.
 *
 * Procura primeiro entre os registros do proprio visitante. Um deles pode ter sido
 * associado a alguem que ja estava no acervo — nesse caso o segundo registro do par
 * nao esta no lote, e a entidade e quem informa qual foi.
 */
async function acharPar(registros: RecordDetail[]): Promise<ParResolvido | null> {
  const comEntidade = registros.filter((r) => r.entity_id);
  const porId = new Map(registros.map((r) => [r.record_id, r]));

  for (const registro of comEntidade) {
    const entityId = registro.entity_id;
    if (!entityId) continue;

    let entidade: Entity;
    try {
      entidade = await request<Entity>(
        `/v1/resolution/entities/${encodeURIComponent(entityId)}`,
      );
    } catch {
      continue; // uma entidade inacessivel nao invalida as outras
    }
    if (entidade.member_count < 2) continue;

    const membro = entidade.members.find(
      (m) => m.matched_record_id !== null && temCampos(m.evidence),
    );
    if (!membro?.matched_record_id || !temCampos(membro.evidence)) continue;

    const a = porId.get(membro.record_id) ?? (await pegar(membro.record_id));
    const b = porId.get(membro.matched_record_id) ?? (await pegar(membro.matched_record_id));
    if (!a || !b) continue;

    return { entityId, evidencia: membro.evidence, registroA: a, registroB: b };
  }
  return null;
}

async function pegar(id: string): Promise<RecordDetail | null> {
  try {
    return await request<RecordDetail>(`/v1/records/${encodeURIComponent(id)}`);
  } catch {
    return null;
  }
}

export function useJornada(): Jornada {
  const [fase, setFase] = useState<Fase>("inicio");
  const [erro, setErro] = useState("");
  const [ids, setIds] = useState<string[]>([]);
  const [trilha, setTrilha] = useState<Trail | null>(null);
  const [registros, setRegistros] = useState<RecordDetail[]>([]);
  const [par, setPar] = useState<ParResolvido | null>(null);
  const [precisaDeOutroPasso, setPrecisa] = useState(false);

  /** Le a trilha e devolve se ela ja chegou ao fim. */
  const lerTrilha = useCallback(async (id: string): Promise<boolean> => {
    try {
      const nova = await request<Trail>(
        `/v1/observability/trail/${encodeURIComponent(id)}`,
      );
      setTrilha(nova);
      return nova.events.some(
        (e) => e.stage === "resolved" || e.stage === "dead_lettered",
      );
    } catch {
      // A trilha e best-effort (ADR-010): nao conseguir le-la nao significa que o
      // registro falhou, entao o desenho fica como esta em vez de acusar erro.
      return false;
    }
  }, []);

  const enviar = useCallback(() => {
    setFase("enviando");
    setErro("");
    setIds([]);
    setTrilha(null);
    setRegistros([]);
    setPar(null);
    setPrecisa(false);

    void (async () => {
      try {
        let novos: string[];
        if (config.demoMode) {
          const resultado = await semear(TAMANHO_DO_LOTE);
          novos = resultado.record_ids ?? [];
          if (novos.length === 0) {
            throw new Error(
              "A API aceitou o lote mas nao devolveu os identificadores. Acompanhar a jornada exige a versao atualizada da API.",
            );
          }
        } else {
          // Fora da demonstracao nao existe `/v1/demo/*`: o operador tem ingestao
          // livre, e as mesmas taxas do servidor mantem a historia igual nos dois.
          const lote = montarLote(TAMANHO_DO_LOTE, "narrativa", 0.15, 0.3);
          const aceitos = await Promise.all(
            lote.map((registro) => ingerir("person", registro.payload)),
          );
          novos = aceitos.map((r) => r.record_id);
        }
        // A deduplicacao por conteudo devolve o MESMO record_id para registros
        // identicos, entao o lote pode trazer repetidos. Consultar duas vezes o
        // mesmo registro so gastaria chamada.
        setIds([...new Set(novos)]);
        if (novos[0]) await lerTrilha(novos[0]);
        setFase("enfileirado");
      } catch (causa) {
        setErro(mensagem(causa, "Nao foi possivel enviar o lote. Tente de novo."));
        setFase("erro");
      }
    })();
  }, [lerTrilha]);

  const processar = useCallback(() => {
    setFase("processando");
    setErro("");

    void (async () => {
      try {
        if (config.demoMode) {
          await avancar();
        } else {
          // Fora da demonstracao nao existe `/v1/demo/advance`, entao o passo e montado
          // aqui com as rotas do operador — e com o mesmo orcamento que o servidor usa
          // la, para a pagina se comportar igual nos dois ambientes.
          //
          // `max_messages` tem teto de 100 no schema (ProcessRequest), entao o orcamento
          // vem de repetir rodadas, nao de pedir um lote maior.
          await request("/v1/ops/dispatch", { method: "POST", body: { limit: 25 } });
          for (let rodada = 0; rodada < RODADAS_DO_PASSO; rodada += 1) {
            const consumo = await request<{ received: number }>("/v1/ops/process", {
              method: "POST",
              body: { max_messages: MENSAGENS_POR_RODADA },
            });
            if (consumo.received === 0) break;
          }
        }
        // A fila e compartilhada e atende por ordem de chegada: com acervo acumulado,
        // um passo pode ter consumido registros de outra visita antes dos deste lote.
        const terminou = ids[0] ? await lerTrilha(ids[0]) : true;
        setPrecisa(!terminou);
        const detalhes = await buscarRegistros(ids);
        setRegistros(detalhes);
        setPar(await acharPar(detalhes));
        setFase("concluido");
      } catch (causa) {
        setErro(mensagem(causa, "Nao foi possivel processar agora. Tente de novo."));
        setFase("erro");
      }
    })();
  }, [ids, lerTrilha]);

  return { fase, erro, ids, trilha, registros, par, precisaDeOutroPasso, enviar, processar };
}
