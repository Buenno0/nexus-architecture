/**
 * Os icones das quatro etapas, desenhados para o que cada uma FAZ — nao para o tipo
 * de servico. Um cilindro diz "banco de dados" em qualquer painel do mundo; aqui o
 * armazenamento mostra as duas linhas que a mesma transacao grava, porque e isso que
 * o Nexus faz de diferente.
 *
 * Todos animam pelo estado da etapa (classes em JornadaViva.css), nunca por conta
 * propria: um icone que mexe sem evento por tras estaria mentindo sobre o sistema.
 */

type Estado = "parado" | "agindo" | "feito";

function Moldura({ estado, children, rotulo }: { estado: Estado; children: React.ReactNode; rotulo: string }) {
  return (
    <svg
      viewBox="0 0 48 48"
      className={`icone icone--${estado}`}
      role="img"
      aria-label={rotulo}
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {children}
    </svg>
  );
}

/** API: uma porta. O pedido entra pela esquerda, passa pela validacao e e aceito. */
export function IconeApi({ estado }: { estado: Estado }) {
  return (
    <Moldura estado={estado} rotulo="Porta de entrada que valida e aceita o pedido">
      <path d="M30 8v32" />
      <path d="M30 8h8v32h-8" opacity=".45" />
      <path className="icone__pedido" d="M6 24h18m-5-5 5 5-5 5" />
      <path className="icone__aceite" d="M32.5 24l2.5 2.5 4.5-5" />
    </Moldura>
  );
}

/** Armazenamento: uma tabela onde DUAS linhas acendem juntas — registro e evento. */
export function IconeArmazenamento({ estado }: { estado: Estado }) {
  return (
    <Moldura estado={estado} rotulo="Tabela com registro e evento gravados na mesma transacao">
      <rect x="7" y="9" width="34" height="30" rx="3" />
      <path d="M7 17h34" opacity=".45" />
      <rect className="icone__linha icone__linha--a" x="11" y="21" width="26" height="6" rx="1.5" />
      <rect className="icone__linha icone__linha--b" x="11" y="30" width="26" height="6" rx="1.5" />
      {/* O colchete diz "estas duas, juntas" — a transacao. */}
      <path className="icone__tx" d="M44 21v15" />
    </Moldura>
  );
}

/** Fila: bandejas empilhadas. A de cima sai quando o worker consome. */
export function IconeFila({ estado }: { estado: Estado }) {
  return (
    <Moldura estado={estado} rotulo="Fila com mensagens empilhadas esperando consumo">
      <path d="M8 38h32" opacity=".45" />
      <rect x="10" y="30" width="28" height="6" rx="1.5" opacity=".45" />
      <rect x="10" y="22" width="28" height="6" rx="1.5" opacity=".7" />
      <rect className="icone__mensagem" x="10" y="14" width="28" height="6" rx="1.5" />
    </Moldura>
  );
}

/** Worker: dois cartoes que se aproximam para serem comparados campo a campo. */
export function IconeWorker({ estado }: { estado: Estado }) {
  return (
    <Moldura estado={estado} rotulo="Dois registros sendo comparados campo a campo">
      <g className="icone__cartao icone__cartao--a">
        <rect x="5" y="12" width="16" height="22" rx="2.5" />
        <path d="M9 18h8M9 23h6M9 28h7" opacity=".6" />
      </g>
      <g className="icone__cartao icone__cartao--b">
        <rect x="27" y="12" width="16" height="22" rx="2.5" />
        <path d="M31 18h8M31 23h6M31 28h7" opacity=".6" />
      </g>
      <path className="icone__igual" d="M21.5 21h5M21.5 25h5" />
    </Moldura>
  );
}

export type { Estado as EstadoIcone };
