/**
 * Fluxograma animado: o caminho de uma observacao pela plataforma.
 *
 * Uma figura, uma afirmacao — **o caminho e assincrono e nenhuma falha perde o
 * registro**. Por isso o desenho traz a transacao, a publicacao, a fila, o worker, a
 * recuperacao pelo outbox e a DLQ, e deixa de fora o que nao sustenta essa afirmacao:
 * idempotencia, resolucao e trilha tem explicacao propria logo abaixo, cada uma com o
 * seu desenho.
 *
 * O movimento carrega o que desenho parado nao carrega. Tres ideias do sistema sao
 * temporais — a mensagem que espera antes de ser consumida, o caminho de falha que so
 * acontece as vezes, e a rede de seguranca que so entra em acao quando a publicacao
 * direta falhou. Seta nao distingue "imediato" de "depois"; particula distingue.
 *
 * SVG escrito a mao, sem biblioteca e sem script: a animacao e SMIL (`animateMotion`),
 * nativa do formato. **Nada aqui le a API** — os numeros reais estao nas outras abas,
 * cada um com a origem rotulada.
 */

import { useState } from "react";

import "./Pipeline.css";

interface No {
  id: string;
  x: number;
  y: number;
  nome: string;
  papel: string;
  externo?: boolean;
  falha?: boolean;
}

const L = 136;
const A = 52;

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
  d: string;
  rotulo: string;
  rx: number;
  ry: number;
  ancora?: "start" | "middle" | "end";
  recuperacao?: boolean;
  falha?: boolean;
}

const ARESTAS: Aresta[] = [
  { d: "M146,62 H242", rotulo: "POST", rx: 194, ry: 52 },
  { d: "M386,62 H632", rotulo: "TransactWriteItems", rx: 509, ry: 52 },
  { d: "M300,88 V172", rotulo: "publica", rx: 292, ry: 136, ancora: "end" },
  {
    d: "M660,88 V140 H336 V172",
    rotulo: "outbox pendente, despachante recupera",
    rx: 500,
    ry: 132,
    recuperacao: true,
  },
  { d: "M386,206 H442", rotulo: "consome", rx: 414, ry: 196 },
  { d: "M586,206 H632", rotulo: "resolve", rx: 609, ry: 196 },
  { d: "M708,180 V96", rotulo: "vincula", rx: 716, ry: 140, ancora: "start" },
  { d: "M518,232 V312", rotulo: "3 falhas", rx: 526, ry: 276, ancora: "start", falha: true },
  { d: "M450,346 H286 V234", rotulo: "redrive", rx: 366, ry: 338, falha: true },
];

interface Particula {
  caminho: string;
  dur: string;
  inicio: string;
  /** Pausa no comeco do percurso: e a espera na fila, nao um atraso de animacao. */
  espera?: boolean;
  falha?: boolean;
}

const PARTICULAS: Particula[] = [
  { caminho: "M146,62 H242", dur: "1.7s", inicio: "0s" },
  { caminho: "M386,62 H632", dur: "2.1s", inicio: "0.5s" },
  { caminho: "M300,88 V172", dur: "1.5s", inicio: "1.1s" },
  { caminho: "M660,88 V140 H336 V172", dur: "3.4s", inicio: "2.6s" },
  { caminho: "M386,206 H442", dur: "3.2s", inicio: "1.6s", espera: true },
  { caminho: "M586,206 H632", dur: "1.4s", inicio: "2.4s" },
  { caminho: "M708,180 V96", dur: "1.8s", inicio: "3.1s" },
  { caminho: "M518,232 V312", dur: "2.2s", inicio: "0.2s", falha: true },
  { caminho: "M450,346 H286 V234", dur: "2.8s", inicio: "2.2s", falha: true },
];

function Caixa({ no }: { no: No }) {
  return (
    <g className={no.falha ? "flux__falha" : undefined}>
      <rect
        x={no.x}
        y={no.y}
        width={L}
        height={A}
        rx="9"
        className={`flux__caixa ${no.externo ? "flux__caixa--externa" : ""}`}
      />
      <text x={no.x + L / 2} y={no.y + 24} textAnchor="middle" className="flux__nome">
        {no.nome}
      </text>
      <text x={no.x + L / 2} y={no.y + 40} textAnchor="middle" className="flux__papel">
        {no.papel}
      </text>
    </g>
  );
}

export function Pipeline() {
  const [mostrarFalha, setMostrarFalha] = useState(false);

  return (
    <div className={`flux ${mostrarFalha ? "flux--com-falha" : ""}`}>
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
            <g key={a.rotulo} className={a.falha ? "flux__falha" : undefined}>
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
            <Caixa key={n.id} no={n} />
          ))}

          {PARTICULAS.map((p) => (
            <circle
              key={p.caminho + p.inicio}
              r="4.5"
              className={`flux__particula ${p.falha ? "flux__particula--erro" : ""} ${p.falha ? "flux__falha" : ""}`}
            >
              <animateMotion
                dur={p.dur}
                begin={p.inicio}
                repeatCount="indefinite"
                path={p.caminho}
                calcMode="linear"
                // A pausa no inicio do percurso e a espera na fila: a mensagem ja foi
                // publicada e ainda nao foi consumida. E o unico trecho do desenho em
                // que o correto e nao se mover.
                {...(p.espera
                  ? { keyTimes: "0;0.45;1", keyPoints: "0;0;1" }
                  : { keyTimes: "0;1", keyPoints: "0;1" })}
              />
            </circle>
          ))}
        </svg>
        </div>
        <figcaption className="flux__legenda">
          O caminho e assincrono de ponta a ponta, e nenhuma falha perde o registro. A
          transacao grava observacao e evento juntos — ou os dois, ou nenhum. A
          publicacao na fila e best-effort: quando ela falha, o evento continua pendente
          num indice esparso e o despachante o recupera. E se o processamento falhar
          tres vezes, a mensagem vai para a DLQ, onde fica visivel e devolvivel, em vez
          de sumir.
        </figcaption>
      </figure>

      <div className="flux__controles">
        <button
          type="button"
          className={`op op--${mostrarFalha ? "perigo" : "normal"}`}
          onClick={() => setMostrarFalha((v) => !v)}
        >
          {mostrarFalha ? "Ocultar o caminho de falha" : "Mostrar o caminho de falha"}
        </button>
      </div>

      <p className="flux__aviso">
        Este desenho explica o mecanismo; nao le o sistema. Nenhum numero aqui vem da
        API — os reais estao nas outras abas, cada um com a origem rotulada.
      </p>
    </div>
  );
}
