/**
 * Rotulo de origem do dado — ADR-009.
 *
 * Os numeros do Nexus vem de tres lugares, com garantias diferentes. Apresenta-los
 * lado a lado sem dizer qual e qual seria enganoso: uma profundidade de fila persistida
 * e uma afirmacao bem mais forte que um contador que zera no reinicio da API.
 */

import "./OriginBadge.css";
import type { Origem } from "../api/types";

const DESCRICAO: Record<Origem, { curto: string; titulo: string }> = {
  persistido: {
    curto: "persistido",
    titulo:
      "Vem do armazenamento ou de um servico de fila. Valores do SQS sao aproximados.",
  },
  processo: {
    curto: "processo",
    titulo:
      "Contador em memoria da API. Zera a cada reinicio e nao agrega entre replicas.",
  },
  sessao: {
    curto: "sessao",
    titulo:
      "Acumulado neste navegador desde que a pagina abriu. Recarregar zera a serie.",
  },
};

export function OriginBadge({ origem }: { origem: Origem }) {
  const info = DESCRICAO[origem];
  return (
    <span className={`origem origem--${origem}`} title={info.titulo}>
      {info.curto}
    </span>
  );
}
