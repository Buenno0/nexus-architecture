/**
 * "Mesma pessoa?" — o visitante julga um par real antes de ver o que o Nexus decidiu.
 *
 * Texto curto de proposito: a explicacao e a revelacao, nao um paragrafo antes dela.
 */

import { useEffect, useState } from "react";

import type { Evidence, FieldScore } from "../api/types";
import { montarRodadas, TOTAL, type Resposta, type Rodada } from "./rodadas";
import "./jogo.css";

const REPO = "https://github.com/Buenno0/nexus-architecture";
const LIMIAR_DUVIDA = 0.65;
const LIMIAR_MATCH = 0.85;

const CAMPOS: Record<string, string> = {
  full_name: "Nome",
  legal_name: "Razão social",
  email: "E-mail",
  phone: "Telefone",
  document: "Documento",
};

const OPCOES: { valor: Resposta; rotulo: string; tecla: string }[] = [
  { valor: "mesma", rotulo: "Mesma pessoa", tecla: "1" },
  { valor: "duvida", rotulo: "Não dá para ter certeza", tecla: "2" },
  { valor: "diferentes", rotulo: "Pessoas diferentes", tecla: "3" },
];

const VEREDITO: Record<Resposta, string> = {
  mesma: "Mesma pessoa — associou sozinho",
  duvida: "Em dúvida — mandou para um humano",
  diferentes: "Pessoas diferentes — manteve separados",
};

type Fase = "carregando" | "vazio" | "jogando" | "fim";

export function Jogo({ sair }: { sair: () => void }) {
  const [fase, setFase] = useState<Fase>("carregando");
  const [rodadas, setRodadas] = useState<Rodada[]>([]);
  const [i, setI] = useState(0);
  const [palpites, setPalpites] = useState<Resposta[]>([]);

  const carregar = () => {
    setFase("carregando");
    setI(0);
    setPalpites([]);
    void montarRodadas()
      .then((r) => { setRodadas(r); setFase(r.length ? "jogando" : "vazio"); })
      .catch(() => setFase("vazio"));
  };
  useEffect(carregar, []);

  const rodada = rodadas[i];
  const palpite = palpites[i];
  const acertos = palpites.filter((p, k) => p === rodadas[k]?.resposta).length;

  const escolher = (r: Resposta) => { if (!palpite) setPalpites((p) => [...p, r]); };
  const seguir = () => (i + 1 < rodadas.length ? setI(i + 1) : setFase("fim"));

  useEffect(() => {
    const tecla = (e: KeyboardEvent) => {
      if (fase !== "jogando") return;
      const op = OPCOES.find((o) => o.tecla === e.key);
      if (op && !palpite) escolher(op.valor);
      if (e.key === "Enter" && palpite) seguir();
    };
    window.addEventListener("keydown", tecla);
    return () => window.removeEventListener("keydown", tecla);
  });

  return (
    <div className="jogo">
      <header className="jogo__topo">
        <button type="button" className="jogo__marca" onClick={sair}>NEXUS</button>
        {fase === "jogando" && (
          <ol className="jogo__progresso" aria-label={`Rodada ${i + 1} de ${rodadas.length}`}>
            {rodadas.map((r, k) => (
              <li
                key={r.id}
                className={
                  k < palpites.length
                    ? palpites[k] === r.resposta ? "acertou" : "errou"
                    : k === i ? "atual" : ""
                }
              />
            ))}
          </ol>
        )}
      </header>

      {fase === "carregando" && <p className="jogo__aviso">Buscando pares que o Nexus já julgou…</p>}

      {fase === "vazio" && (
        <div className="jogo__aviso">
          <p>Ainda não há pares julgados no acervo.</p>
          <button type="button" className="jogo__botao" onClick={sair}>Voltar</button>
        </div>
      )}

      {fase === "jogando" && rodada && (
        <main className="jogo__mesa" key={rodada.id}>
          <h1 className="jogo__pergunta">São a mesma pessoa?</h1>

          <Cartoes evidencia={rodada.evidencia} revelado={Boolean(palpite)} />

          {!palpite ? (
            <div className="jogo__opcoes">
              {OPCOES.map((o) => (
                <button key={o.valor} type="button" className={`jogo__opcao jogo__opcao--${o.valor}`} onClick={() => escolher(o.valor)}>
                  <kbd>{o.tecla}</kbd>{o.rotulo}
                </button>
              ))}
            </div>
          ) : (
            <Revelacao evidencia={rodada.evidencia} palpite={palpite} certo={rodada.resposta} seguir={seguir} ultima={i + 1 === rodadas.length} />
          )}
        </main>
      )}

      {fase === "fim" && (
        <main className="jogo__fim">
          <p className="jogo__placar"><strong>{acertos}</strong>/{rodadas.length}</p>
          <h1 className="jogo__pergunta">
            {acertos === rodadas.length ? "Você pensa como o Nexus." : acertos >= rodadas.length / 2 ? "Quase lá." : "Difícil, né?"}
          </h1>
          <p className="jogo__texto">
            Cada par veio de dados reais da plataforma. O Nexus compara campo a campo, soma com peso e,
            quando fica no meio, não chuta: pede uma pessoa.
          </p>
          <div className="jogo__acoes">
            <button type="button" className="jogo__botao" onClick={carregar}>Jogar de novo</button>
            <button type="button" className="jogo__botao jogo__botao--sec" onClick={sair}>Ver como funciona</button>
            <a className="jogo__botao jogo__botao--sec" href={REPO}>Código</a>
          </div>
          <p className="jogo__autor">Feito por Mateus Bueno · Python, AWS serverless, React</p>
        </main>
      )}
      {fase === "jogando" && <p className="jogo__rodape">{TOTAL} pares reais · teclas 1, 2, 3 e Enter</p>}
    </div>
  );
}

function Cartoes({ evidencia, revelado }: { evidencia: Evidence; revelado: boolean }) {
  return (
    <div className="cartoes">
      {(["left", "right"] as const).map((lado, n) => (
        <article key={lado} className={`cartao cartao--${lado}`}>
          <p className="cartao__fonte">Registro {n === 0 ? "A" : "B"}</p>
          <dl>
            {evidencia.fields.map((f) => (
              <div key={f.field} className={`cartao__campo ${revelado ? `cartao__campo--${faixa(f)}` : ""}`}>
                <dt>{CAMPOS[f.field] ?? f.field}</dt>
                <dd>{f[lado] ?? "—"}</dd>
              </div>
            ))}
          </dl>
        </article>
      ))}
    </div>
  );
}

function faixa(f: FieldScore): "igual" | "parecido" | "diferente" {
  if (f.score >= 0.999) return "igual";
  return f.score > 0 ? "parecido" : "diferente";
}

function Revelacao({
  evidencia, palpite, certo, seguir, ultima,
}: { evidencia: Evidence; palpite: Resposta; certo: Resposta; seguir: () => void; ultima: boolean }) {
  const [agulha, setAgulha] = useState(0);
  useEffect(() => { const t = requestAnimationFrame(() => setAgulha(evidencia.total)); return () => cancelAnimationFrame(t); }, [evidencia.total]);
  const acertou = palpite === certo;

  return (
    <section className="revela" aria-live="polite">
      <p className={`revela__selo ${acertou ? "revela__selo--ok" : "revela__selo--nao"}`}>
        {acertou ? "Você concordou com o Nexus" : "O Nexus decidiu diferente"}
      </p>

      <div className="regua" aria-label={`Soma ${evidencia.total.toFixed(2)}`}>
        <div className="regua__faixas">
          <span style={{ width: `${LIMIAR_DUVIDA * 100}%` }}>diferentes</span>
          <span style={{ width: `${(LIMIAR_MATCH - LIMIAR_DUVIDA) * 100}%` }}>dúvida</span>
          <span style={{ width: `${(1 - LIMIAR_MATCH) * 100}%` }}>mesma</span>
        </div>
        <div className="regua__agulha" style={{ left: `${agulha * 100}%` }}>
          <span>{evidencia.total.toFixed(2)}</span>
        </div>
      </div>

      <p className="revela__veredito">{VEREDITO[certo]}</p>

      <ul className="revela__campos">
        {evidencia.fields.map((f, k) => (
          <li key={f.field} style={{ ["--atraso" as string]: `${300 + k * 120}ms` }}>
            <span>{CAMPOS[f.field] ?? f.field}</span>
            <span className="revela__barra"><span style={{ width: `${f.score * 100}%` }} /></span>
            <span className={`revela__nota revela__nota--${faixa(f)}`}>{faixa(f)}</span>
            <span className="revela__peso">peso {Math.round(f.weight * 100)}%</span>
          </li>
        ))}
      </ul>

      <button type="button" className="jogo__botao" onClick={seguir} autoFocus>
        {ultima ? "Ver resultado" : "Próximo par"} →
      </button>
    </section>
  );
}
