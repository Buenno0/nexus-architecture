import { useEffect, useState } from "react";

import "./App.css";
import { config } from "./api/config";
import { useAuth } from "./auth/provider";
import { ApiMonitoring } from "./screens/ApiMonitoring";
import { Arquitetura } from "./screens/Arquitetura";
import { EntityResolution } from "./screens/EntityResolution";
import { Login } from "./screens/Login";
import { Overview } from "./screens/Overview";
import { QueueMonitoring } from "./screens/QueueMonitoring";
import { Trail } from "./screens/Trail";
import { WorkerMonitoring } from "./screens/WorkerMonitoring";
import { ObservabilityCenter } from "./screens/ObservabilityCenter";
import { Decisoes, Experimentos, Infraestrutura } from "./screens/EngineeringLab";
import { AlertBanner } from "./components/AlertBanner";
import { useAlerts, useHealth } from "./api/queries";
import { Narrativa } from "./narrativa/Narrativa";
import { Jogo } from "./jogo/Jogo";

const TELAS = [
  { id: "arquitetura", rotulo: "Arquitetura", componente: Arquitetura },
  { id: "overview", rotulo: "Overview", componente: Overview },
  { id: "observabilidade", rotulo: "Observabilidade", componente: ObservabilityCenter },
  { id: "api", rotulo: "API", componente: ApiMonitoring },
  { id: "queue", rotulo: "Queue", componente: QueueMonitoring },
  { id: "worker", rotulo: "Worker", componente: WorkerMonitoring },
  { id: "resolution", rotulo: "Entity Resolution", componente: EntityResolution },
  { id: "trail", rotulo: "Trail", componente: Trail },
  { id: "experimentos", rotulo: "Experimentos", componente: Experimentos },
  { id: "decisoes", rotulo: "Decisões", componente: Decisoes },
  { id: "infraestrutura", rotulo: "Infraestrutura", componente: Infraestrutura },
] as const;

type TelaId = (typeof TELAS)[number]["id"];

function Abrindo() {
  return (
    <div className="abrindo" role="status">
      <span className="abrindo__marca">NEXUS</span>
      <span className="abrindo__nota">abrindo a demonstração…</span>
    </div>
  );
}

function telaDaUrl(): TelaId | null {
  const id = window.location.hash.slice(1);
  return TELAS.find((t) => t.id === id)?.id ?? null;
}

export function App() {
  // `null` e a pagina publica; um id de aba e o console. O hash continua sendo o
  // endereco de cada aba, entao todo link antigo (`#overview`, `#resolution`) segue
  // valendo — e sem hash, quem chega cai na narrativa em vez de num painel.
  //
  // No uso local quem abre e o operador, que quer os numeros direto.
  const [tela, setTela] = useState<TelaId | null>(
    () => telaDaUrl() ?? (config.demoMode ? null : "overview"),
  );
  // O jogo nao e aba do console: e uma porta da pagina publica, com endereco proprio.
  const [jogando, setJogando] = useState(() => window.location.hash === "#jogar");
  useEffect(() => {
    const atualizar = () => { setTela(telaDaUrl()); setJogando(window.location.hash === "#jogar"); };
    window.addEventListener("hashchange", atualizar);
    return () => window.removeEventListener("hashchange", atualizar);
  }, []);
  const { autenticado, autenticandoConvidado, modo, usuario, sair } = useAuth();
  // So o console consulta. A narrativa nao precisa de health nem de alertas, e cada
  // consulta ociosa numa pagina publica e custo recorrente por visitante parado.
  const noConsole = autenticado && tela !== null;
  const health = useHealth(noConsole);
  // Depois da autenticacao: ver a docstring de useAlerts.
  const alertas = useAlerts(noConsole);

  // Enquanto o convidado entra sozinho, a demonstracao publica nao mostra formulario:
  // pedir usuario e senha para quem nunca vai digitar nenhum e uma porta trancada na
  // frente de uma casa aberta. Se a tentativa falhar, `autenticandoConvidado` vira
  // false e o formulario aparece com o erro.
  if (!autenticado) return autenticandoConvidado ? <Abrindo /> : <Login />;

  if (jogando) {
    return <Jogo sair={() => { window.location.hash = ""; }} />;
  }

  if (tela === null) {
    return <Narrativa abrirConsole={() => { window.location.hash = "overview"; }} />;
  }

  const atual = TELAS.find((t) => t.id === tela) ?? TELAS[0];
  const Componente = atual.componente;

  const estado = health.data?.status;
  const classeEstado =
    health.isError || estado === "degraded" ? "estado--alerta" : estado === "ok" ? "estado--ok" : "";

  return (
    <div className="app">
      <header className="topo">
        <div className="topo__marca">
          <button
            type="button"
            className="topo__voltar"
            onClick={() => { window.location.hash = ""; setTela(null); }}
          >
            <span className="topo__nome">NEXUS</span>
          </button>
          <span className="topo__sub">Painel técnico</span>
        </div>

        <nav className="topo__nav" aria-label="Áreas do Nexus">
          {TELAS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={`aba ${t.id === tela ? "aba--ativa" : ""}`}
              aria-current={t.id === tela ? "page" : undefined}
              onClick={() => { setTela(t.id); window.location.hash = t.id; }}
            >
              {t.rotulo}
            </button>
          ))}
        </nav>

        <div className="topo__estado">
          <span className={`estado ${classeEstado}`}>
            {health.isError
              ? "sem resposta"
              : (health.data?.status ?? "…")}
          </span>
          <span className="topo__ambiente numero">
            {health.data?.environment ?? config.apiUrl.replace(/^https?:\/\//, "")}
          </span>
          {modo === "cognito" ? (
            <button type="button" className="aba" onClick={sair} title={usuario ?? ""}>
              sair
            </button>
          ) : null}
        </div>
      </header>

      <main className="conteudo">
        {/* A faixa fica fora da tela ativa: um alerta de DLQ importa tanto na tela de
            resolucao quanto na da fila, e so apareceria numa delas se vivesse dentro. */}
        {tela !== "observabilidade" && <AlertBanner alertas={alertas.data?.alerts} erro={alertas.isError} />}
        <Componente />
      </main>

      <footer className="rodape">
        <span>
          Dados sinteticos. Atualizacao a cada {Math.round(config.pollIntervalMs / 1000)}s.
        </span>
        <span>
          Todo numero declara a origem: <strong>persistido</strong> vem do armazenamento,{" "}
          <strong>processo</strong> zera no reinicio da API, <strong>sessao</strong> some ao
          recarregar esta pagina.
        </span>
      </footer>
    </div>
  );
}
