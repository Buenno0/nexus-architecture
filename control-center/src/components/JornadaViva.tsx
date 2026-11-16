import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { config } from "../api/config";
import { request } from "../api/client";
import { ingerir, semear } from "../api/queries";
import { montarLote } from "../api/generator";
import type { RecordDetail, Trail, TrailEvent } from "../api/types";
import "./JornadaViva.css";

const fontes = "https://github.com/Buenno0/nexus-architecture/blob/main/";
const etapas = [
  { stage: "accepted", nome: "API", subtitulo: "recebe", x: 130 },
  { stage: "accepted", nome: "Armazenamento", subtitulo: "guarda", x: 320 },
  { stage: "published", nome: "Fila", subtitulo: "aguarda", x: 510 },
  { stage: "consumed", nome: "Worker", subtitulo: "processa", x: 700 },
] as const;
const descricoes: Record<TrailEvent["stage"], string> = {
  accepted: "A API recebeu o registro e o guardou junto de um evento para processamento.",
  published: "Uma mensagem foi publicada na fila. O registro permanece guardado.",
  consumed: "O worker recebeu a mensagem e iniciou o processamento.",
  resolved: "O processamento terminou. Confira abaixo o que a trilha registrou sobre a comparação.",
  failed: "Uma falha foi registrada durante o processamento; uma nova tentativa pode acontecer.",
  dead_lettered: "A mensagem foi encaminhada para a fila de falhas.",
};
const nomeEvento: Record<TrailEvent["stage"], string> = {
  accepted: "ACCEPTED", published: "PUBLISHED", consumed: "CONSUMED",
  resolved: "RESOLVED", failed: "FAILED", dead_lettered: "DEAD_LETTERED",
};

function valor(dados: Record<string, unknown> | undefined, chave: string) {
  const v = dados?.[chave];
  return typeof v === "string" && v.trim() ? v : null;
}

export function JornadaViva() {
  const [id, setId] = useState("");
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState("");
  const [duplicado, setDuplicado] = useState(false);
  const [resposta, setResposta] = useState("");
  const trilha = useQuery({
    queryKey: ["jornada-viva", id],
    queryFn: () => request<Trail>(`/v1/observability/trail/${encodeURIComponent(id)}`),
    enabled: id.length > 0,
    refetchInterval: (query) => query.state.data?.events.some((e) => e.stage === "resolved" || e.stage === "dead_lettered") ? false : config.pollIntervalMs,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: false,
  });
  const registro = useQuery({
    queryKey: ["jornada-registro", id],
    queryFn: () => request<RecordDetail>(`/v1/records/${encodeURIComponent(id)}`),
    enabled: id.length > 0,
  });
  const eventos = trilha.data?.events ?? [];
  const tem = (stage: TrailEvent["stage"]) => eventos.some((e) => e.stage === stage);
  const ultimo = eventos.at(-1);
  const resolvido = [...eventos].reverse().find((e) => e.stage === "resolved");
  const candidatos = resolvido?.detail.candidates;
  const matches = resolvido?.detail.matches;
  const mensagem = !id ? "Envie um exemplo para acompanhar o que acontece com ele." : trilha.isError ? "Não foi possível consultar a trilha. Tente atualizar." : trilha.isPending ? "Consultando os primeiros eventos…" : ultimo ? descricoes[ultimo.stage] : "Nenhum evento foi encontrado ainda. A trilha pode ter lacunas.";
  const nome = valor(registro.data?.payload, "full_name");
  const email = valor(registro.data?.payload, "email");

  async function enviar() {
    setEnviando(true); setErro(""); setId(""); setResposta(""); setDuplicado(false);
    try {
      if (config.demoMode) {
        const resultado = await semear(1);
        const recordId = resultado.record_ids?.[0];
        if (!recordId) throw new Error("O pedido foi concluído, mas a API não devolveu um identificador. Acompanhar a jornada exige a versão atualizada da API.");
        setDuplicado(resultado.duplicate > 0);
        setResposta(`POST /v1/demo/seed · resposta recebida · aceitos: ${resultado.accepted} · duplicados: ${resultado.duplicate} · falhas: ${resultado.failed}`);
        setId(recordId);
      } else {
        const exemplo = montarLote(1, "jornada-visual", 0, 0)[0];
        if (!exemplo) throw new Error("Não foi possível criar um exemplo sintético.");
        const resultado = await ingerir("person", exemplo.payload);
        setDuplicado(resultado.status === "duplicate");
        setResposta(`POST /v1/records/person · resposta recebida · ${resultado.status}`);
        setId(resultado.record_id);
      }
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível enviar. Tente novamente.");
    } finally { setEnviando(false); }
  }

  return <div className="jornada-real">
    <header className="jornada-real__hero"><div><span>PROJETO DE ENGENHARIA</span><h1>Dados diferentes.<br />Uma mesma pessoa?</h1></div><p>O Nexus recebe registros de fontes diferentes e procura relações entre eles. Um projeto pessoal de Mateus Bueno sobre processamento assíncrono e resolução de identidade.</p></header>
    <section className="jornada-real__problema"><div><span>O PROBLEMA</span><h2>O mesmo cadastro pode chegar de formas diferentes.</h2></div><div><p>Uma pessoa pode aparecer em duas fontes com nomes escritos de maneiras diferentes. Tratar tudo como novo cria duplicatas; juntar registros sem cuidado pode misturar pessoas distintas.</p><p>Envie um registro sintético para acompanhar o que o Nexus faz com ele.</p></div></section>
    <section className="jornada-real__cena" aria-label="Caminho de um registro real"><header><strong>Acompanhe um registro</strong><span>Dados sintéticos · eventos da plataforma</span></header><div className="jornada-real__controles"><button type="button" onClick={() => void enviar()} disabled={enviando}>{enviando ? "Enviando…" : id ? "Enviar outro exemplo" : "Enviar exemplo"}</button>{id && <button className="jornada-real__atualizar" type="button" onClick={() => { void trilha.refetch(); void registro.refetch(); }}>Atualizar</button>}<small>Cria um registro fictício na plataforma.</small></div>
      <div className="jornada-real__entrada"><span>REGISTRO</span>{!id ? "O exemplo aparecerá aqui depois do envio." : registro.isPending ? "Consultando o registro…" : registro.isError ? "Não foi possível consultar os dados do registro." : <>{nome ?? "Nome indisponível"}{email && <> · {email}</>}</>}</div>
      <div className="jornada-real__desenho"><svg viewBox="0 0 860 230" role="img" aria-label="Diagrama da API, armazenamento, fila e worker. Os destaques representam eventos encontrados na trilha deste registro."><path className="jornada-real__linha" d="M60 85H130 M222 85H320 M412 85H510 M602 85H700" />{etapas.map((etapa) => <g key={etapa.nome} className={tem(etapa.stage) ? "jornada-real__observado" : ""}><rect x={etapa.x} y="43" width="92" height="84" rx="12"/><text x={etapa.x + 46} y="77" textAnchor="middle" className="jornada-real__marca">{etapa.nome === "Armazenamento" ? "▤" : etapa.nome === "Fila" ? "≡" : etapa.nome === "Worker" ? "◷" : "↘"}</text><text x={etapa.x + 46} y="151" textAnchor="middle" className="jornada-real__nome">{etapa.nome}</text><text x={etapa.x + 46} y="169" textAnchor="middle" className="jornada-real__sub">{tem(etapa.stage) ? "observado" : etapa.subtitulo}</text></g>)}{tem("accepted") && <g key={id} className="jornada-real__registro-movel" aria-hidden="true"><rect x="-35" y="-11" width="70" height="22" rx="5"/><text x="0" y="4" textAnchor="middle">registro</text></g>}{tem("published") && <g className="jornada-real__pacote" style={{ transform: `translate(${tem("consumed") ? 746 : 556}px, 105px)` }}><rect x="-38" y="-11" width="76" height="22" rx="5"/><text x="0" y="4" textAnchor="middle">mensagem</text></g>}</svg></div>
      <div className="jornada-real__legenda" aria-live="polite">{mensagem}</div>
      {erro && <p className="jornada-real__aviso" role="alert">{erro}</p>}{duplicado && <p className="jornada-real__aviso">Este exemplo já existia. A trilha mostrada pertence ao registro original.</p>}{id && <p className="jornada-real__nota">ID: <code>{id}</code>. A consulta é atualizada a cada {Math.round(config.pollIntervalMs / 1000)} segundos enquanto o processamento não termina. O movimento ilustra eventos observados; não representa o tempo exato entre eles. A trilha é best-effort: um marco ausente não comprova falha.</p>}
    </section>
    <section className="jornada-real__resultado" aria-labelledby="resultado-jornada"><h2 id="resultado-jornada">Resultado da comparação</h2>{!id ? <p>O resultado deste exemplo aparecerá aqui quando o processamento for registrado.</p> : !resolvido ? <p>Ainda não há um resultado de processamento na trilha. Ele pode estar pendente ou o evento pode não ter sido registrado.</p> : <><p>{typeof candidatos === "number" ? `${candidatos} candidato(s) comparado(s).` : "A quantidade de candidatos não está disponível nesta trilha."} {typeof matches === "number" ? `${matches} correspondência(s) registrada(s).` : "O número de correspondências não está disponível nesta trilha."}</p><p>Os campos comparados e a decisão completa não estão disponíveis neste evento. A conclusão do processamento, por si só, não significa que houve uma correspondência.</p></>}</section>
    <section className="jornada-real__console" aria-label="Console da jornada"><header><strong>Console da jornada</strong><span>Resposta do envio e eventos persistidos · sem logs do servidor</span></header><div className="jornada-real__log">{!id ? <p>Envie um exemplo para acompanhar os eventos.</p> : <><p><span>ENVIO</span> {resposta}</p><p><span>REGISTRO</span> {id}</p>{eventos.map((evento, i) => <p key={`${evento.occurred_at}-${evento.stage}-${i}`}><span>{nomeEvento[evento.stage] ?? evento.stage}</span> {new Date(evento.occurred_at).toLocaleString("pt-BR")} · {evento.service}{evento.delta_ms !== null ? ` · intervalo ${evento.delta_ms} ms` : ""}</p>)}{trilha.isError && <p>Não foi possível consultar os eventos. Use Atualizar para tentar novamente.</p>}{!trilha.isPending && !trilha.isError && eventos.length === 0 && <p>Nenhum evento retornado até o momento.</p>}</>}</div></section>
    <section className="jornada-real__secao"><span>POR TRÁS DA CENA</span><h2>Decisões de engenharia</h2><p>O problema, a escolha e suas consequências estão registrados junto ao código.</p><div className="jornada-real__decisoes"><details><summary>Por que guardar antes de processar?</summary><p>O registro e o evento são gravados na mesma transação. Se a publicação falhar, o evento pode ser recuperado; o consumidor precisa suportar entregas repetidas.</p><a href={`${fontes}docs/adr/ADR-003-transactional-outbox.md`}>Ler a decisão sobre transactional outbox ↗</a></details><details><summary>E se uma requisição for repetida?</summary><p>A chave de idempotência identifica a operação. Repetir a mesma chave com o mesmo conteúdo devolve a resposta anterior; conteúdo diferente gera conflito.</p><a href={`${fontes}docs/adr/ADR-002-identidade-e-idempotencia.md`}>Ler a decisão sobre idempotência ↗</a></details><details><summary>Como uma associação é decidida?</summary><p>Os campos disponíveis são comparados. Uma faixa intermediária gera revisão; os pesos e limiares não garantem acerto em dados reais.</p><a href={`${fontes}docs/adr/ADR-006-entity-resolution.md`}>Ler a decisão sobre resolução de identidade ↗</a></details></div></section>
    <section className="jornada-real__secao"><span>PARA INVESTIGAR</span><h2>Evidências e limites</h2><div className="jornada-real__evidencias"><article><h3>Testes de integração</h3><p>Fluxos verificados com DynamoDB Local; o relatório descreve o ambiente e os resultados.</p><a href={`${fontes}docs/testing/validation-2026-11-15.md`}>Ver validação ↗</a></article><article><h3>Qualidade da comparação</h3><p>A avaliação usa dados sintéticos com gabarito conhecido; não prevê desempenho com dados reais.</p><a href={`${fontes}docs/testing/phase-5-report.md`}>Ver avaliação ↗</a></article><article><h3>Medições e correções</h3><p>As medições foram locais. Erros e corridas inconclusivas continuam documentados.</p><a href={`${fontes}docs/testing/phase-7-report.md`}>Ver relatório ↗</a></article></div></section>
    <section className="jornada-real__autor"><h2>Um projeto pessoal de Mateus Bueno</h2><p>O Nexus reúne implementação, infraestrutura, interface e documentação para investigar como receber e relacionar registros sem esconder as decisões e as falhas do caminho.</p><a href="https://github.com/Buenno0/nexus-architecture">Ver o repositório ↗</a></section>
  </div>;
}
