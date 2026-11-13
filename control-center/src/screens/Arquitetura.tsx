/**
 * O que o visitante precisa saber antes de olhar um numero sequer.
 *
 * Cada linha e um mecanismo que a plataforma implementa e **o problema concreto que
 * ele resolve**. A ordem acompanha a jornada de uma observacao: chega, e gravada,
 * espera, e processada, e fica rastreavel.
 *
 * Os desenhos sao SVG escrito a mao, nao imagem: acompanham o tema, escalam sem
 * borrar, e o diff mostra qual seta mudou.
 */

import "./Arquitetura.css";
import { Panel } from "../components/Panel";
import { Pipeline } from "../components/Pipeline";

const BORDA = "var(--borda-forte)";
const CAIXA = "var(--superficie-alta)";

function Caixa({ x, y, rotulo }: { x: number; y: number; rotulo: string }) {
  return (
    <g>
      <rect x={x} y={y} width="54" height="34" rx="7" fill={CAIXA} stroke={BORDA} />
      <text x={x + 27} y={y + 21} textAnchor="middle" className="arq__rotulo">
        {rotulo}
      </text>
    </g>
  );
}

function Tracejado({ x1, y1, x2, y2 }: { x1: number; y1: number; x2: number; y2: number }) {
  return (
    <line x1={x1} y1={y1} x2={x2} y2={y2} stroke={BORDA} strokeWidth="1.4" strokeDasharray="2 4" />
  );
}

function Idempotencia() {
  return (
    <svg viewBox="0 0 360 96" className="arq__desenho" role="img" aria-label="Tres chamadas identicas produzem uma unica observacao">
      <Caixa x={6} y={14} rotulo="cliente" />
      <Caixa x={6} y={52} rotulo="cliente" />
      {/* Tres tentativas, uma so observacao: e a figura inteira do mecanismo. */}
      <path d="M62 31 C 150 31, 180 48, 236 48" fill="none" stroke={BORDA} strokeWidth="1.4" strokeDasharray="2 4" />
      <path d="M62 69 C 150 69, 180 50, 236 50" fill="none" stroke={BORDA} strokeWidth="1.4" strokeDasharray="2 4" />
      <text x={148} y={14} textAnchor="middle" className="arq__nota">mesma Idempotency-Key</text>
      <Caixa x={240} y={32} rotulo="registro" />
      <text x={267} y={82} textAnchor="middle" className="arq__nota">a 2a chamada devolve a 1a resposta</text>
    </svg>
  );
}

function Outbox() {
  return (
    <svg viewBox="0 0 360 96" className="arq__desenho" role="img" aria-label="Registro e evento gravados numa transacao unica">
      <rect x="18" y="22" width="178" height="56" rx="9" fill="none" stroke={BORDA} strokeDasharray="5 4" />
      <text x={107} y={16} textAnchor="middle" className="arq__nota">uma transacao</text>
      <Caixa x={30} y={34} rotulo="registro" />
      <Caixa x={118} y={34} rotulo="evento" />
      <Tracejado x1={200} y1={51} x2={248} y2={51} />
      <Caixa x={252} y={34} rotulo="fila" />
      <text x={107} y={90} textAnchor="middle" className="arq__nota">os dois, ou nenhum</text>
    </svg>
  );
}

function FilaDlq() {
  return (
    <svg viewBox="0 0 360 96" className="arq__desenho" role="img" aria-label="Fila com retentativa e dead letter queue">
      <Caixa x={6} y={16} rotulo="fila" />
      <Tracejado x1={64} y1={33} x2={240} y2={33} />
      {/* Unico elemento animado da tela: a mensagem que espera e segue. */}
      <circle cx="80" cy="33" r="3.5" fill="var(--info)" className="arq__fluxo" />
      <Caixa x={244} y={16} rotulo="worker" />
      <path d="M271 52 L 271 66" stroke={BORDA} strokeWidth="1.4" strokeDasharray="2 4" />
      <Caixa x={244} y={66} rotulo="DLQ" />
      <text x={238} y={78} textAnchor="end" className="arq__nota">apos 3 tentativas, com backoff</text>
    </svg>
  );
}

function Resolucao() {
  return (
    <svg viewBox="0 0 360 96" className="arq__desenho" role="img" aria-label="Score decide entre fundir, revisar ou nao fazer nada">
      <Caixa x={6} y={14} rotulo="obs. A" />
      <Caixa x={6} y={52} rotulo="obs. B" />
      <Tracejado x1={62} y1={31} x2={112} y2={44} />
      <Tracejado x1={62} y1={69} x2={112} y2={52} />
      <circle cx="136" cy="48" r="22" fill={CAIXA} stroke={BORDA} />
      <text x={136} y={52} textAnchor="middle" className="arq__rotulo">score</text>
      {[
        { y: 16, cor: "var(--ok)", texto: "funde" },
        { y: 44, cor: "var(--atencao)", texto: "revisao humana" },
        { y: 72, cor: "var(--neutro)", texto: "nada" },
      ].map((f) => (
        <g key={f.texto}>
          <Tracejado x1={160} y1={48} x2={212} y2={f.y + 4} />
          <circle cx="218" cy={f.y + 4} r="4" fill={f.cor} />
          <text x={230} y={f.y + 8} className="arq__nota">{f.texto}</text>
        </g>
      ))}
    </svg>
  );
}

function Trilha() {
  return (
    <svg viewBox="0 0 360 96" className="arq__desenho" role="img" aria-label="A trilha registra marcos emitidos por dois processos diferentes">
      <text x={4} y={28} className="arq__rotulo">api</text>
      <text x={4} y={76} className="arq__rotulo">worker</text>
      <line x1="38" y1="22" x2="348" y2="22" stroke={BORDA} strokeWidth="1.4" />
      <line x1="38" y1="70" x2="348" y2="70" stroke={BORDA} strokeWidth="1.4" />
      {[
        { x: 60, t: "accepted" },
        { x: 132, t: "published" },
      ].map((m) => (
        <g key={m.t}>
          <circle cx={m.x} cy="22" r="4" fill="var(--origem-persistido)" />
          <text x={m.x} y="12" textAnchor="middle" className="arq__nota">{m.t}</text>
        </g>
      ))}
      {[
        { x: 232, t: "consumed" },
        { x: 316, t: "resolved" },
      ].map((m) => (
        <g key={m.t}>
          <circle cx={m.x} cy="70" r="4" fill="var(--origem-persistido)" />
          <text x={m.x} y="88" textAnchor="middle" className="arq__nota">{m.t}</text>
        </g>
      ))}
      {/* O intervalo entre os dois processos e o que a trilha torna visivel. */}
      <path d="M132 30 L 132 46 L 232 46 L 232 62" fill="none" stroke={BORDA} strokeWidth="1.4" strokeDasharray="3 3" />
      <text x={182} y={42} textAnchor="middle" className="arq__nota">espera na fila</text>
    </svg>
  );
}

const MECANISMOS = [
  {
    nome: "Idempotencia",
    legenda: "A mesma chamada, uma unica observacao.",
    porque:
      "Cliente que nao recebe resposta tenta de novo. Sem isto, uma falha de rede vira dado duplicado — e ninguem percebe, porque do lado de fora nada falhou.",
    desenho: <Idempotencia />,
  },
  {
    nome: "Transactional outbox",
    legenda: "Ou grava os dois, ou nenhum.",
    porque:
      "Gravar no banco e publicar na fila sao duas operacoes. Um crash no meio deixa o registro salvo e nunca processado — invisivel. A transacao grava registro e evento juntos; um despachante publica depois.",
    desenho: <Outbox />,
  },
  {
    nome: "Fila, retentativa e DLQ",
    legenda: "Falha nao desaparece em silencio.",
    porque:
      "A entrega e at-least-once por construcao. Mensagem que falha volta com espera crescente e, esgotadas as tentativas, vai para a DLQ — onde fica visivel e devolvivel, em vez de sumir.",
    desenho: <FilaDlq />,
  },
  {
    nome: "Resolucao de identidade",
    legenda: "Em duvida, nao funde.",
    porque:
      "Fundir duas pessoas distintas corrompe dados de forma dificil de detectar e de reverter. Por isso tres faixas, nao duas: o caso duvidoso fica pendente de decisao humana em vez de virar um palpite silencioso.",
    desenho: <Resolucao />,
  },
  {
    nome: "Trilha",
    legenda: "A jornada atravessa processos.",
    porque:
      "API e worker sao processos diferentes, com logs diferentes. A trilha junta os marcos num lugar so — e o intervalo entre eles separa 'o processamento esta lento' de 'a fila esta acumulando', diagnosticos opostos.",
    desenho: <Trilha />,
  },
];

export function Arquitetura() {
  return (
    <>
      <div className="arq__intro">
        <h2 className="arq__titulo">Como uma observacao atravessa o Nexus</h2>
        <p className="arq__sub">
          Cinco mecanismos, cada um respondendo a um problema concreto de sistemas
          distribuidos. As demais abas mostram esses mecanismos funcionando com dados
          reais — sinteticos, gerados pelo proprio servidor.
        </p>
      </div>

      <Panel
        titulo="O caminho de uma observacao"
        descricao="Aperte play e acompanhe uma requisicao atravessando a plataforma. O ramo de falha so acende quando a requisicao passa por ele — desenhar os dois com o mesmo peso diria que falhar e tao comum quanto dar certo."
      >
        <Pipeline />
      </Panel>

      <Panel
        titulo="Mecanismos"
        descricao="Na ordem em que um registro os encontra."
      >
        {MECANISMOS.map((m) => (
          <div className="arq__linha" key={m.nome}>
            <div>
              <h3 className="arq__nome">{m.nome}</h3>
              <p className="arq__legenda">{m.legenda}</p>
              <p className="arq__porque">{m.porque}</p>
            </div>
            {m.desenho}
          </div>
        ))}
      </Panel>
    </>
  );
}
