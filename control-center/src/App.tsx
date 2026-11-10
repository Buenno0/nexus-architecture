import { useState } from "react";

import "./App.css";
import { config } from "./api/config";
import { useAuth } from "./auth/provider";
import { ApiMonitoring } from "./screens/ApiMonitoring";
import { EntityResolution } from "./screens/EntityResolution";
import { Login } from "./screens/Login";
import { Overview } from "./screens/Overview";
import { QueueMonitoring } from "./screens/QueueMonitoring";
import { Trail } from "./screens/Trail";
import { WorkerMonitoring } from "./screens/WorkerMonitoring";
import { AlertBanner } from "./components/AlertBanner";
import { useAlerts, useHealth } from "./api/queries";

const TELAS = [
  { id: "overview", rotulo: "Overview", componente: Overview },
  { id: "api", rotulo: "API", componente: ApiMonitoring },
  { id: "queue", rotulo: "Queue", componente: QueueMonitoring },
  { id: "worker", rotulo: "Worker", componente: WorkerMonitoring },
  { id: "resolution", rotulo: "Entity Resolution", componente: EntityResolution },
  { id: "trail", rotulo: "Trail", componente: Trail },
] as const;

type TelaId = (typeof TELAS)[number]["id"];

export function App() {
  const [tela, setTela] = useState<TelaId>("overview");
  const { autenticado, modo, usuario, sair } = useAuth();
  const health = useHealth();
  const alertas = useAlerts();

  if (!autenticado) return <Login />;

  const atual = TELAS.find((t) => t.id === tela) ?? TELAS[0];
  const Componente = atual.componente;

  const estado = health.data?.status;
  const classeEstado =
    health.isError || estado === "degraded" ? "estado--alerta" : estado === "ok" ? "estado--ok" : "";

  return (
    <div className="app">
      <header className="topo">
        <div className="topo__marca">
          <span className="topo__nome">NEXUS</span>
          <span className="topo__sub">Control Center</span>
        </div>

        <nav className="topo__nav">
          {TELAS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={`aba ${t.id === tela ? "aba--ativa" : ""}`}
              onClick={() => setTela(t.id)}
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
        <AlertBanner alertas={alertas.data?.alerts} erro={alertas.isError} />
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
