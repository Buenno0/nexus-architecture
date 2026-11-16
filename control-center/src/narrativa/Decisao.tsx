/**
 * Secao 3 — a decisao, com a evidencia que a sustenta.
 *
 * Esta e a secao que justifica o projeto inteiro, e no painel antigo ela estava atras
 * de um campo pedindo um `entity_id` que o visitante nao tinha como saber. Aqui ela
 * aparece sozinha, a partir do lote que ele mesmo acabou de enviar.
 *
 * O numero nunca aparece sozinho: cada score vem acompanhado de uma palavra. Cor
 * sozinha exclui quem nao a distingue — mesma regra do tema do console.
 */

import type { FieldScore, RecordDetail } from "../api/types";
import type { Jornada as EstadoJornada } from "./useJornada";

const ROTULOS: Record<string, string> = {
  full_name: "Nome",
  legal_name: "Razão social",
  email: "E-mail",
  phone: "Telefone",
  document: "Documento",
};

const DECISOES = {
  MATCH: { palavra: "Correspondem", classe: "veredito--match" },
  POSSIBLE_MATCH: { palavra: "Em dúvida", classe: "veredito--duvida" },
  NO_MATCH: { palavra: "Não correspondem", classe: "veredito--falha" },
} as const;

function faixa(score: number): { palavra: string; classe: string } {
  if (score >= 0.85) return { palavra: "igual", classe: "score--alto" };
  if (score > 0) return { palavra: "parecido", classe: "score--medio" };
  return { palavra: "diferente", classe: "score--nulo" };
}

function nomeDe(registro: RecordDetail): string {
  const p = registro.payload;
  const bruto = p["full_name"] ?? p["legal_name"];
  return typeof bruto === "string" && bruto.trim() ? bruto : registro.record_id;
}

export function Decisao({ estado }: { estado: EstadoJornada }) {
  return (
    <section className="secao" aria-labelledby="decisao-titulo">
      <p className="sobrelinha">A decisão</p>
      {/* O titulo nao pode prometer correspondencia: em parte das rodadas o lote nao
          tem par nenhum, e "por que sao a mesma pessoa" sobre cinco desconhecidos
          seria a interface contradizendo o proprio resultado. */}
      <h2 className="titulo" id="decisao-titulo">
        {estado.par
          ? "Por que o Nexus disse que são a mesma pessoa"
          : "O que o Nexus decidiu, e por quê"}
      </h2>

      {estado.par ? <Veredito par={estado.par} /> : <SemPar estado={estado} />}

      <div className="faixas">
        <h3 className="faixas__titulo">Três respostas possíveis, não duas</h3>
        <p className="faixas__texto">
          Um sistema que só respondesse “sim” ou “não” teria que chutar no meio. O Nexus
          tem uma faixa de dúvida: quando a soma dos campos não é alta o bastante para
          associar nem baixa o bastante para descartar, o par vira um item de revisão e{" "}
          <strong>nunca é fundido sozinho</strong>. É mais barato deixar uma pessoa em
          dobro do que fundir duas pessoas diferentes num registro só.
        </p>
      </div>
    </section>
  );
}

function Veredito({ par }: { par: NonNullable<EstadoJornada["par"]> }) {
  const { evidencia, registroA, registroB } = par;
  const decisao = DECISOES[evidencia.decision];

  return (
    <>
      <div className="veredito">
        <p className={`veredito__palavra ${decisao.classe}`}>{decisao.palavra}</p>
        <p className="veredito__nomes">
          <strong>{nomeDe(registroA)}</strong> e <strong>{nomeDe(registroB)}</strong>
        </p>
        <p className="veredito__razao">{evidencia.reason}</p>
      </div>

      <table className="evidencia">
        <caption className="evidencia__legenda">
          Campo a campo, com o peso de cada um. A soma é {evidencia.total.toFixed(3)} sobre{" "}
          {evidencia.compared_fields} campo(s) comparado(s).
        </caption>
        <thead>
          <tr>
            <th scope="col">Campo</th>
            <th scope="col">Peso</th>
            <th scope="col">Resultado</th>
            <th scope="col">Primeiro registro</th>
            <th scope="col">Segundo registro</th>
          </tr>
        </thead>
        <tbody>
          {evidencia.fields.map((campo: FieldScore) => {
            const f = faixa(campo.score);
            return (
              <tr key={campo.field}>
                <th scope="row">{ROTULOS[campo.field] ?? campo.field}</th>
                <td className="evidencia__num">{campo.weight.toFixed(2)}</td>
                <td>
                  <span className={`score ${f.classe}`}>
                    {f.palavra} <span className="score__num">{campo.score.toFixed(2)}</span>
                  </span>
                </td>
                <td className="evidencia__valor">{campo.left ?? "não informado"}</td>
                <td className="evidencia__valor">{campo.right ?? "não informado"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </>
  );
}

function SemPar({ estado }: { estado: EstadoJornada }) {
  if (estado.fase === "concluido") {
    return (
      <p className="lead">
        Nesta rodada os registros descreviam pessoas diferentes, então nenhuma associação
        foi feita — o que também é uma resposta. Envie outro lote: o gerador cria
        duplicatas e variantes em parte dos casos, e aí há um par para decidir.
      </p>
    );
  }
  if (estado.fase === "processando") {
    return <p className="lead">Comparando os registros do lote…</p>;
  }
  return (
    <p className="lead">
      Envie um lote acima e peça o processamento. O que o Nexus decidir sobre ele, e por
      quê, aparece aqui.
    </p>
  );
}
