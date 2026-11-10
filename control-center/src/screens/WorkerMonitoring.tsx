import { Chart } from "../components/Chart";
import { ErrorState } from "../components/ErrorState";
import { NotAvailable } from "../components/NotAvailable";
import { Grade, Panel } from "../components/Panel";
import { StatTile } from "../components/StatTile";
import { useMetrics } from "../api/queries";
import { somarPorNome } from "../metrics/parse";
import { useSessionSeries } from "../metrics/useSessionSeries";

export function WorkerMonitoring() {
  const metrics = useMetrics();
  const contadores = metrics.data?.counters ?? null;

  const processados = contadores ? somarPorNome(contadores, "worker_processed_total") : null;
  const jaProcessados = contadores ? somarPorNome(contadores, "worker_skipped_duplicate_total") : null;
  const falhas = contadores ? somarPorNome(contadores, "worker_failed_total") : null;
  const dlq = contadores ? somarPorNome(contadores, "worker_dead_lettered_total") : null;

  const serie = useSessionSeries(
    contadores ? { processados: processados ?? 0, ja_processados: jaProcessados ?? 0, falhas: falhas ?? 0 } : null,
    metrics.dataUpdatedAt,
  );

  if (metrics.isError) {
    return <ErrorState erro={metrics.error} onTentarNovamente={() => void metrics.refetch()} />;
  }

  const porRegistro = metrics.data?.latency_ms["worker_record_duration"];
  const porLote = metrics.data?.latency_ms["worker_batch_duration"];

  return (
    <>
      <Panel titulo="Execucao">
        <Grade>
          <StatTile rotulo="registros processados" valor={processados} origem="processo" />
          <StatTile
            rotulo="ja processados"
            valor={jaProcessados}
            origem="processo"
            dica="Reentregas absorvidas pela escrita condicional do marcador (ADR-005)."
          />
          <StatTile
            rotulo="falhas"
            valor={falhas}
            origem="processo"
            estado={(falhas ?? 0) > 0 ? "atencao" : "normal"}
          />
          <StatTile
            rotulo="enviados a DLQ"
            valor={dlq}
            origem="processo"
            estado={(dlq ?? 0) > 0 ? "erro" : "normal"}
          />
        </Grade>
      </Panel>

      <Panel titulo="Workers em execucao">
        <Grade minimo={340}>
          <NotAvailable
            rotulo="workers ativos"
            explicacao="Nao ha worker residente para contar. A execucao e sob demanda: o worker sobe, consome um lote e termina. E essa a escolha que mantem o custo proximo de zero com a fila ociosa — ver ADR-008."
          />
        </Grade>
      </Panel>

      <Panel titulo="Duracao" descricao="Percentis em milissegundos.">
        <Grade minimo={140}>
          <StatTile rotulo="por registro p50" valor={porRegistro?.p50 ?? null} unidade="ms" origem="processo" />
          <StatTile rotulo="por registro p95" valor={porRegistro?.p95 ?? null} unidade="ms" origem="processo" />
          <StatTile rotulo="por registro p99" valor={porRegistro?.p99 ?? null} unidade="ms" origem="processo" />
          <StatTile rotulo="por lote p50" valor={porLote?.p50 ?? null} unidade="ms" origem="processo" />
          <StatTile rotulo="por lote p95" valor={porLote?.p95 ?? null} unidade="ms" origem="processo" />
          <StatTile rotulo="lotes medidos" valor={porLote?.count ?? null} origem="processo" />
        </Grade>
      </Panel>

      <Panel
        titulo="Historico de execucao na sessao"
        descricao="Totais acumulados a cada leitura, desde que esta pagina abriu."
      >
        <Chart
          pontos={serie}
          series={[
            { chave: "processados", rotulo: "processados" },
            { chave: "ja_processados", rotulo: "ja processados" },
            { chave: "falhas", rotulo: "falhas" },
          ]}
        />
      </Panel>
    </>
  );
}
