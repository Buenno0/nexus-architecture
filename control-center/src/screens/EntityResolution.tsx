import { useState } from "react";

import { ErrorState } from "../components/ErrorState";
import { Loading } from "../components/Loading";
import { OpButton } from "../components/OpButton";
import { Grade, Panel } from "../components/Panel";
import { StatTile } from "../components/StatTile";
import { useDecidirRevisao, useEntity, useResolutionStats, useReviews } from "../api/queries";
import type { Evidence, ReviewItem } from "../api/types";

/**
 * Tela de resolucao de identidade.
 *
 * E a tela que mais justifica a existencia do painel: a evidencia campo a campo que o
 * ADR-006 produz e ilegivel em JSON e util numa tabela. E e ela que sustenta a regra
 * inegociavel do projeto — POSSIBLE_MATCH nunca funde sozinho, alguem decide.
 */

function TabelaDeEvidencia({ evidencia }: { evidencia: Evidence }) {
  return (
    <table className="tabela tabela--evidencia">
      <thead>
        <tr>
          <th>campo</th>
          <th style={{ textAlign: "right" }}>peso</th>
          <th style={{ textAlign: "right" }}>score</th>
          <th>registro A</th>
          <th>registro B</th>
        </tr>
      </thead>
      <tbody>
        {evidencia.fields.map((campo) => (
          <tr key={campo.field}>
            <td>{campo.field}</td>
            <td className="numero" style={{ textAlign: "right" }}>
              {campo.weight.toFixed(2)}
            </td>
            <td
              className="numero"
              style={{
                textAlign: "right",
                color:
                  campo.score >= 0.85
                    ? "var(--ok)"
                    : campo.score > 0
                      ? "var(--atencao)"
                      : "var(--erro)",
              }}
            >
              {campo.score.toFixed(3)}
            </td>
            <td className="numero celula-valor">{campo.left ?? "—"}</td>
            <td className="numero celula-valor">{campo.right ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CartaoDeRevisao({ item }: { item: ReviewItem }) {
  const decidir = useDecidirRevisao();
  const [motivo, setMotivo] = useState("");

  return (
    <article className="revisao">
      <header className="revisao__cabecalho">
        <div>
          <span className="revisao__score numero">{item.score.toFixed(3)}</span>
          <span className="revisao__motivo">{item.evidence.reason}</span>
        </div>
        <div className="revisao__acoes">
          <OpButton
            rotulo="Confirmar fusao"
            confirmacao="Sao a mesma entidade?"
            onExecutar={() =>
              decidir.mutateAsync({
                pairId: item.pair_id,
                decisao: "confirm",
                ...(motivo ? { motivo } : {}),
              })
            }
          />
          <OpButton
            rotulo="Recusar"
            variante="perigo"
            onExecutar={() =>
              decidir.mutateAsync({
                pairId: item.pair_id,
                decisao: "reject",
                ...(motivo ? { motivo } : {}),
              })
            }
          />
        </div>
      </header>

      <div className="revisao__ids numero">
        {item.record_a} &nbsp;↔&nbsp; {item.record_b}
      </div>

      <TabelaDeEvidencia evidencia={item.evidence} />

      <input
        className="revisao__campo"
        placeholder="Motivo da decisao (opcional, fica registrado)"
        value={motivo}
        onChange={(e) => setMotivo(e.target.value)}
      />
    </article>
  );
}

export function EntityResolution() {
  const stats = useResolutionStats();
  const reviews = useReviews(25);
  const [entidadeAberta, setEntidadeAberta] = useState<string | null>(null);
  const entidade = useEntity(entidadeAberta);

  if (stats.isError) {
    return <ErrorState erro={stats.error} onTentarNovamente={() => void stats.refetch()} />;
  }

  const c = stats.data?.counters ?? {};

  return (
    <>
      <Panel
        titulo="Resolucao"
        descricao={`Processador ${stats.data?.processor_version ?? "…"}. Contadores duraveis, nao em memoria.`}
      >
        <Grade>
          <StatTile rotulo="registros analisados" valor={c.records_analyzed ?? null} origem="persistido" />
          <StatTile rotulo="candidatos comparados" valor={c.candidates_compared ?? null} origem="persistido" />
          <StatTile rotulo="correspondencias" valor={c.matches ?? null} origem="persistido" />
          <StatTile
            rotulo="possiveis"
            valor={c.possible_matches ?? null}
            origem="persistido"
            dica="Entre os limiares. Nunca fundem sozinhas."
          />
          <StatTile rotulo="entidades criadas" valor={c.entities_created ?? null} origem="persistido" />
          <StatTile rotulo="fusoes" valor={c.merges ?? null} origem="persistido" />
          <StatTile
            rotulo="recusadas por teto"
            valor={c.refused_too_large ?? null}
            origem="persistido"
            estado={(c.refused_too_large ?? 0) > 0 ? "atencao" : "normal"}
            dica="Cluster que cresceria demais e sinalizado em vez de expandido."
          />
          <StatTile
            rotulo="aguardando revisao"
            valor={stats.data?.pending_reviews ?? null}
            origem="persistido"
            estado={(stats.data?.pending_reviews ?? 0) > 0 ? "atencao" : "normal"}
          />
        </Grade>
      </Panel>

      <Panel
        titulo="Fila de revisao"
        descricao="Pares em duvida. Confirmar funde os clusters; recusar registra a decisao e impede que o par volte em reprocessamentos."
      >
        {reviews.isError ? (
          <ErrorState erro={reviews.error} />
        ) : reviews.isPending ? (
          <Loading texto="consultando a fila de revisao…" />
        ) : reviews.data.items.length === 0 ? (
          <p className="vazio">
            Nenhum par aguardando decisao. Gere registros com variantes na aba Queue para
            produzir casos duvidosos.
          </p>
        ) : (
          reviews.data.items.map((item) => <CartaoDeRevisao key={item.pair_id} item={item} />)
        )}
      </Panel>

      <Panel
        titulo="Inspecionar entidade"
        descricao="Informe um entity_id para ver os vinculos e o historico de fusoes."
      >
        <input
          className="revisao__campo"
          placeholder="entity_id"
          value={entidadeAberta ?? ""}
          onChange={(e) => setEntidadeAberta(e.target.value || null)}
        />
        {entidade.isError ? (
          <ErrorState erro={entidade.error} />
        ) : entidade.data ? (
          <>
            <Grade minimo={150}>
              <StatTile rotulo="membros" valor={entidade.data.member_count} origem="persistido" />
              <StatTile rotulo="versao" valor={entidade.data.version} origem="persistido" />
              <StatTile
                rotulo="sinalizada"
                valor={entidade.data.flagged ? "sim" : "nao"}
                origem="persistido"
                estado={entidade.data.flagged ? "atencao" : "normal"}
                dica={entidade.data.flag_reason ?? undefined}
              />
              <StatTile rotulo="fusoes" valor={entidade.data.merges.length} origem="persistido" />
            </Grade>
            <table className="tabela" style={{ marginTop: 12 }}>
              <thead>
                <tr>
                  <th>membro</th>
                  <th style={{ textAlign: "right" }}>score</th>
                  <th>ligado a</th>
                </tr>
              </thead>
              <tbody>
                {entidade.data.members.map((m) => (
                  <tr key={m.record_id}>
                    <td className="numero">{m.record_id}</td>
                    <td className="numero" style={{ textAlign: "right" }}>
                      {m.score.toFixed(3)}
                    </td>
                    <td className="numero">{m.matched_record_id ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : null}
      </Panel>
    </>
  );
}
