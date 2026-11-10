import { Chart } from "../components/Chart";
import { ErrorState } from "../components/ErrorState";
import { Loading } from "../components/Loading";
import { Grade, Panel } from "../components/Panel";
import { OriginBadge } from "../components/OriginBadge";
import { StatTile } from "../components/StatTile";
import {
  useHealth,
  useMetrics,
  usePersistedSeries,
  useQueueStats,
  useRecords,
  useResolutionStats,
} from "../api/queries";
import { somarPorNome } from "../metrics/parse";
import { descreverCobertura, paraPontos } from "../metrics/persisted";

export function Overview() {
  const metrics = useMetrics();
  const queue = useQueueStats();
  const resolution = useResolutionStats();
  const health = useHealth();
  const records = useRecords("person", 8);

  const contadores = metrics.data?.counters ?? null;

  // Serie do armazenamento, nao da memoria desta aba: sobrevive a recarregar a pagina
  // e a reiniciar a API. Era a limitacao que o ADR-009 registrou e a Fase 6 fechou.
  const serie = usePersistedSeries(60);
  const pontos = paraPontos(serie.data?.points ?? [], {
    queue_pending: "aguardando",
    queue_in_flight: "em voo",
    queue_dead: "dead letter",
    outbox_pending: "outbox",
  });

  if (metrics.isError) return <ErrorState erro={metrics.error} onTentarNovamente={() => void metrics.refetch()} />;

  const aceitos = contadores ? somarPorNome(contadores, "ingestion_accepted_total") : null;
  const duplicados = contadores ? somarPorNome(contadores, "ingestion_duplicate_total") : null;
  const latencia = metrics.data?.latency_ms ?? {};
  const http = Object.entries(latencia).find(([k]) => k.startsWith("http_request_duration"))?.[1];
  const erros4xx5xx = contadores
    ? Object.entries(contadores)
        .filter(([k]) => k.startsWith("http_requests_total") && /status=[45]\d\d/.test(k))
        .reduce((s, [, v]) => s + v, 0)
    : null;
  const totalReq = contadores ? somarPorNome(contadores, "http_requests_total") : null;
  const taxaErro =
    totalReq !== null && erros4xx5xx !== null && totalReq > 0 ? (erros4xx5xx / totalReq) * 100 : null;

  return (
    <>
      <Panel
        titulo="Modulos da plataforma"
        descricao="O estado vem da propria API: modulo nao implementado se declara como tal."
      >
        <Grade minimo={200}>
          {Object.entries(metrics.data?.modules ?? {}).map(([nome, estado]) => (
            <StatTile
              key={nome}
              rotulo={nome.replace(/_/g, " ")}
              valor={estado.replace(/_/g, " ")}
              origem="processo"
              estado={estado === "implemented" ? "normal" : estado === "disabled" ? "atencao" : "normal"}
            />
          ))}
          <StatTile
            rotulo="persistencia"
            valor={health.data?.persistence ?? null}
            origem="processo"
            estado={health.data?.persistence === "ok" ? "normal" : "erro"}
          />
        </Grade>
      </Panel>

      <Panel titulo="Ingestao">
        <Grade>
          <StatTile rotulo="registros aceitos" valor={aceitos} origem="processo" />
          <StatTile rotulo="duplicados" valor={duplicados} origem="processo" />
          <StatTile
            rotulo="replays"
            valor={contadores ? somarPorNome(contadores, "ingestion_replayed_total") : null}
            origem="processo"
            dica="Mesma Idempotency-Key com o mesmo corpo: a resposta armazenada foi devolvida."
          />
          <StatTile
            rotulo="conflitos 409"
            valor={contadores ? somarPorNome(contadores, "ingestion_idempotency_conflict_total") : null}
            origem="processo"
            dica="Chave reusada com corpo diferente. E bug do cliente, nao da plataforma."
          />
        </Grade>
      </Panel>

      <Panel titulo="Fila e processamento">
        <Grade>
          <StatTile rotulo="aguardando" valor={queue.data?.pending ?? null} origem="persistido" carregando={queue.isLoading} />
          <StatTile rotulo="em voo" valor={queue.data?.in_flight ?? null} origem="persistido" />
          <StatTile
            rotulo="dead letter"
            valor={queue.data?.dead ?? null}
            origem="persistido"
            estado={(queue.data?.dead ?? 0) > 0 ? "erro" : "normal"}
          />
          <StatTile
            rotulo="outbox pendente"
            valor={queue.data?.outbox_pending ?? null}
            origem="persistido"
            estado={(queue.data?.outbox_pending ?? 0) > 0 ? "atencao" : "normal"}
          />
          <StatTile
            rotulo="processados"
            valor={contadores ? somarPorNome(contadores, "worker_processed_total") : null}
            origem="processo"
          />
        </Grade>
      </Panel>

      <Panel titulo="Latencia HTTP" descricao="Percentis, nao media: a media esconde a cauda.">
        <Grade minimo={140}>
          <StatTile rotulo="p50" valor={http?.p50 ?? null} unidade="ms" origem="processo" />
          <StatTile rotulo="p95" valor={http?.p95 ?? null} unidade="ms" origem="processo" />
          <StatTile rotulo="p99" valor={http?.p99 ?? null} unidade="ms" origem="processo" />
          <StatTile rotulo="maximo" valor={http?.max ?? null} unidade="ms" origem="processo" />
          <StatTile
            rotulo="taxa de erro"
            valor={taxaErro}
            unidade="%"
            origem="processo"
            estado={(taxaErro ?? 0) > 5 ? "erro" : "normal"}
          />
        </Grade>
      </Panel>

      <Panel
        titulo="Profundidade da plataforma"
        descricao={descreverCobertura(serie.data)}
        acoes={<OriginBadge origem="persistido" />}
      >
        <Chart
          pontos={pontos}
          series={[
            { chave: "aguardando", rotulo: "aguardando" },
            { chave: "em voo", rotulo: "em voo" },
            { chave: "dead letter", rotulo: "dead letter" },
            { chave: "outbox", rotulo: "outbox" },
          ]}
          vazio="Sem amostras na janela. A serie avanca quando a plataforma e consultada."
        />
      </Panel>

      <Panel titulo="Resolucao de identidade">
        <Grade>
          <StatTile rotulo="analisados" valor={resolution.data?.counters.records_analyzed ?? null} origem="persistido" />
          <StatTile rotulo="correspondencias" valor={resolution.data?.counters.matches ?? null} origem="persistido" />
          <StatTile rotulo="entidades" valor={resolution.data?.counters.entities_created ?? null} origem="persistido" />
          <StatTile
            rotulo="aguardando revisao"
            valor={resolution.data?.pending_reviews ?? null}
            origem="persistido"
            estado={(resolution.data?.pending_reviews ?? 0) > 0 ? "atencao" : "normal"}
          />
        </Grade>
      </Panel>

      <Panel titulo="Ultimas observacoes">
        {records.isError ? (
          <ErrorState erro={records.error} />
        ) : records.isPending ? (
          <Loading texto="consultando observacoes…" />
        ) : records.data.items.length === 0 ? (
          <p className="vazio">Nenhuma observacao ainda. Gere registros na aba Queue.</p>
        ) : (
          <table className="tabela">
            <thead>
              <tr>
                <th>record_id</th>
                <th>fonte</th>
                <th>entidade</th>
                <th>visto</th>
                <th>criado</th>
              </tr>
            </thead>
            <tbody>
              {records.data.items.map((r) => (
                <tr key={r.record_id}>
                  <td className="numero">{r.record_id}</td>
                  <td>{r.source}</td>
                  <td className="numero">{r.entity_id ?? "—"}</td>
                  <td className="numero">{r.seen_count}</td>
                  <td className="numero">{new Date(r.created_at).toLocaleTimeString("pt-BR")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </>
  );
}
