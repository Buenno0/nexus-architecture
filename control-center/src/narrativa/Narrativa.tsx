/**
 * A pagina publica.
 *
 * Abre com o par e o convite para o jogo. O envio de lotes e o pipeline etapa por
 * etapa ficam so na aba Arquitetura, para a mesma historia nao ser contada duas vezes.
 */

import { AoVivo } from "./AoVivo";
import { Autor } from "./Autor";
import { Decisoes } from "./Decisoes";
import { Medicoes } from "./Medicoes";
import { Pergunta } from "./Pergunta";
import "./narrativa.css";

const REPO = "https://github.com/Buenno0/nexus-architecture";

export function Narrativa({ abrirConsole }: { abrirConsole: () => void }) {
  return (
    <div className="narrativa">
      <header className="cabecalho">
        <div className="cabecalho__marca">
          <span className="cabecalho__nome">NEXUS</span>
          <span className="cabecalho__linha">Engenharia de sistemas distribuídos</span>
        </div>
        <nav className="cabecalho__links" aria-label="Links do projeto">
          <a className="cabecalho__jogar" href="#jogar">Jogar</a>
          <a href={REPO}>Repositório</a>
          <button type="button" className="elo" onClick={abrirConsole}>
            Painel técnico
          </button>
        </nav>
      </header>

      <main className="pagina">
        <Pergunta />
        <Decisoes />
        <Medicoes />
        <AoVivo abrirConsole={abrirConsole} />
        <Autor />
      </main>

      <footer className="rodape-narrativa">
        <p>
          Dados sintéticos: nenhum registro corresponde a pessoa real.
        </p>
      </footer>
    </div>
  );
}
