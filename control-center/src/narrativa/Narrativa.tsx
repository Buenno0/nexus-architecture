/**
 * A pagina publica.
 *
 * Uma rolagem, sem abas. Quem chega nao escolhe por onde comecar — a pagina conduz.
 * O painel de operador continua inteiro, atras do link do rodape.
 *
 * As secoes 4 a 7 do plano ainda nao existem; enquanto isso, o fecho leva ao
 * repositorio e ao console para que a pagina nao termine num precipicio.
 */

import { Decisao } from "./Decisao";
import { Jornada } from "./Jornada";
import { Pergunta } from "./Pergunta";
import { useJornada } from "./useJornada";
import "./narrativa.css";

const REPO = "https://github.com/Buenno0/nexus-architecture";

export function Narrativa({ abrirConsole }: { abrirConsole: () => void }) {
  // O estado vive aqui porque as secoes 2 e 3 contam a mesma historia: a 3 explica a
  // decisao sobre o lote que a 2 enviou.
  const jornada = useJornada();

  return (
    <div className="narrativa">
      <header className="cabecalho">
        <div className="cabecalho__marca">
          <span className="cabecalho__nome">NEXUS</span>
          <span className="cabecalho__linha">Engenharia de sistemas distribuídos</span>
        </div>
        <nav className="cabecalho__links" aria-label="Links do projeto">
          <a href={REPO}>Repositório</a>
          <button type="button" className="elo" onClick={abrirConsole}>
            Painel técnico
          </button>
        </nav>
      </header>

      <main className="pagina">
        <Pergunta />
        <Jornada estado={jornada} />
        <Decisao estado={jornada} />
      </main>

      <footer className="rodape-narrativa">
        <p>
          Um projeto de Mateus Bueno. Os dados desta página são sintéticos: nenhum
          registro corresponde a pessoa real.
        </p>
        <p className="rodape-narrativa__links">
          <a href={REPO}>Ver o código</a>
          <button type="button" className="elo" onClick={abrirConsole}>
            Abrir o painel técnico
          </button>
        </p>
      </footer>
    </div>
  );
}
