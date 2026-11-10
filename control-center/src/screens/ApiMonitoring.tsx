import { Chart } from "../components/Chart";
import { ErrorState } from "../components/ErrorState";
import { Grade, Panel } from "../components/Panel";
import { StatTile } from "../components/StatTile";
import { useMetrics } from "../api/queries";
import { agruparPorRotulo, parseChave, somarPorNome } from "../metrics/parse";
import { useRates, useSessionSeries } from "../metrics/useSessionSeries";

export function ApiMonitoring() {
  const metrics = useMetrics();
  const contadores = metrics.data?.counters ?? null;
  const taxas = useRates(contadores, metrics.dataUpdatedAt);

  const requisicoesPorSegundo = Object.entries(taxas)
    .filter(([k]) => k.startsWith("http_requests_total"))
    .reduce((s, [, v]) => s + v, 0);

  const serie = useSessionSeries(
    contadores ? { rps: Number(requisicoesPorSegundo.toFixed(2)) } : null,
    metrics.dataUpdatedAt,
  );

  if (metrics.isError) {
    return <ErrorState erro={metrics.error} onTentarNovamente={() => void metrics.refetch()} />;
  }

  const total = contadores ? somarPorNome(contadores, "http_requests_total") : null;
  const porRota = contadores ? agruparPorRotulo(contadores, "http_requests_total", "path") : {};
  const porStatus = contadores ? agruparPorRotulo(contadores, "http_requests_total", "status") : {};
  const latencias = Object.entries(metrics.data?.latency_ms ?? {}).filter(([k]) =>
    k.startsWith("http_request_duration"),
  );

  const erros = Object.entries(porStatus)
    .filter(([status]) => /^[45]/.test(status))
    .reduce((s, [, v]) => s + v, 0);

  return (
    <>
      <Panel titulo="Trafego">
        <Grade>
          <StatTile rotulo="total de requisicoes" valor={total} origem="processo" />
          <StatTile
            rotulo="requisicoes por segundo"
            valor={Object.keys(taxas).length > 0 ? requisicoesPorSegundo : null}
            unidade="req/s"
            origem="sessao"
            dica="Calculado a partir da diferenca entre duas leituras do contador."
          />
          <StatTile
            rotulo="respostas 4xx e 5xx"
            valor={contadores ? erros : null}
            origem="processo"
            estado={erros > 0 ? "atencao" : "normal"}
          />
          <StatTile
            rotulo="taxa de erro"
            valor={total && total > 0 ? (erros / total) * 100 : null}
            unidade="%"
            origem="processo"
            estado={total && erros / total > 0.05 ? "erro" : "normal"}
          />
        </Grade>
      </Panel>

      <Panel
        titulo="Requisicoes por segundo ao longo da sessao"
        descricao="A API nao guarda serie temporal; esta e montada aqui a partir do polling."
      >
        <Chart pontos={serie} series={[{ chave: "rps", rotulo: "req/s" }]} />
      </Panel>

      <Panel titulo="Rotas mais usadas">
        {Object.keys(porRota).length === 0 ? (
          <p className="vazio">Sem trafego registrado.</p>
        ) : (
          <table className="tabela">
            <thead>
              <tr>
                <th>rota</th>
                <th style={{ textAlign: "right" }}>requisicoes</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(porRota)
                .sort(([, a], [, b]) => b - a)
                .map(([rota, n]) => (
                  <tr key={rota}>
                    <td className="numero">{rota}</td>
                    <td className="numero" style={{ textAlign: "right" }}>
                      {n.toLocaleString("pt-BR")}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel titulo="Respostas por status">
        <Grade minimo={120}>
          {Object.entries(porStatus)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([status, n]) => (
              <StatTile
                key={status}
                rotulo={`HTTP ${status}`}
                valor={n}
                origem="processo"
                estado={/^5/.test(status) ? "erro" : /^4/.test(status) ? "atencao" : "normal"}
              />
            ))}
        </Grade>
      </Panel>

      <Panel titulo="Latencia por rota" descricao="Percentis em milissegundos.">
        {latencias.length === 0 ? (
          <p className="vazio">Sem medicoes de latencia.</p>
        ) : (
          <table className="tabela">
            <thead>
              <tr>
                <th>rota</th>
                <th style={{ textAlign: "right" }}>amostras</th>
                <th style={{ textAlign: "right" }}>p50</th>
                <th style={{ textAlign: "right" }}>p95</th>
                <th style={{ textAlign: "right" }}>p99</th>
                <th style={{ textAlign: "right" }}>max</th>
              </tr>
            </thead>
            <tbody>
              {latencias.map(([chave, resumo]) => {
                const rotulos = parseChave(chave).rotulos;
                return (
                  <tr key={chave}>
                    <td className="numero">
                      {rotulos.method} {rotulos.path}
                    </td>
                    {[resumo.count, resumo.p50, resumo.p95, resumo.p99, resumo.max].map((v, i) => (
                      <td key={i} className="numero" style={{ textAlign: "right" }}>
                        {v.toLocaleString("pt-BR", { maximumFractionDigits: 2 })}
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Panel>
    </>
  );
}
