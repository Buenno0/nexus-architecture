import { useState } from "react";

import { Chart } from "../components/Chart";
import { ErrorState } from "../components/ErrorState";
import { OpButton } from "../components/OpButton";
import { Grade, Panel } from "../components/Panel";
import { ResultLine } from "../components/ResultLine";
import { OriginBadge } from "../components/OriginBadge";
import { StatTile } from "../components/StatTile";
import {
  useDispatch,
  useMetrics,
  usePersistedSeries,
  useProcess,
  useQueueStats,
  useRedrive,
  useReprocess,
} from "../api/queries";
import { enviarLote, montarLote } from "../api/generator";
import type { ProgressoGeracao } from "../api/generator";
import { somarPorNome } from "../metrics/parse";
import { descreverCobertura, paraPontos } from "../metrics/persisted";

const VOLUMES = [100, 1_000, 10_000] as const;
/** Acima disso, gerar pede confirmacao: e trabalho em volume. */
const LIMIAR_CONFIRMACAO = 1_000;

export function QueueMonitoring() {
  const queue = useQueueStats();
  const metrics = useMetrics();
  const dispatch = useDispatch();
  const process = useProcess();
  const redrive = useRedrive();
  const reprocess = useReprocess();

  const [resultado, setResultado] = useState<Record<string, unknown> | null>(null);

  // Os resultados das operacoes sao objetos planos de numeros e textos; o componente
  // que os exibe so precisa iterar as entradas.
  const guardar = (r: object) => setResultado({ ...r });
  const [progresso, setProgresso] = useState<ProgressoGeracao | null>(null);

  const serie = usePersistedSeries(60);
  const pontos = paraPontos(serie.data?.points ?? [], {
    queue_pending: "aguardando",
    queue_in_flight: "em voo",
    queue_dead: "dead letter",
    outbox_pending: "outbox",
  });

  if (queue.isError) {
    return <ErrorState erro={queue.error} onTentarNovamente={() => void queue.refetch()} />;
  }

  const contadores = metrics.data?.counters ?? null;
  const loteDuracao = metrics.data?.latency_ms["worker_batch_duration"];

  async function gerar(quantidade: number) {
    setProgresso({ enviados: 0, aceitos: 0, duplicados: 0, falhas: 0, total: quantidade });
    const lote = montarLote(quantidade, "control-center", 0.15, 0.25);
    const final = await enviarLote(lote, setProgresso);
    guardar(final);
    void queue.refetch();
    void metrics.refetch();
  }

  return (
    <>
      <Panel
        titulo="Profundidade"
        descricao="Vem do armazenamento da fila, nao de contador em memoria."
      >
        <Grade>
          <StatTile rotulo="aguardando" valor={queue.data?.pending ?? null} origem="persistido" />
          <StatTile rotulo="em voo" valor={queue.data?.in_flight ?? null} origem="persistido" dica="Entregues a um consumidor e ainda nao confirmadas, ou aguardando retentativa." />
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
            dica="Eventos gravados na transacao de ingestao que ainda nao foram publicados."
          />
          <StatTile rotulo="backend" valor={queue.data?.backend ?? null} origem="persistido" />
        </Grade>
      </Panel>

      <Panel
        titulo="Operacoes"
        descricao="Nada processa sozinho: toda execucao e sob demanda. Operacoes de efeito amplo pedem confirmacao."
        acoes={
          <>
            <OpButton
              rotulo="Despachar outbox"
              dica="Publica na fila os eventos pendentes do outbox."
              onExecutar={async () => guardar(await dispatch.mutateAsync(1000))}
            />
            <OpButton
              rotulo="Processar fila"
              dica="Consome um lote e termina."
              onExecutar={async () => guardar(await process.mutateAsync(100))}
            />
            <OpButton
              rotulo="Devolver da DLQ"
              variante="perigo"
              confirmacao="Devolver mensagens da DLQ para a fila?"
              desabilitado={(queue.data?.dead ?? 0) === 0}
              onExecutar={async () => guardar(await redrive.mutateAsync(1000))}
            />
            <OpButton
              rotulo="Reprocessar acervo"
              variante="perigo"
              confirmacao="Reenfileirar registros sem resultado na versao corrente?"
              onExecutar={async () => guardar(await reprocess.mutateAsync(1000))}
            />
          </>
        }
      >
        <ResultLine resultado={resultado} />
      </Panel>

      <Panel
        titulo="Gerar registros sinteticos"
        descricao="Dados ficticios, com 15% de duplicatas exatas e 25% de variantes da mesma entidade. Nenhum dado pessoal real."
        acoes={VOLUMES.map((n) => (
          <OpButton
            key={n}
            rotulo={`Gerar ${n.toLocaleString("pt-BR")}`}
            {...(n > LIMIAR_CONFIRMACAO
              ? { confirmacao: `Gerar ${n.toLocaleString("pt-BR")} registros?` }
              : {})}
            onExecutar={() => gerar(n)}
          />
        ))}
      >
        {progresso ? (
          <>
            <div className="progresso">
              <div
                className="progresso__barra"
                style={{ width: `${(progresso.enviados / progresso.total) * 100}%` }}
              />
            </div>
            <ResultLine resultado={{ ...progresso }} />
          </>
        ) : (
          <p className="vazio">Escolha um volume acima.</p>
        )}
      </Panel>

      <Panel titulo="Consumo" >
        <Grade>
          <StatTile
            rotulo="processados"
            valor={contadores ? somarPorNome(contadores, "worker_processed_total") : null}
            origem="processo"
          />
          <StatTile
            rotulo="ja processados"
            valor={contadores ? somarPorNome(contadores, "worker_skipped_duplicate_total") : null}
            origem="processo"
          />
          <StatTile rotulo="lotes medidos" valor={loteDuracao?.count ?? null} origem="processo" />
          <StatTile rotulo="duracao de lote p95" valor={loteDuracao?.p95 ?? null} unidade="ms" origem="processo" />
        </Grade>
      </Panel>

      <Panel
        titulo="Historico da fila"
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
          altura={240}
          vazio="Sem amostras na janela. A serie avanca quando a plataforma e consultada."
        />
      </Panel>
    </>
  );
}
