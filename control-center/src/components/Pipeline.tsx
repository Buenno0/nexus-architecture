/**
 * O visitante aperta play e acompanha **uma** requisicao atravessando a plataforma.
 *
 * Uma figura, uma afirmacao: o caminho e assincrono e nenhuma falha perde o registro.
 * O desenho traz a transacao, a publicacao, a fila, o worker, a recuperacao pelo
 * outbox e a DLQ — e deixa de fora o que nao sustenta essa afirmacao. Idempotencia,
 * resolucao e trilha tem explicacao e desenho proprios logo abaixo.
 *
 * Por que acionado em vez de animado em laco: particula correndo sozinha o tempo todo
 * e ambiente, nao evento. O que o sistema faz e atender **uma** requisicao, e quem
 * olha precisa poder seguir aquela — ver onde ela para, quanto tempo espera, e para
 * onde ela vai quando falha.
 *
 * O token anda pelos mesmos vertices das arestas desenhadas; nao ha caminho invisivel.
 * A pausa na fila nao e atraso de animacao: e o intervalo entre `published` e
 * `consumed`, que e o que separa "processamento lento" de "fila acumulando".
 *
 * **Nada aqui le a API** — os numeros reais estao nas outras abas, com a origem
 * rotulada em cada um.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import "./Pipeline.css";

const L = 136;
const A = 52;

interface No {
  id: string;
  x: number;
  y: number;
  nome: string;
  papel: string;
  externo?: boolean;
  falha?: boolean;
}

const NOS: No[] = [
  { id: "cliente", x: 10, y: 36, nome: "cliente", papel: "FONTE", externo: true },
  { id: "api", x: 250, y: 36, nome: "API", papel: "INGESTAO" },
  { id: "dynamo", x: 640, y: 36, nome: "DynamoDB", papel: "ARMAZENAMENTO" },
  { id: "fila", x: 250, y: 180, nome: "fila", papel: "SQS" },
  { id: "worker", x: 450, y: 180, nome: "worker", papel: "CONSUMO" },
  { id: "resolucao", x: 640, y: 180, nome: "resolucao", papel: "IDENTIDADE" },
  { id: "dlq", x: 450, y: 320, nome: "DLQ", papel: "FALHA", falha: true },
];

interface Aresta {
  id: string;
  d: string;
  rotulo: string;
  rx: number;
  ry: number;
  ancora?: "start" | "middle" | "end";
  recuperacao?: boolean;
  falha?: boolean;
}

/** Os vertices aqui sao os mesmos por onde o token anda. */
const ARESTAS: Aresta[] = [
  { id: "post", d: "M146,62 H242", rotulo: "POST", rx: 194, ry: 52 },
  { id: "transacao", d: "M386,62 H632", rotulo: "TransactWriteItems", rx: 509, ry: 52 },
  { id: "publica", d: "M318,88 V172", rotulo: "publica", rx: 310, ry: 136, ancora: "end" },
  {
    id: "recupera",
    d: "M670,88 V150 H290 V172",
    rotulo: "outbox pendente, despachante recupera",
    rx: 505,
    ry: 142,
    recuperacao: true,
  },
  { id: "consome", d: "M386,206 H442", rotulo: "consome", rx: 414, ry: 196 },
  { id: "resolve", d: "M586,206 H632", rotulo: "resolve", rx: 609, ry: 196 },
  { id: "vincula", d: "M708,180 V96", rotulo: "vincula", rx: 716, ry: 140, ancora: "start" },
  { id: "falhou", d: "M518,232 V312", rotulo: "3 falhas", rx: 526, ry: 276, ancora: "start", falha: true },
  { id: "redrive", d: "M450,346 H200 V206 H242", rotulo: "redrive", rx: 330, ry: 338, falha: true },
];

interface Passo {
  x: number;
  y: number;
  /** Duracao do deslocamento ate este ponto. 0 em pausas. */
  dur: number;
  /** Tempo parado depois de chegar. */
  pausa: number;
  no?: string;
  aresta?: string;
  titulo?: string;
  texto?: string;
  espera?: boolean;
  erro?: boolean;
}

const INICIO: Passo = {
  x: 78,
  y: 62,
  dur: 0,
  pausa: 700,
  no: "cliente",
  titulo: "A requisicao sai do cliente",
  texto:
    "Um registro sintetico, com um cabecalho Idempotency-Key proprio. A mesma chave nunca produz duas observacoes.",
};

const ATE_A_FILA: Passo[] = [
  INICIO,
  {
    x: 318,
    y: 62,
    dur: 850,
    pausa: 1100,
    no: "api",
    aresta: "post",
    titulo: "POST /v1/records/person",
    texto:
      "A validacao acontece na borda: payload invalido para aqui, com 422, e nunca alcanca a persistencia.",
  },
  {
    x: 318,
    y: 62,
    dur: 0,
    pausa: 1500,
    no: "dynamo",
    aresta: "transacao",
    titulo: "TransactWriteItems",
    texto:
      "Observacao, evento de outbox e registro de idempotencia numa transacao unica. Ou os tres existem, ou nenhum — e o que impede o registro salvo e nunca processado.",
  },
  {
    x: 318,
    y: 206,
    dur: 800,
    pausa: 1800,
    no: "fila",
    aresta: "publica",
    titulo: "Publicado — e agora espera",
    texto:
      "A publicacao e best-effort: se falhasse, o evento continuaria pendente no indice esparso e o despachante o recuperaria. Agora a mensagem aguarda, e e este intervalo que separa 'processamento lento' de 'fila acumulando'.",
    espera: true,
  },
  {
    x: 518,
    y: 206,
    dur: 800,
    pausa: 900,
    no: "worker",
    aresta: "consome",
    titulo: "Outro processo consome",
    texto:
      "Worker le o lote. Antes de processar, consulta o marcador: reentrega encontra o marcador e nao processa de novo. A entrega e at-least-once por construcao.",
  },
];

const FELIZ: Passo[] = [
  ...ATE_A_FILA,
  {
    x: 708,
    y: 206,
    dur: 800,
    pausa: 1100,
    no: "resolucao",
    aresta: "resolve",
    titulo: "Resolucao de identidade",
    texto:
      "Blocking seleciona candidatos, o score compara campo a campo e a decisao tem tres faixas. Em duvida vai para revisao humana — nunca funde no palpite.",
  },
  {
    x: 708,
    y: 62,
    dur: 850,
    pausa: 1400,
    no: "dynamo",
    aresta: "vincula",
    titulo: "Vinculo gravado",
    texto:
      "A observacao permanece imutavel; o que foi criado e o vinculo a entidade canonica, com a evidencia que o justifica.",
  },
];

const COM_FALHA: Passo[] = [
  ...ATE_A_FILA,
  {
    x: 518,
    y: 346,
    dur: 850,
    pausa: 1400,
    no: "dlq",
    aresta: "falhou",
    titulo: "Tres tentativas, e a DLQ",
    texto:
      "O processamento falha. A mensagem volta a fila com espera crescente e, esgotadas as tentativas, sai do caminho quente para a DLQ — onde fica visivel, inspecionavel e devolvivel. Um alerta acende sozinho.",
    erro: true,
  },
  { x: 200, y: 346, dur: 700, pausa: 0, aresta: "redrive", erro: true },
  { x: 200, y: 206, dur: 500, pausa: 0, erro: true },
  {
    x: 318,
    y: 206,
    dur: 500,
    pausa: 1400,
    no: "fila",
    titulo: "Redrive: de volta a fila",
    texto:
      "Um redrive explicito devolve a mensagem para a mesma fila de onde ela saiu. Nada se perdeu — o registro continua la, esperando ser processado de novo.",
  },
];

export function Pipeline() {
  const [roteiro, setRoteiro] = useState<Passo[] | null>(null);
  const [i, setI] = useState(0);
  const [rodando, setRodando] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  const parar = useCallback(() => {
    if (timer.current !== undefined) window.clearTimeout(timer.current);
    timer.current = undefined;
  }, []);

  useEffect(() => {
    if (!roteiro) return;
    const passo = roteiro[i];
    if (!passo) return;
    if (i === roteiro.length - 1) {
      timer.current = window.setTimeout(() => setRodando(false), passo.dur + passo.pausa);
      return parar;
    }
    timer.current = window.setTimeout(() => setI((n) => n + 1), passo.dur + passo.pausa);
    return parar;
  }, [i, roteiro, parar]);

  useEffect(() => parar, [parar]);

  function tocar(novo: Passo[]) {
    parar();
    setRoteiro(novo);
    setI(0);
    setRodando(true);
  }

  const passo = roteiro?.[i];
  // O rotulo nao muda em passo de vertice: so quando ha algo novo a dizer.
  const legenda = roteiro
    ? [...roteiro.slice(0, i + 1)].reverse().find((p) => p.titulo)
    : undefined;
  const comFalha = roteiro === COM_FALHA;

  return (
    <div className={`flux ${comFalha ? "flux--com-falha" : ""}`}>
      <div className="flux__controles">
        <button type="button" className="op op--normal" onClick={() => tocar(FELIZ)} disabled={rodando}>
          {rodando && !comFalha ? "em curso…" : "▶ Enviar uma requisicao"}
        </button>
        <button type="button" className="op op--perigo" onClick={() => tocar(COM_FALHA)} disabled={rodando}>
          {rodando && comFalha ? "em curso…" : "▶ Com falha no processamento"}
        </button>
      </div>

      <figure>
        <p className="flux__rolar">Arraste o desenho para o lado para ver o fluxo inteiro.</p>
        <div className="flux__rolagem">
          <svg
            viewBox="0 0 980 400"
            className="flux__svg"
            role="img"
            aria-label="Fluxograma: o cliente chama a API, que grava registro e evento numa unica transacao e publica na fila; o worker consome e resolve a identidade. Se a publicacao falhar, o despachante recupera o evento pendente; se o processamento falhar tres vezes, a mensagem vai para a DLQ e volta por redrive."
          >
            <defs>
              <marker id="flux-seta" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M0,0 L8,4 L0,8 z" fill="currentColor" />
              </marker>
            </defs>

            {ARESTAS.map((a) => (
              <g
                key={a.id}
                className={[
                  a.falha ? "flux__falha" : "",
                  passo?.aresta === a.id ? "flux__ativa" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
              >
                <path
                  d={a.d}
                  className={`flux__aresta ${a.recuperacao ? "flux__aresta--recuperacao" : ""}`}
                  markerEnd="url(#flux-seta)"
                />
                <text x={a.rx} y={a.ry} textAnchor={a.ancora ?? "middle"} className="flux__rotulo">
                  {a.rotulo}
                </text>
              </g>
            ))}

            {NOS.map((n) => (
              <g
                key={n.id}
                className={[n.falha ? "flux__falha" : "", passo?.no === n.id ? "flux__ativa" : ""]
                  .filter(Boolean)
                  .join(" ")}
              >
                <rect
                  x={n.x}
                  y={n.y}
                  width={L}
                  height={A}
                  rx="9"
                  className={`flux__caixa ${n.externo ? "flux__caixa--externa" : ""}`}
                />
                <text x={n.x + L / 2} y={n.y + 24} textAnchor="middle" className="flux__nome">
                  {n.nome}
                </text>
                <text x={n.x + L / 2} y={n.y + 40} textAnchor="middle" className="flux__papel">
                  {n.papel}
                </text>
              </g>
            ))}

            {passo && (
              <circle
                r="7"
                className={[
                  "flux__token",
                  passo.espera ? "flux__token--espera" : "",
                  passo.erro ? "flux__token--erro" : "",
                ]
                  .filter(Boolean)
                  .join(" ")}
                style={{
                  transform: `translate(${passo.x}px, ${passo.y}px)`,
                  transitionDuration: `${passo.dur}ms`,
                }}
              />
            )}
          </svg>
        </div>
        <figcaption className="flux__legenda" aria-live="polite">
          {legenda ? (
            <>
              <strong className="flux__legenda-titulo">{legenda.titulo}</strong>
              {legenda.texto}
            </>
          ) : (
            "Aperte um dos botoes acima e acompanhe a requisicao. O caminho e assincrono de ponta a ponta, e nenhuma falha perde o registro."
          )}
        </figcaption>
      </figure>

      <p className="flux__aviso">
        Este desenho explica o mecanismo; nao le o sistema. Nenhum numero aqui vem da
        API — os reais estao nas outras abas, cada um com a origem rotulada.
      </p>
    </div>
  );
}
