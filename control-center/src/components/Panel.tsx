import "./Panel.css";
import type { ReactNode } from "react";

export function Panel({
  titulo,
  descricao,
  acoes,
  children,
}: {
  titulo: string;
  descricao?: string | undefined;
  acoes?: ReactNode | undefined;
  children: ReactNode;
}) {
  return (
    <section className="painel">
      <header className="painel__cabecalho">
        <div>
          <h2 className="painel__titulo">{titulo}</h2>
          {descricao ? <p className="painel__descricao">{descricao}</p> : null}
        </div>
        {acoes ? <div className="painel__acoes">{acoes}</div> : null}
      </header>
      {children}
    </section>
  );
}

export function Grade({ children, minimo = 170 }: { children: ReactNode; minimo?: number }) {
  return (
    <div
      className="grade"
      style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${minimo}px, 1fr))` }}
    >
      {children}
    </div>
  );
}
