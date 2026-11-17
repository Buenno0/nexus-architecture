/**
 * A aba Arquitetura: o sistema desenhado como diagrama, alimentado pelo lote real.
 *
 * NAO E UMA LANDING PAGE
 *
 * A versao anterior abria com titulo de duas linhas e cartao claro com botao azul —
 * o molde de qualquer produto. Quem chega aqui ja esta no console: o que interessa e
 * ver o mecanismo. Cada caixa mostra o dado que aquela etapa produz de verdade (o
 * status da API, as duas linhas da transacao, a espera na fila, os campos comparados).
 *
 * O MESMO FLUXO DA NARRATIVA
 *
 * Enviar e processar vem de `useJornada`, o mesmo estado da pagina publica. Assim o
 * worker tem a evidencia campo a campo para mostrar, e as duas telas nao divergem.
 *
 * O RITMO E DA ANIMACAO, A ORDEM E DO SISTEMA
 *
 * A trilha chega inteira depois de "Processar": acender tudo de uma vez nao mostraria
 * percurso nenhum. Os eventos sao revelados um a um, na ordem em que a plataforma os
 * registrou, e o intervalo real de cada um aparece escrito em ms. A legenda diz isso.
 */

import { useEffect, useState } from "react";

import { config } from "../api/config";
import type { Evidence, TrailEvent } from "../api/types";
import { TAMANHO_DO_LOTE, useJornada } from "../narrativa/useJornada";
import {
  IconeApi,
  IconeArmazenamento,
  IconeFila,
  IconeWorker,
  type EstadoIcone,
} from "./IconesEtapa";
import "./JornadaViva.css";

type Stage = TrailEvent["stage"];

/** Ordem em que os marcos aparecem; `failed` e `dead_lettered` saem do caminho feliz. */
const ORDEM: Stage[] = ["accepted", "published", "consumed", "resolved"];
const PASSO_MS = 650;

const ROTULOS: Record<string, string> = {
  full_name: "nome",
  legal_name: "razão social",
  email: "e-mail",
  phone: "telefone",
  document: "documento",
};

const DECISAO: Record<Evidence["decision"], string> = {
  MATCH: "MATCH — associa",
  POSSIBLE_MATCH: "POSSIBLE_MATCH — vai para revisão",
  NO_MATCH: "NO_MATCH — mantém separados",
};

function curto(id: string | undefined): string {
  return id ? `${id.slice(0, 10)}…` : "—";
}

function ms(valor: number | null | undefined): string {
  if (valor === null || valor === undefined) return "";
  return valor >= 1000 ? `${(valor / 1000).toFixed(1)} s` : `${valor} ms`;
}

/** Quantos marcos ja foram revelados na tela. Sobe um por vez ate alcancar a trilha. */
function useRevelados(total: number, chave: string): number {
  const reduzido =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const [vistos, setVistos] = useState(0);

  useEffect(() => { setVistos(0); }, [chave]);
  useEffect(() => {
    if (reduzido) { setVistos(total); return; }
    if (vistos >= total) return;
    const t = window.setTimeout(() => setVistos((v) => v + 1), vistos === 0 ? 120 : PASSO_MS);
    return () => window.clearTimeout(t);
  }, [vistos, total, reduzido]);

  return Math.min(vistos, total);
}

export function JornadaViva() {
  const j = useJornada();
  const primeiro = j.ids[0];
  const eventos = (j.trilha?.events ?? []).filter((e) => ORDEM.includes(e.stage));
  const vistos = useRevelados(eventos.length, primeiro ?? "");
  const revelados = eventos.slice(0, vistos);
  const evento = (s: Stage) => revelados.find((e) => e.stage === s);
  const teve = (s: Stage) => Boolean(evento(s));

  const ocupado = j.fase === "enviando" || j.fase === "processando";
  const proximo = ORDEM.find((s) => !teve(s));
  /** Uma etapa "age" enquanto a plataforma trabalha nela; "feito" quando o marco chegou. */
  const estado = (concluida: boolean, agindo: boolean): EstadoIcone =>
    concluida ? "feito" : agindo ? "agindo" : "parado";

  const apiFeita = teve("accepted");
  const publicado = teve("published");
  const consumido = teve("consumed");
  const resolvido = evento("resolved");
  const espera = evento("consumed")?.delta_ms;
  const evidencia = resolvido ? j.par?.evidencia : undefined;

  const rota = config.demoMode ? "POST /v1/demo/seed" : "POST /v1/records/person";
  const legenda = legendaDe(j.fase, proximo, Boolean(resolvido), j.precisaDeOutroPasso);

  return (
    <section className="diag" aria-labelledby="diag-titulo">
      <header className="diag__topo">
        <div>
          <p className="diag__rotulo">Arquitetura · execução real</p>
          <h1 className="diag__titulo" id="diag-titulo">
            Um lote atravessando o Nexus
          </h1>
          <p className="diag__texto">
            {TAMANHO_DO_LOTE} registros sintéticos entram pela API, esperam na fila e são
            comparados pelo worker. Cada caixa mostra o que aquela etapa gravou — o desenho
            acompanha o primeiro registro do lote.
          </p>
        </div>
        <div className="diag__acoes">
          <button type="button" className="diag__botao" onClick={j.enviar} disabled={ocupado}>
            {j.fase === "enviando" ? "Enviando…" : j.ids.length ? "Enviar outro lote" : `Enviar ${TAMANHO_DO_LOTE} registros`}
          </button>
          <button
            type="button"
            className="diag__botao diag__botao--sec"
            onClick={j.processar}
            disabled={ocupado || j.ids.length === 0}
          >
            {j.fase === "processando" ? "Processando…" : "Processar agora"}
          </button>
        </div>
      </header>

      <ol className="diag__fluxo">
        <li className={`no ${apiFeita ? "no--feito" : j.fase === "enviando" ? "no--agindo" : ""}`}>
          <div className="no__cabeca">
            <IconeApi estado={estado(apiFeita, j.fase === "enviando")} />
            <div>
              <p className="no__nome">API</p>
              <p className="no__tipo">Lambda · FastAPI</p>
            </div>
          </div>
          <dl className="no__dados">
            <div><dt>rota</dt><dd>{rota}</dd></div>
            <div><dt>resposta</dt><dd>{apiFeita ? `202 · ${j.ids.length} aceitos` : "—"}</dd></div>
            <div><dt>registro</dt><dd>{curto(primeiro)}</dd></div>
          </dl>
          <p className="no__faz">valida, grava e responde — não processa</p>
        </li>

        <Conector ativo={apiFeita} rotulo="mesma requisição" />

        <li className={`no ${apiFeita ? "no--feito" : ""}`}>
          <div className="no__cabeca">
            <IconeArmazenamento estado={estado(apiFeita, false)} />
            <div>
              <p className="no__nome">Armazenamento</p>
              <p className="no__tipo">DynamoDB · tabela única</p>
            </div>
          </div>
          <div className="tx">
            <p className="tx__rotulo">uma transação</p>
            <p className={`tx__linha ${apiFeita ? "tx__linha--on" : ""}`}>
              <span>OBS#{curto(primeiro)}</span>
              <em>{apiFeita ? "gravado" : "—"}</em>
            </p>
            <p className={`tx__linha ${apiFeita ? "tx__linha--on" : ""} ${publicado ? "tx__linha--saiu" : ""}`}>
              <span>OUTBOX#{curto(primeiro)}</span>
              <em>{publicado ? "publicado" : apiFeita ? "pendente" : "—"}</em>
            </p>
          </div>
          <p className="no__faz">registro e evento, os dois ou nenhum</p>
        </li>

        <Conector ativo={publicado} rotulo={publicado ? `dispatcher · ${ms(evento("published")?.delta_ms)}` : "dispatcher"} />

        <li className={`no ${consumido ? "no--feito" : publicado ? "no--esperando" : ""}`}>
          <div className="no__cabeca">
            <IconeFila estado={estado(consumido, publicado && !consumido)} />
            <div>
              <p className="no__nome">Fila</p>
              <p className="no__tipo">SQS · com DLQ</p>
            </div>
          </div>
          <div className="pilha" aria-label="Mensagem deste registro na fila">
            <span className={`pilha__msg ${publicado ? "pilha__msg--entrou" : ""} ${consumido ? "pilha__msg--saiu" : ""}`}>
              msg {curto(primeiro)}
            </span>
          </div>
          <dl className="no__dados">
            <div><dt>estado</dt><dd>{consumido ? "consumida" : publicado ? "esperando" : "—"}</dd></div>
            <div><dt>espera</dt><dd>{consumido && espera !== null ? ms(espera) : publicado ? "até alguém pedir" : "—"}</dd></div>
          </dl>
          <p className="no__faz">sem worker residente: só anda quando alguém pede</p>
        </li>

        <Conector ativo={consumido} rotulo="processamento sob demanda" />

        <li className={`no no--largo ${resolvido ? "no--feito" : consumido ? "no--agindo" : ""}`}>
          <div className="no__cabeca">
            <IconeWorker estado={estado(Boolean(resolvido), consumido && !resolvido)} />
            <div>
              <p className="no__nome">Worker</p>
              <p className="no__tipo">Lambda · resolução de identidade</p>
            </div>
          </div>
          <Comparacao
            resolvido={resolvido}
            evidencia={evidencia}
            par={j.par ? [nomeDe(j.par.registroA.payload), nomeDe(j.par.registroB.payload)] : null}
          />
          <p className="no__faz">compara campos com peso; em dúvida, não funde</p>
        </li>
      </ol>

      <p className="diag__legenda" aria-live="polite">{legenda}</p>
      {j.erro && <p className="diag__erro" role="alert">{j.erro}</p>}

      <div className="diag__log" aria-label="Eventos da trilha">
        <p className="diag__log-titulo">
          trilha · {primeiro ?? "nenhum registro"}
        </p>
        {revelados.length === 0 ? (
          <p className="diag__log-vazio">Os eventos aparecem aqui conforme a plataforma os registra.</p>
        ) : (
          revelados.map((e, i) => (
            <p className="diag__log-linha" key={`${e.stage}-${i}`}>
              <span className="diag__log-hora">{new Date(e.occurred_at).toLocaleTimeString("pt-BR")}</span>
              <span className={`diag__log-stage diag__log-stage--${e.stage}`}>{e.stage}</span>
              <span>{e.service}</span>
              <span className="diag__log-delta">{e.delta_ms !== null ? `+${ms(e.delta_ms)}` : ""}</span>
            </p>
          ))
        )}
        <p className="diag__log-nota">
          A ordem é a registrada pela plataforma; o ritmo da animação, não. Os intervalos
          reais estão em ms. A trilha é best-effort: um marco ausente não prova falha.
        </p>
      </div>
    </section>
  );
}

function Conector({ ativo, rotulo }: { ativo: boolean; rotulo: string }) {
  return (
    <li className={`conector ${ativo ? "conector--ativo" : ""}`} aria-hidden="true">
      <span className="conector__linha"><span className="conector__pacote" /></span>
      <span className="conector__rotulo">{rotulo}</span>
    </li>
  );
}

function nomeDe(payload: Record<string, unknown>): string {
  const bruto = payload["full_name"] ?? payload["legal_name"];
  return typeof bruto === "string" && bruto.trim() ? bruto : "sem nome";
}

function Comparacao({
  resolvido,
  evidencia,
  par,
}: {
  resolvido: TrailEvent | undefined;
  evidencia: Evidence | undefined;
  par: [string, string] | null;
}) {
  if (!resolvido) {
    return <p className="cmp__vazio">aguardando a mensagem</p>;
  }
  const candidatos = resolvido.detail["candidates"];
  const matches = resolvido.detail["matches"];
  // O resumo e do registro que o desenho acompanha; o par pode ser outro registro do
  // mesmo lote. Sem dizer de quem e cada coisa, "0 correspondencias" ao lado de um
  // MATCH parece contradicao.
  const resumo = `registro acompanhado: ${typeof candidatos === "number" ? candidatos : "?"} candidatos · ${typeof matches === "number" ? matches : "?"} correspondências`;

  if (!evidencia) {
    return (
      <div className="cmp">
        <p className="cmp__resumo">{resumo}</p>
        <p className="cmp__vazio">Nenhum par associado neste lote — o resultado também é uma resposta.</p>
      </div>
    );
  }
  return (
    <div className="cmp">
      <p className="cmp__resumo">{resumo}</p>
      <p className="cmp__par">
        par associado no lote: <strong>{par?.[0]}</strong> × <strong>{par?.[1]}</strong>
      </p>
      <ul className="cmp__campos">
        {evidencia.fields.map((f, i) => (
          <li key={f.field} className="cmp__campo" style={{ ["--atraso" as string]: `${i * 140}ms` }}>
            <span className="cmp__nome">{ROTULOS[f.field] ?? f.field}</span>
            <span className="cmp__peso">{f.weight.toFixed(2)}</span>
            <span className="cmp__barra" aria-hidden="true">
              <span style={{ width: `${Math.round(f.score * 100)}%` }} />
            </span>
            <span className="cmp__nota">{f.score.toFixed(2)}</span>
          </li>
        ))}
      </ul>
      <p className={`cmp__decisao cmp__decisao--${evidencia.decision}`}>
        soma {evidencia.total.toFixed(3)} → {DECISAO[evidencia.decision]}
      </p>
    </div>
  );
}

function legendaDe(fase: string, proximo: Stage | undefined, resolvido: boolean, falta: boolean): string {
  if (fase === "inicio") return "Nada foi enviado ainda. O primeiro botão cria o lote; o segundo pede o processamento.";
  if (fase === "enviando") return "A API está validando e gravando o lote…";
  if (fase === "processando") return "Dispatcher publicando e worker consumindo…";
  if (fase === "erro") return "Algo deu errado neste passo.";
  if (resolvido) return "O worker terminou. A evidência acima é a que ficou gravada com a decisão.";
  if (falta) return "A fila é compartilhada e atende por ordem de chegada: este lote ainda não chegou à vez dele. Peça outro passo.";
  if (proximo === "published" || proximo === "consumed") return "O lote está gravado e a mensagem espera na fila. Nada acontece até alguém apertar “Processar agora”.";
  return "";
}
