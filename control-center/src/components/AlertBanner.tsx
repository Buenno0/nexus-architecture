/**
 * Faixa de alertas, visivel em todas as telas — ADR-010.
 *
 * As condicoes sao avaliadas no servidor, a partir do estado real, a cada chamada.
 * Duplicar os limiares aqui faria a faixa divergir do backend no primeiro ajuste de
 * configuracao, e a tela passaria a afirmar algo que a plataforma nao afirma.
 *
 * Cada alerta mostra a origem do numero que o acendeu, pela mesma regra do ADR-009:
 * um alerta de taxa de erro que some sozinho ao reiniciar a API precisa dizer isso.
 */

import "./AlertBanner.css";
import type { Alert } from "../api/types";
import { OriginBadge } from "./OriginBadge";

export function AlertBanner({
  alertas,
  erro,
}: {
  alertas: readonly Alert[] | undefined;
  erro?: boolean | undefined;
}) {
  // Falha ao consultar nao e "tudo certo". Silencio aqui seria indistinguivel de
  // plataforma saudavel, que e o pior resultado possivel para um painel de operacao.
  if (erro) {
    return (
      <div className="faixa faixa--desconhecida">
        <span className="faixa__marca">alertas indisponiveis</span>
        <span className="faixa__texto">
          Nao foi possivel avaliar as condicoes. Isto nao significa que esta tudo bem.
        </span>
      </div>
    );
  }

  if (!alertas || alertas.length === 0) return null;

  return (
    <div className="faixa-lista">
      {alertas.map((a) => (
        <div key={a.id} className={`faixa faixa--${a.severity}`}>
          <span className="faixa__marca">{a.severity === "error" ? "erro" : "atencao"}</span>
          <div className="faixa__corpo">
            <span className="faixa__titulo">{a.title}</span>
            <span className="faixa__texto">{a.detail}</span>
          </div>
          <OriginBadge origem={a.origin} />
        </div>
      ))}
    </div>
  );
}
