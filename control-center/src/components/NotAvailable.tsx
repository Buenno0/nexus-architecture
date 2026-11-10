/**
 * Card para metrica que **nao existe** — e nao apenas esta indisponivel no momento.
 *
 * A secao 7 do projeto pede "workers em execucao". Esse numero nao tem significado
 * aqui: a execucao e sob demanda, o worker consome um lote e termina. Nao ha processo
 * residente para contar.
 *
 * Mostrar zero seria mentir; omitir o card faria a pergunta sumir sem resposta. O card
 * existe e explica.
 */

import "./NotAvailable.css";

interface Props {
  rotulo: string;
  explicacao: string;
}

export function NotAvailable({ rotulo, explicacao }: Props) {
  return (
    <div className="indisponivel">
      <div className="indisponivel__cabecalho">
        <span className="indisponivel__rotulo">{rotulo}</span>
        <span className="indisponivel__marca">nao se aplica</span>
      </div>
      <p className="indisponivel__explicacao">{explicacao}</p>
    </div>
  );
}
