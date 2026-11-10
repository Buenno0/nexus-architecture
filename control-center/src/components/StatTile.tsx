/**
 * Card de metrica.
 *
 * Regra inegociavel: **quando nao ha valor, mostra `—`, nunca um numero**. Um zero no
 * lugar de "nao sei" e uma afirmacao falsa, e a secao 7 do projeto proibe apresentar
 * dado ficticio como metrica real.
 */

import "./StatTile.css";
import type { Origem } from "../api/types";
import { OriginBadge } from "./OriginBadge";

interface Props {
  rotulo: string;
  valor: number | string | null | undefined;
  origem: Origem;
  unidade?: string | undefined;
  /** Destaque visual quando o valor merece atencao, como DLQ acima de zero. */
  estado?: "normal" | "atencao" | "erro" | undefined;
  dica?: string | undefined;
  carregando?: boolean | undefined;
}

export function formatarValor(valor: number | string | null | undefined): string {
  if (valor === null || valor === undefined) return "—";
  if (typeof valor === "string") return valor;
  if (!Number.isFinite(valor)) return "—";
  if (Number.isInteger(valor)) return valor.toLocaleString("pt-BR");
  return valor.toLocaleString("pt-BR", { maximumFractionDigits: 2 });
}

export function StatTile({
  rotulo,
  valor,
  origem,
  unidade,
  estado = "normal",
  dica,
  carregando = false,
}: Props) {
  const vazio = valor === null || valor === undefined;
  const texto = carregando ? "…" : formatarValor(valor);
  // Identificadores e nomes de backend nao cabem no corpo usado para numeros.
  const longo = typeof valor === "string" && valor.length > 12;

  return (
    <div className={`tile tile--${estado}`} title={dica}>
      <div className="tile__cabecalho">
        <span className="tile__rotulo">{rotulo}</span>
        <OriginBadge origem={origem} />
      </div>
      <div
        className={`tile__valor numero ${vazio ? "tile__valor--vazio" : ""} ${
          longo ? "tile__valor--texto" : ""
        }`}
      >
        {texto}
        {!vazio && !carregando && unidade ? <span className="tile__unidade">{unidade}</span> : null}
      </div>
    </div>
  );
}
