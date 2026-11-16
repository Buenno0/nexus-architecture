/**
 * Secao 2 — veja acontecer.
 *
 * O desenho e HTML, nao SVG. O SVG do painel antigo tinha `min-width: 660px` e pedia
 * "arraste o desenho para o lado" no celular; aqui as quatro paradas sao uma lista,
 * que vira coluna quando nao cabem em linha e que um leitor de tela percorre sozinha.
 *
 * A unica animacao da pagina esta aqui: cada parada muda de estado quando a trilha
 * registra o marco correspondente. Nada se move por decoracao — o que acende acendeu
 * porque o evento existe.
 */

import type { Trail, TrailEvent } from "../api/types";
import { TAMANHO_DO_LOTE, type Jornada as EstadoJornada } from "./useJornada";

const PARADAS = [
  { marco: "accepted", nome: "API", faz: "confere e aceita" },
  { marco: "accepted", nome: "Armazenamento", faz: "guarda o registro" },
  { marco: "published", nome: "Fila", faz: "guarda a mensagem" },
  { marco: "consumed", nome: "Worker", faz: "compara e decide" },
] as const satisfies readonly { marco: TrailEvent["stage"]; nome: string; faz: string }[];

function observou(trilha: Trail | null, marco: TrailEvent["stage"]): boolean {
  return trilha?.events.some((e) => e.stage === marco) ?? false;
}

function legenda(estado: EstadoJornada): string {
  switch (estado.fase) {
    case "inicio":
      return `Envie ${TAMANHO_DO_LOTE} registros de exemplo para acompanhar o caminho deles.`;
    case "enviando":
      return "Enviando o lote…";
    case "enfileirado":
      return "Os registros foram aceitos, guardados e enfileirados. E a API parou aí — ela nunca processa.";
    case "processando":
      return "Processando: o worker pegou as mensagens da fila e está comparando.";
    case "concluido":
      return estado.precisaDeOutroPasso
        ? "Esse passo levou o que cabia, e a fila ainda tinha trabalho de outras visitas na frente. Peça outro passo."
        : "O worker terminou. O que ele decidiu está logo abaixo.";
    case "erro":
      return "Algo deu errado neste passo.";
  }
}

export function Jornada({ estado }: { estado: EstadoJornada }) {
  const ocupado = estado.fase === "enviando" || estado.fase === "processando";
  const podeProcessar =
    estado.ids.length > 0 &&
    (estado.fase === "enfileirado" || estado.precisaDeOutroPasso);

  return (
    <section className="secao" aria-labelledby="jornada-titulo">
      <p className="sobrelinha">Veja acontecer</p>
      <h2 className="titulo" id="jornada-titulo">
        Um lote de exemplo, do envio à decisão
      </h2>
      <p className="lead">
        Os registros abaixo são criados pelo servidor e gravados de verdade. Nada aqui é
        encenação: o que você vê acender é um evento que a plataforma registrou.
      </p>

      <div className="acoes">
        <button type="button" className="botao" onClick={estado.enviar} disabled={ocupado}>
          {estado.fase === "enviando"
            ? "Enviando…"
            : estado.ids.length > 0
              ? "Enviar outro lote"
              : `Enviar ${TAMANHO_DO_LOTE} registros`}
        </button>

        <button
          type="button"
          className="botao botao--segundo"
          onClick={estado.processar}
          disabled={ocupado || !podeProcessar}
        >
          {estado.fase === "processando" ? "Processando…" : "Processar agora"}
        </button>
      </div>

      {/* O segundo botao e o argumento, nao um detalhe de implementacao. */}
      <p className="acoes__nota">
        São dois botões porque são dois momentos. A API aceita e enfileira; o
        processamento só acontece quando alguém pede. Não existe worker ligado
        esperando — por isso o segundo botão existe.
      </p>

      <ol className="percurso">
        {PARADAS.map((parada) => {
          const feito = observou(estado.trilha, parada.marco);
          return (
            <li
              className={feito ? "parada parada--feita" : "parada"}
              key={parada.nome}
              aria-current={feito ? "step" : undefined}
            >
              <span className="parada__marca" aria-hidden="true" />
              <span className="parada__nome">{parada.nome}</span>
              <span className="parada__faz">{parada.faz}</span>
              <span className="parada__estado">{feito ? "registrado" : "aguardando"}</span>
            </li>
          );
        })}
      </ol>

      <p className="legenda" aria-live="polite">
        {legenda(estado)}
      </p>

      {estado.erro ? (
        <p className="aviso" role="alert">
          {estado.erro}
        </p>
      ) : null}

      {estado.ids.length > 0 ? (
        <div className="ressalva">
          <p>O desenho segue o primeiro registro do lote:</p>
          <p className="ressalva__id">{estado.ids[0]}</p>
          <p>
            A trilha é best-effort: uma parada que não acende não comprova que algo
            falhou.
          </p>
        </div>
      ) : null}
    </section>
  );
}
