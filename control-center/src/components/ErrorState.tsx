/**
 * Estado de falha.
 *
 * Mostra o `correlation_id` porque e ele que liga o que apareceu na tela a trilha de
 * log do servidor. Sem ele, "deu erro" e tudo que sobra.
 *
 * Importante: a tela que falha mostra **isto**, nunca o ultimo numero conhecido. Um
 * valor velho apresentado como atual e pior que nenhum valor.
 */

import "./ErrorState.css";
import { NexusApiError } from "../api/client";

export function ErrorState({
  erro,
  onTentarNovamente,
}: {
  erro: unknown;
  onTentarNovamente?: (() => void) | undefined;
}) {
  const api = erro instanceof NexusApiError ? erro : null;
  const mensagem = erro instanceof Error ? erro.message : "Falha desconhecida";

  return (
    <div className="falha" role="alert">
      <div className="falha__titulo">
        {api ? `${api.status} ${api.code}` : "Sem resposta da API"}
      </div>
      <p className="falha__mensagem">{mensagem}</p>
      {api?.correlationId ? (
        <p className="falha__correlacao">
          correlation_id <code className="numero">{api.correlationId}</code>
        </p>
      ) : (
        <p className="falha__correlacao">
          A API nao respondeu. Verifique se a stack esta no ar: <code>make up</code>
        </p>
      )}
      {onTentarNovamente ? (
        <button type="button" className="falha__acao" onClick={onTentarNovamente}>
          Tentar novamente
        </button>
      ) : null}
    </div>
  );
}
