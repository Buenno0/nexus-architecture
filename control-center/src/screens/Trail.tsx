/**
 * Tela Trail — a jornada de uma observacao atravessando processos.
 *
 * Esta pergunta nao tinha resposta ate a Fase 6. O `correlation_id` era propagado
 * corretamente desde a Fase 1, mas a metade do worker so existia no terminal de quem
 * rodou o comando: `docker compose logs api` tinha zero eventos de processamento.
 * O investimento em rastreamento nunca se pagou porque a trilha era irrecuperavel.
 */

import { useState } from "react";

import { ErrorState } from "../components/ErrorState";
import { Loading } from "../components/Loading";
import { OriginBadge } from "../components/OriginBadge";
import { Grade, Panel } from "../components/Panel";
import { StatTile, formatarValor } from "../components/StatTile";
import { useRecords, useTrail } from "../api/queries";
import type { TrailEvent } from "../api/types";

const ROTULO: Record<TrailEvent["stage"], string> = {
  accepted: "aceito",
  published: "publicado",
  consumed: "consumido",
  resolved: "resolvido",
  failed: "falhou",
  dead_lettered: "dead letter",
};

const ESTADO: Record<TrailEvent["stage"], "normal" | "atencao" | "erro"> = {
  accepted: "normal",
  published: "normal",
  consumed: "normal",
  resolved: "normal",
  failed: "atencao",
  dead_lettered: "erro",
};

/** Marcos consecutivos e o que o intervalo entre eles significa de fato. */
const INTERVALO: Record<string, string> = {
  "accepted>published": "tempo ate a publicacao na fila",
  "published>consumed": "intervalo observado entre publicacao e consumo; pode incluir espera na fila e eventos nao registrados",
  "consumed>resolved": "intervalo observado entre consumo e resolucao",
  "consumed>failed": "intervalo observado entre consumo e falha",
};

export function Trail() {
  const [entrada, setEntrada] = useState("");
  const [consultado, setConsultado] = useState("");
  const [tipo, setTipo] = useState<"person" | "organization">("person");
  const trilha = useTrail(consultado);
  const recentes = useRecords(tipo, 5);

  const eventos = trilha.data?.events ?? [];
  const atravessa = (trilha.data?.services.length ?? 0) > 1;
  const correlacoes = [...new Set(eventos.map((e) => e.correlation_id).filter(Boolean))];
  const ausentes = (["accepted", "published", "consumed", "resolved"] as const).filter(
    (stage) => !eventos.some((evento) => evento.stage === stage),
  );

  return (
    <>
      <Panel
        titulo="Jornada de uma observacao"
        descricao="Marcos emitidos pela API e pelo worker associados ao record_id. Retencao padrao de 7 dias."
      >
        <form
          className="trilha__busca"
          onSubmit={(e) => {
            e.preventDefault();
            setConsultado(entrada.trim());
          }}
        >
          <input
            className="trilha__campo numero"
            placeholder="record_id"
            value={entrada}
            onChange={(e) => setEntrada(e.target.value)}
            aria-label="record_id"
          />
          <button type="submit" className="aba" disabled={entrada.trim().length === 0}>
            Consultar
          </button>
        </form>

        <label className="trilha__tipo">Registros recentes
          <select value={tipo} onChange={(e) => setTipo(e.target.value as "person" | "organization")}>
            <option value="person">Pessoas</option>
            <option value="organization">Organizacoes</option>
          </select>
        </label>
        {recentes.isError ? <p className="trilha__aviso">Nao foi possivel carregar registros recentes. A busca por identificador continua disponivel.</p> : null}
        {recentes.data && recentes.data.items.length > 0 ? (
          <div className="trilha__recentes">
            <span className="trilha__recentes-rotulo">recentes:</span>
            {recentes.data.items.slice(0, 5).map((r) => (
              <button
                key={r.record_id}
                type="button"
                className="trilha__atalho numero"
                aria-label={`Consultar registro ${r.record_id}`}
                onClick={() => {
                  setEntrada(r.record_id);
                  setConsultado(r.record_id);
                }}
              >
                {r.record_id.slice(-10)}
              </button>
            ))}
          </div>
        ) : null}
      </Panel>

      {consultado === "" ? (
        <Panel titulo="Nenhum registro consultado">
          <p className="vazio">
            Informe um record_id acima, ou escolha um dos recentes.
          </p>
        </Panel>
      ) : trilha.isError ? (
        <ErrorState erro={trilha.error} onTentarNovamente={() => void trilha.refetch()} />
      ) : trilha.isPending ? (
        <Loading texto="carregando a trilha…" />
      ) : eventos.length === 0 ? (
        <Panel titulo="Sem trilha para este registro">
          <p className="vazio">
            Nao ha marcos gravados. A trilha e best-effort e tem retencao padrao de 7 dias: o registro
            pode ser anterior a Fase 6, ter passado da retencao, ou as escritas de trilha
            podem ter falhado. Nada disso afirma que o registro nao existe — a observacao e
            o resultado de processamento sao transacionais e continuam intactos.
          </p>
        </Panel>
      ) : (
        <>
          {ausentes.length > 0 ? <p className="trilha__parcial" role="status">Marcos do caminho comum nao encontrados nesta resposta: {ausentes.join(", ")}. A trilha pode estar incompleta, o processamento ainda pode estar em curso ou o caminho pode ter sido diferente.</p> : null}
          <Panel titulo="Resumo">
            <Grade>
              <StatTile rotulo="marcos" valor={eventos.length} origem="persistido" />
              <StatTile
                rotulo="entre primeiro e ultimo marco"
                valor={trilha.data.total_ms}
                unidade="ms"
                origem="persistido"
                dica="Intervalo entre os marcos observados; nao garante duracao completa da jornada."
              />
              <StatTile
                rotulo="emissores"
                valor={trilha.data.services.join(", ")}
                origem="persistido"
                estado={atravessa ? "normal" : "atencao"}
                dica={
                  atravessa
                    ? "Marcos emitidos por API e worker. No modo local podem compartilhar o mesmo processo."
                    : "Apenas um emissor contribuiu. O registro pode ainda nao ter sido consumido."
                }
              />
              <StatTile
                rotulo="correlation_id"
                valor={correlacoes.length === 0 ? null : correlacoes.length === 1 ? correlacoes[0] : `${correlacoes.length} identificadores`}
                origem="persistido"
                dica="Cada marco tem seu correlation_id; reprocessamentos podem gerar identificadores distintos."
              />
            </Grade>
          </Panel>

          <Panel
            titulo="Linha do tempo"
            descricao="Intervalos entre marcos observados. Uma trilha incompleta ou retentativas podem mudar a interpretacao."
          >
            <ol className="linha">
              {eventos.map((evento, i) => {
                const anterior = eventos[i - 1];
                const chave = anterior ? `${anterior.stage}>${evento.stage}` : "";
                return (
                  <li key={`${evento.stage}-${evento.occurred_at}-${i}`} className="linha__item">
                    <div className={`linha__marcador linha__marcador--${ESTADO[evento.stage]}`} />
                    <div className="linha__corpo">
                      <div className="linha__cabecalho">
                        <span className="linha__estagio">{ROTULO[evento.stage]}</span>
                        <span className="linha__servico numero">{evento.service}</span>
                        <span className="linha__hora numero">
                          <time dateTime={evento.occurred_at}>{new Date(evento.occurred_at).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "medium" })}</time>
                        </span>
                        {evento.delta_ms === null ? null : (
                          <span className="linha__delta numero">
                            +{formatarValor(evento.delta_ms)} ms
                          </span>
                        )}
                      </div>
                      <p className="linha__correlacao numero">correlation_id: {evento.correlation_id || "nao informado"}</p>
                      {chave && INTERVALO[chave] ? (
                        <p className="linha__intervalo">{INTERVALO[chave]}</p>
                      ) : null}
                      {Object.keys(evento.detail).length > 0 ? (
                        <dl className="linha__detalhe">
                          {Object.entries(evento.detail).map(([k, v]) => (
                            <div key={k}>
                              <dt>{k}</dt>
                              <dd className="numero">{String(v)}</dd>
                            </div>
                          ))}
                        </dl>
                      ) : null}
                    </div>
                  </li>
                );
              })}
            </ol>
            <p className="nota">
              <OriginBadge origem="persistido" /> Marcos gravados em best-effort: podem faltar
              eventos, inclusive entre dois marcos exibidos. Uma ausencia nao confirma falha
              nem conclusao; a trilha nao e auditoria. Retencao configurada: 7 dias por padrao.
            </p>
          </Panel>
        </>
      )}
    </>
  );
}
