import { useState } from "react";
import { useAlerts, useMetrics, usePersistedSeries, useQueueStats } from "../api/queries";
import { Chart } from "../components/Chart";
import { ErrorState } from "../components/ErrorState";
import { Loading } from "../components/Loading";
import { OriginBadge } from "../components/OriginBadge";
import { Grade, Panel } from "../components/Panel";
import { StatTile, formatarValor } from "../components/StatTile";
import { parseChave } from "../metrics/parse";
import { descreverCobertura, descreverGraficoVazio, paraPontos } from "../metrics/persisted";
import "./ObservabilityCenter.css";

const SERIES = [
  { chave: "aguardando", rotulo: "aguardando" },
  { chave: "em voo", rotulo: "em voo" },
  { chave: "dead letter", rotulo: "dead letter" },
  { chave: "outbox", rotulo: "outbox" },
];

/** Um contador ausente nao comprova que o trabalho nao aconteceu. */
function contador(contadores: Record<string, number>, nome: string): number | null {
  const valores = Object.entries(contadores).filter(([chave]) => parseChave(chave).nome === nome);
  return valores.length ? valores.reduce((total, [, valor]) => total + valor, 0) : null;
}

function Atualizacao({ instante }: { instante: number }) {
  return <p className="obs__atualizacao">Resposta recebida em <time dateTime={new Date(instante).toISOString()}>{new Date(instante).toLocaleString("pt-BR")}</time>.</p>;
}

export function ObservabilityCenter() {
  const [janela, setJanela] = useState(60);
  const fila = useQueueStats();
  const metricas = useMetrics();
  const alertas = useAlerts();
  const serie = usePersistedSeries(janela);
  const pontos = paraPontos(serie.isError ? [] : serie.data?.points ?? [], {
    queue_pending: "aguardando", queue_in_flight: "em voo", queue_dead: "dead letter", outbox_pending: "outbox",
  }, serie.data?.interval_seconds);
  const dados = metricas.isError ? undefined : metricas.data;
  const counters = dados?.counters ?? {};
  const http = Object.entries(dados?.latency_ms ?? {}).filter(([chave]) => parseChave(chave).nome === "http_request_duration");
  const requisicoes = Object.entries(counters).filter(([chave]) => parseChave(chave).nome === "http_requests_total");
  const total = requisicoes.reduce((soma, [, valor]) => soma + valor, 0);
  const erros = requisicoes.filter(([chave]) => /^[45]\d\d$/.test(parseChave(chave).rotulos.status ?? "")).reduce((soma, [, valor]) => soma + valor, 0);
  const porRegistro = dados?.latency_ms.worker_record_duration;
  const porLote = dados?.latency_ms.worker_batch_duration;

  return <>
    <header className="obs__intro"><span>OBSERVABILIDADE</span><h1>O que o sistema consegue mostrar</h1><p>Leituras da API e do armazenamento, com o alcance de cada fonte. Uma resposta indisponível não representa zero.</p></header>

    <Panel titulo="Alertas" descricao="Condições calculadas no servidor no momento da consulta; a taxa HTTP usa apenas respostas 5xx deste processo.">
      {alertas.isError ? <ErrorState erro={alertas.error} onTentarNovamente={() => void alertas.refetch()} /> : alertas.isPending ? <Loading texto="consultando alertas…" /> : <>
        <p className="obs__aviso">{alertas.data.alerts.length ? `${alertas.data.alerts.length} condição(ões) retornada(s).` : "Nenhum alerta retornado nesta avaliação."} Algumas leituras internas podem falhar sem produzir um alerta específico; ausência de alerta não comprova saúde integral.</p>
        <p className="obs__atualizacao">Avaliado pelo servidor em <time dateTime={alertas.data.evaluated_at}>{new Date(alertas.data.evaluated_at).toLocaleString("pt-BR")}</time>.</p>
        {alertas.data.alerts.map((a) => <article className="obs__alerta" key={a.id}><div><strong>{a.title}</strong><p>{a.detail}</p></div><div><span>{a.severity === "error" ? "erro" : "atenção"}</span> <OriginBadge origem={a.origin} /></div>{a.value !== null && <p>Valor retornado: <span className="numero">{a.value}</span>{a.threshold !== null ? <> · limiar: <span className="numero">{a.threshold}</span></> : null}. A unidade depende da condição.</p>}</article>)}
      </>}
    </Panel>

    <Panel titulo="Fila e outbox" descricao="Leitura do backend da fila e do armazenamento do outbox. O SQS devolve estimativas, não contagens exatas.">
      {fila.isError ? <ErrorState erro={fila.error} onTentarNovamente={() => void fila.refetch()} /> : fila.isPending ? <Loading texto="consultando fila e outbox…" /> : <>
        <Atualizacao instante={fila.dataUpdatedAt} />
        {!fila.data.enabled ? <p className="obs__aviso">Fila desabilitada. Os contadores de fila não representam uma fila ativa.</p> : null}
        <Grade><StatTile rotulo="aguardando" valor={fila.data.enabled ? fila.data.pending : null} origem="persistido" /><StatTile rotulo="em voo" valor={fila.data.enabled ? fila.data.in_flight : null} origem="persistido" /><StatTile rotulo="dead letter" valor={fila.data.enabled ? fila.data.dead : null} origem="persistido" estado={fila.data.enabled && fila.data.dead > 0 ? "erro" : "normal"} /><StatTile rotulo="outbox pendente" valor={fila.data.outbox_pending} origem="persistido" /><StatTile rotulo="backend" valor={fila.data.backend} origem="processo" /></Grade>
        <p className="obs__aviso">{fila.data.backend === "sqs" ? "Aguardando, em voo e DLQ são estimativas do SQS e podem demorar a refletir alterações." : "Valores da fila vêm do backend configurado; confirme o backend antes de comparar ambientes."} Outbox é uma fonte distinta da fila.</p>
      </>}
    </Panel>

    <Panel titulo="Histórico de profundidade" descricao="Amostras persistidas em baldes de tempo; lacunas não são interpoladas." acoes={<OriginBadge origem="persistido" />}>
      <label className="obs__janela">Janela <select value={janela} onChange={(e) => setJanela(Number(e.target.value))}><option value={15}>15 minutos</option><option value={60}>60 minutos</option><option value={360}>6 horas</option><option value={1440}>24 horas</option></select></label>
      {serie.isError ? <ErrorState erro={serie.error} onTentarNovamente={() => void serie.refetch()} /> : serie.isPending ? <Loading texto="consultando série persistida…" /> : <>
        <p className="obs__aviso">{descreverCobertura(serie.data)} A coleta é oportunista e pode deixar períodos sem dados. Quando a fonte é SQS, os valores de fila são estimativas; cada amostra não identifica qual backend a produziu.</p>
        <Atualizacao instante={serie.dataUpdatedAt} />
        <div className="obs__legenda">{SERIES.map((s, i) => <span key={s.chave}><i style={{ background: `var(--serie-${i + 1})` }} />{s.rotulo}</span>)}</div>
        <Chart pontos={pontos} series={SERIES} eixoTemporal vazio={descreverGraficoVazio(serie.data)} />
        {serie.data.points.length > 0 && <details className="obs__amostras"><summary>Ver amostras retornadas</summary><div className="obs__rolagem"><table className="tabela"><thead><tr><th>Instante</th><th>Aguardando</th><th>Em voo</th><th>DLQ</th><th>Outbox</th></tr></thead><tbody>{serie.data.points.map((p) => <tr key={p.bucket}><td><time dateTime={p.bucket}>{new Date(p.bucket).toLocaleString("pt-BR")}</time></td>{["queue_pending", "queue_in_flight", "queue_dead", "outbox_pending"].map((k) => <td key={k} className="numero">{p.values[k] ?? "—"}</td>)}</tr>)}</tbody></table></div></details>}
      </>}
    </Panel>

    <Panel titulo="API e processamento" descricao="Contadores e amostras da instância que respondeu /metrics. Reinícios zeram o registro; réplicas não são agregadas.">
      {metricas.isError ? <ErrorState erro={metricas.error} onTentarNovamente={() => void metricas.refetch()} /> : metricas.isPending ? <Loading texto="consultando métricas do processo…" /> : <>
        <Atualizacao instante={metricas.dataUpdatedAt} />
        <Grade><StatTile rotulo="requisições observadas" valor={requisicoes.length ? total : null} origem="processo" /><StatTile rotulo="respostas 4xx e 5xx" valor={total > 0 ? (erros / total) * 100 : null} unidade="%" origem="processo" dica="Calculado a partir dos contadores da instância; inclui 4xx e 5xx." /><StatTile rotulo="registros processados" valor={contador(counters, "worker_processed_total")} origem="processo" /><StatTile rotulo="falhas de processamento" valor={contador(counters, "worker_failed_total")} origem="processo" /><StatTile rotulo="worker p95 por registro" valor={porRegistro?.p95 ?? null} unidade="ms" origem="processo" /><StatTile rotulo="worker p95 por lote" valor={porLote?.p95 ?? null} unidade="ms" origem="processo" /></Grade>
        <p className="obs__aviso">A proporção 4xx/5xx é calculada sobre respostas deste processo desde seu início. A API pode não compartilhar processo com o worker, especialmente na AWS; valores ausentes não significam que nada foi processado. A API não fornece vazão agregada de processamento entre workers.</p>
        <h3 className="obs__subtitulo">Latência HTTP por rota</h3><p className="obs__aviso">Percentis das amostras mantidas por esta instância, até 4.096 por série. Não são percentis globais.</p>
        {http.length === 0 ? <p className="obs__aviso">Nenhuma amostra de latência HTTP retornada por este processo.</p> : <div className="obs__rolagem"><table className="tabela"><thead><tr><th>Rota</th><th>Amostras</th><th>p50</th><th>p95</th><th>p99</th></tr></thead><tbody>{http.map(([chave, valor]) => { const rotulos = parseChave(chave).rotulos; return <tr key={chave}><td className="numero">{rotulos.method} {rotulos.path}</td><td className="numero">{formatarValor(valor.count)}</td><td className="numero">{formatarValor(valor.p50)} ms</td><td className="numero">{formatarValor(valor.p95)} ms</td><td className="numero">{formatarValor(valor.p99)} ms</td></tr>; })}</tbody></table></div>}
      </>}
    </Panel>
    <p className="obs__fontes">Fontes: <a href="https://github.com/Buenno0/nexus-architecture/blob/main/docs/adr/ADR-009-control-center.md">ADR-009</a> · <a href="https://github.com/Buenno0/nexus-architecture/blob/main/docs/adr/ADR-010-observabilidade.md">ADR-010</a>. Os limites descritos são do código deste build.</p>
  </>;
}
