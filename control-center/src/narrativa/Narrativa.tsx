/**
 * A pagina publica.
 *
 * Uma rolagem, sem abas. Quem chega nao escolhe por onde comecar — a pagina conduz.
 * O painel de operador continua inteiro, atras do link da secao 6.
 */

import { AoVivo } from "./AoVivo";
import { Autor } from "./Autor";
import { Decisao } from "./Decisao";
import { Decisoes } from "./Decisoes";
import { Medicoes } from "./Medicoes";
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
        <Decisoes />
        <Medicoes />
        <AoVivo abrirConsole={abrirConsole} />
        <Autor />
      </main>

      {/* A autoria e os links agora vivem na secao 7. O rodape fica so com a
          ressalva que precisa acompanhar a pagina inteira. */}
      <footer className="rodape-narrativa">
        <p>
          Todos os dados desta página são sintéticos: nenhum registro corresponde a
          pessoa real. A demonstração grava de verdade, num acervo criado para ela.
        </p>
      </footer>
    </div>
  );
}
