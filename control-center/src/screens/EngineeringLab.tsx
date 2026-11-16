import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Panel } from "../components/Panel";
import { useHealth } from "../api/queries";
import dados from "../generated/lab-data.json";

const ROOT = "https://github.com/Buenno0/nexus-architecture/blob/main/";
const GITHUB = "https://github.com/Buenno0/nexus-architecture/actions";
const fonte = (path: string) => `${ROOT}${path}`;

type Corrida = {
  nome: string; nota?: string; quando?: string;
  parametros?: { usuarios?: number; duracao?: string };
  ambiente?: { api_workers?: number; registros_pre_carregados?: number; trail_enabled?: boolean; environment?: string };
  latencia?: { agregado?: { requisicoes?: number; falhas?: number; rps?: number; p50_ms?: number; p95_ms?: number; p99_ms?: number }; cenarios?: Record<string, { p50_ms?: number; p95_ms?: number; rps?: number }> };
  gerador_saturado?: boolean;
};
const corridas = dados.runs.map((item) => ({ path: item.path, data: item.data as Corrida }));
const campanhas = [
  { id: "workers", nome: "Processos da API · repeticoes controladas", prefixos: ["ctrl-w1-", "ctrl-w4-"], nota: "Tres repeticoes por configuracao, com estado zerado. A diferenca observada ficou dentro da dispersao; nao sustenta uma vantagem detectavel.", classif: "Comparacao controlada · conclusao limitada" },
  { id: "trilha", nome: "Custo da trilha · regime nao saturado", prefixos: ["linear-trilha-off-", "linear-trilha-on-"], nota: "Tres repeticoes por configuracao, com 10 usuarios. Para custo de escrita, compare o cenario de registro novo, nao apenas o agregado.", classif: "Comparacao controlada · ambiente local" },
  { id: "concorrencia", nome: "Concorrencia · 10, 50 e 200 usuarios", prefixos: ["concorrencia-"], nota: "Uma corrida por configuracao. A tendencia e exploratoria; a magnitude nao tem repeticoes suficientes para quantificar dispersao.", classif: "Uma corrida por configuracao" },
  { id: "volume", nome: "Volume do acervo", prefixos: ["volume-"], nota: "Uma corrida por configuracao, com 50 usuarios. A magnitude da diferenca tem incerteza.", classif: "Uma corrida por configuracao" },
  { id: "inconclusivas", nome: "Corridas inconclusivas e descartadas", prefixos: ["workers-", "rep-w", "trilha-on", "trilha-off", "capacidade-", "ctrl-trilha-"], nota: "Inclui isolamento defeituoso, deriva do acervo ou dispersao sob saturacao. Estes resultados ficam preservados, mas nao sustentam conclusoes comparativas.", classif: "Inconclusiva ou descartada · consulte a fonte" },
] as const;

const numero = (v: number | undefined, casas = 2) => v === undefined || !Number.isFinite(v) ? "—" : v.toLocaleString("pt-BR", { maximumFractionDigits: casas });

export function Experimentos() {
  const [campanha, setCampanha] = useState<string>("workers");
  const [selecionada, setSelecionada] = useState<string>("");
  const atual = campanhas.find((c) => c.id === campanha) ?? campanhas[0];
  const itens = useMemo(() => corridas.filter(({ data }) => typeof data.nome === "string" && atual.prefixos.some((p) => data.nome.startsWith(p)) && data.latencia?.agregado), [atual]);
  const escolhida = itens.find((r) => r.data.nome === selecionada) ?? itens[0];
  const tetoGrafico = Math.max(0, ...itens.map((item) => item.data.latencia?.agregado?.rps ?? 0));
  return <>
    <div className="lab-intro"><span>PERFORMANCE / FASE 7</span><h1>Experimentos de desempenho</h1><p>Corridas locais com DynamoDB Local e Locust. Estes valores nao preveem desempenho na AWS.</p></div>
    <Panel titulo="Campanhas" descricao="Selecione um conjunto para examinar as corridas versionadas.">
      <div className="lab-filter"><label htmlFor="campanha">Conjunto de corridas</label><select id="campanha" value={campanha} onChange={(e) => { setCampanha(e.target.value); setSelecionada(""); }}>{campanhas.map((c) => <option key={c.id} value={c.id}>{c.nome}</option>)}</select></div>
      <div className="lab-callout"><strong>{atual.classif}</strong><p>{atual.nota}</p></div>
      <figure className="lab-bars"><figcaption>Vazao agregada por corrida · req/s <span>Escala de zero ate {numero(tetoGrafico)} req/s</span></figcaption>{itens.map(({data: d}) => <div className="lab-bar-row" key={d.nome}><span>{d.nome}</span><div aria-hidden="true"><i style={{width: `${tetoGrafico > 0 ? Math.max(0, (d.latencia?.agregado?.rps ?? 0) / tetoGrafico * 100) : 0}%`}} /></div><strong>{numero(d.latencia?.agregado?.rps)}</strong></div>)}</figure>
      <div className="lab-scroll"><table className="lab-table"><thead><tr><th>Corrida</th><th>Usuarios</th><th>Processos</th><th>Vazao agregada</th><th>p50</th><th>p95</th><th>p99</th></tr></thead><tbody>{itens.map(({data: d}) => <tr key={d.nome} className={escolhida?.data.nome === d.nome ? "lab-row-active" : ""}><td><button className="lab-select" type="button" onClick={() => setSelecionada(d.nome)} aria-pressed={escolhida?.data.nome === d.nome}>{d.nome}</button></td><td>{numero(d.parametros?.usuarios)}</td><td>{numero(d.ambiente?.api_workers)}</td><td>{numero(d.latencia?.agregado?.rps)} req/s</td><td>{numero(d.latencia?.agregado?.p50_ms)} ms</td><td>{numero(d.latencia?.agregado?.p95_ms)} ms</td><td>{numero(d.latencia?.agregado?.p99_ms)} ms</td></tr>)}</tbody></table></div>
      {escolhida && <div className="lab-detail"><h3>{escolhida.data.nome}</h3><p>{escolhida.data.nota || "Corrida registrada na campanha."}</p><dl><div><dt>Duracao configurada</dt><dd>{escolhida.data.parametros?.duracao ?? "—"}</dd></div><div><dt>Acervo inicial</dt><dd>{numero(escolhida.data.ambiente?.registros_pre_carregados)}</dd></div><div><dt>Trilha</dt><dd>{escolhida.data.ambiente?.trail_enabled === undefined ? "—" : escolhida.data.ambiente.trail_enabled ? "ligada" : "desligada"}</dd></div><div><dt>Requisicoes / falhas</dt><dd>{numero(escolhida.data.latencia?.agregado?.requisicoes)} / {numero(escolhida.data.latencia?.agregado?.falhas)}</dd></div><div><dt>Gerador saturado</dt><dd>{escolhida.data.gerador_saturado === undefined ? "nao registrado" : escolhida.data.gerador_saturado ? "sim" : "nao"}</dd></div></dl>
        {escolhida.data.latencia?.cenarios && <div className="lab-scroll"><table className="lab-table"><caption>Detalhe por cenario da corrida selecionada</caption><thead><tr><th>Cenario</th><th>Vazao na mistura</th><th>p50</th><th>p95</th></tr></thead><tbody>{Object.entries(escolhida.data.latencia.cenarios).map(([nome, valor]) => <tr key={nome}><td>{nome}</td><td>{numero(valor.rps)} req/s</td><td>{numero(valor.p50_ms)} ms</td><td>{numero(valor.p95_ms)} ms</td></tr>)}</tbody></table><p>A vazao por cenario em carga mista depende do peso do cenario; nao e seu teto isolado.</p></div>}
        <a href={fonte(escolhida.path)}>Abrir JSON original ↗</a></div>}
    </Panel>
    <Panel titulo="Metodo e limites"><div className="lab-links"><a href={fonte("docs/performance/metodologia.md")}>Ambiente, carga e repeticao <span>↗</span></a><a href={fonte("docs/performance/runs/README.md")}>Classificacao dos arquivos <span>↗</span></a><a href={fonte("docs/testing/phase-7-report.md#6-erros-de-medicao-cometidos-nesta-fase")}>Erros de medicao e correcoes <span>↗</span></a></div></Panel>
  </>;
}

const adrs = dados.adrs.map((doc) => {
  const titulo = doc.content.match(/^#\s+(.+)$/m)?.[1] ?? doc.path;
  const id = doc.path.match(/ADR-(\d+)/)?.[1] ?? "";
  const status = doc.content.match(/^- \*\*Status:\*\*\s*(.+)$/m)?.[1]?.replaceAll("**", "") ?? "Consulte o documento";
  return { ...doc, id, titulo, status };
});

export function Decisoes() {
  const [id, setId] = useState("003");
  const doc = adrs.find((a) => a.id === id) ?? adrs[0];
  if (!doc) return <p>Nenhum ADR disponivel neste build.</p>;
  const relacionadas = [...new Set([...doc.content.matchAll(/ADR-(\d{3})/g)].map((m) => m[1]).filter((n) => n && n !== doc.id && adrs.some((a) => a.id === n)))];
  return <>
    <div className="lab-intro"><span>ARQUITETURA / REGISTROS</span><h1>Decisoes de engenharia</h1><p>A copia exibida corresponde aos arquivos presentes no build; a fonte no repositorio pode estar em uma versao anterior.</p></div>
    <div className="lab-document-layout"><nav className="lab-doc-nav" aria-label="Decisoes de arquitetura">{adrs.map((a) => <button key={a.id} type="button" className={a.id === doc.id ? "lab-doc-active" : ""} aria-current={a.id === doc.id ? "true" : undefined} onClick={() => setId(a.id)}><span>ADR-{a.id}</span>{a.titulo.replace(/^ADR-\d+\s*[—–-]\s*/, "")}</button>)}</nav>
      <article className="lab-document"><div className="lab-document-head"><span>DOCUMENTO NO BUILD</span><h2>{doc.titulo}</h2><p><strong>Status no documento:</strong> {doc.status}</p><a href={fonte(doc.path)}>Abrir fonte no repositorio ↗</a></div>{relacionadas.length > 0 && <div className="lab-related">Relacionadas: {relacionadas.map((n) => <button key={n} type="button" onClick={() => setId(n!)}>ADR-{n}</button>)}</div>}<pre className="lab-markdown">{doc.content}</pre></article></div>
  </>;
}

type RunCI = { html_url: string; status: string; conclusion: string | null; created_at: string; head_sha: string; head_branch: string };
async function carregarCI(): Promise<RunCI | null> {
  const response = await fetch("https://api.github.com/repos/Buenno0/nexus-architecture/actions/workflows/ci.yml/runs?per_page=1", { signal: AbortSignal.timeout(8000) });
  if (!response.ok) throw new Error(`GitHub respondeu ${response.status}`);
  const json: unknown = await response.json();
  if (!json || typeof json !== "object" || !("workflow_runs" in json) || !Array.isArray(json.workflow_runs)) throw new Error("Resposta do GitHub invalida");
  const item: unknown = json.workflow_runs[0];
  if (!item) return null;
  if (typeof item !== "object" || !("html_url" in item) || typeof item.html_url !== "string" || !item.html_url.startsWith("https://github.com/Buenno0/nexus-architecture/actions/runs/") || !("status" in item) || typeof item.status !== "string" || !("created_at" in item) || typeof item.created_at !== "string" || !("head_sha" in item) || typeof item.head_sha !== "string" || !("head_branch" in item) || typeof item.head_branch !== "string" || !("conclusion" in item) || !(typeof item.conclusion === "string" || item.conclusion === null)) throw new Error("Dados da execucao indisponiveis");
  return item as RunCI;
}
export function Infraestrutura() {
  const health = useHealth();
  const ci = useQuery({ queryKey: ["github-ci"], queryFn: carregarCI, retry: false, staleTime: 300_000, refetchOnWindowFocus: false });
  return <>
    <div className="lab-intro"><span>INFRAESTRUTURA / ENTREGA</span><h1>Ambientes e operacao</h1><p>Codigo, evidencias historicas e observacoes atuais tem fontes e alcances diferentes.</p></div>
    <div className="infra-grid"><section><h2>Ambiente consultado</h2><p>{health.isPending ? "Consultando a API…" : health.isError ? "API indisponivel; nao e possivel afirmar seu estado." : `API respondeu: ${health.data.status}; ambiente informado: ${health.data.environment}; persistencia: ${health.data.persistence}.`}</p><small>Resposta de /health. Nao e inventario da conta AWS.</small></section><section><h2>Infraestrutura em codigo</h2><p>Docker Compose local; Terraform para API Gateway, Lambda, DynamoDB, SQS, Cognito e Scheduler opcional.</p><a href="https://github.com/Buenno0/nexus-architecture/tree/main/infra/terraform">Ver Terraform ↗</a> · <a href={fonte("docker-compose.yml")}>Docker Compose ↗</a></section><section><h2>Validacao historica</h2><p>Fase 3: implantada e destruida em novembro de 2026. Fase 9: demonstracao reimplantada e verificada em 12/11/2026.</p><a href={fonte("docs/testing/phase-9-report.md")}>Relatorio da Fase 9 ↗</a><small>Estas verificacoes nao comprovam o estado atual de todos os recursos.</small></section><section><h2>Custos registrados</h2><p>Deploy da Fase 3, de 7 a 9/11/2026: US$ 0,0001, conforme o relatorio de custos.</p><a href={fonte("COSTS.md")}>Metodo, valores e estimativas ↗</a><small>Valor historico. Custo atual nao consultado.</small></section></div>
    <Panel titulo="Integracao continua" descricao="Ultima execucao do workflow CI retornada pela API publica do GitHub; nao indica deploy."><div className="lab-callout">{ci.isPending ? <p>Consultando GitHub…</p> : ci.isError ? <p>Estado do CI indisponivel: {ci.error.message}. <a href={GITHUB}>Consultar no GitHub ↗</a></p> : ci.data ? <><strong>{ci.data.status === "completed" ? `Concluida: ${ci.data.conclusion ?? "resultado indisponivel"}` : `Em andamento: ${ci.data.status}`}</strong><p>{ci.data.head_branch} · {ci.data.head_sha.slice(0, 7)} · criada em {new Date(ci.data.created_at).toLocaleString("pt-BR")}</p><a href={ci.data.html_url}>Abrir execucao ↗</a><small>Consultado em {new Date(ci.dataUpdatedAt).toLocaleString("pt-BR")}. Resultado de um workflow, nao do deploy.</small></> : <p>Nenhuma execucao retornada. <a href={GITHUB}>Ver GitHub Actions ↗</a></p>}</div></Panel>
    <Panel titulo="Procedimentos"><div className="lab-links"><a href={fonte("docs/runbook-demo.md")}>Demonstracao publica <span>↗</span></a><a href={fonte("docs/runbook-deploy.md")}>Deploy e destruicao <span>↗</span></a><a href={fonte(".github/workflows/ci.yml")}>Definicao do CI <span>↗</span></a></div></Panel>
  </>;
}
