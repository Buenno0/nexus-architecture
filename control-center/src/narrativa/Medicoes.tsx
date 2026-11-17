/**
 * Secao 5 — o que eu medi, e onde errei.
 *
 * Esta e a secao que diferencia o projeto. Pipeline com fila e worker todo mundo tem;
 * quatro erros de medicao proprios, dois com sinal invertido, versionados de proposito,
 * quase ninguem. No README isso vive em nota de rodape — aqui vira manchete.
 *
 * TODO NUMERO VEM COM ONDE FOI MEDIDO
 *
 * Nenhuma medicao aqui e da AWS: a Fase 7 mediu num laptop, com DynamoDB Local, que nao
 * estrangula e nao tem particao quente. Omitir isso transformaria o numero numa promessa
 * de desempenho em producao, que e exatamente o que ele nao e.
 *
 * Os valores sao transcritos de docs/testing/phase-5-report.md, phase-7-report.md e
 * COSTS.md. Mudar um relatorio e nao mudar aqui cria duas verdades — por isso cada
 * bloco linka a fonte.
 */

const REPO = "https://github.com/Buenno0/nexus-architecture/blob/main/";

interface Medida {
  nome: string;
  linhas: { valor: string; rotulo: string }[];
  onde: string;
  fonte: string;
  href: string;
}

const MEDIDAS: Medida[] = [
  {
    nome: "Vazão, por caminho isolado",
    linhas: [
      { valor: "571,5", rotulo: "replay — uma leitura" },
      { valor: "247,8", rotulo: "duplicata — leitura e consulta" },
      { valor: "103,8", rotulo: "novo — transação, trilha e fila" },
    ],
    onde: "req/s com 200 usuários, local. 5,5× entre o caminho mais barato e o mais caro.",
    fonte: "Relatório de desempenho",
    href: `${REPO}docs/testing/phase-7-report.md`,
  },
  {
    nome: "Onde vai o tempo de uma escrita",
    linhas: [
      { valor: "9 ms", rotulo: "núcleo — 56%" },
      { valor: "4 ms", rotulo: "trilha — 25%" },
      { valor: "4 ms", rotulo: "publicação na fila — 25%" },
    ],
    onde: "Regime não saturado. Sob saturação a dispersão chega a 40% e a conta não fecha.",
    fonte: "Relatório de desempenho",
    href: `${REPO}docs/testing/phase-7-report.md`,
  },
  {
    nome: "Custo real na AWS",
    linhas: [
      { valor: "US$ 0,0001", rotulo: "três dias no ar" },
      { valor: "712×", rotulo: "o que provisionado custaria" },
    ],
    onde: "Provisionar 25 unidades na tabela e nos quatro índices daria US$ 56,94/mês contra US$ 0,08.",
    fonte: "Registro de custos",
    href: `${REPO}COSTS.md`,
  },
  {
    nome: "Qualidade da comparação",
    linhas: [
      { valor: "0,9823", rotulo: "recall na primeira execução" },
      { valor: "1,0000", rotulo: "depois da correção" },
    ],
    onde: "Sem nenhum falso positivo novo. Contra dados sintéticos com gabarito — não prevê dados reais.",
    fonte: "Avaliação da resolução",
    href: `${REPO}docs/testing/phase-5-report.md`,
  },
];

interface Erro {
  titulo: string;
  conclui: string;
  era: string;
}

const ERROS: Erro[] = [
  {
    titulo: "Tratei uma corrida única como conclusão — duas vezes, com sinais opostos",
    conclui: "“Mais processos pioram o sistema”: 163 contra 150 req/s.",
    era: "Repetindo três vezes com estado zerado, 90,4 contra 87,8 — 3% de diferença dentro de uma dispersão de 10% a 26%. As duas conclusões anteriores eram ruído lido como sinal.",
  },
  {
    titulo: "Alternei configurações achando que isso cancelaria a deriva",
    conclui: "Rodei w1, w4, w1, w4 sem reiniciar, supondo que a alternância neutralizaria o crescimento do acervo.",
    era: "A tabela cresce o tempo todo, então quem roda em segundo lugar sempre enfrenta um acervo maior. A queda de 210 para 153 para 137 era a deriva, não a configuração.",
  },
  {
    titulo: "“Isolei” um cenário sem isolar nada",
    conclui: "Teto do replay: 117,6 req/s.",
    era: "Eu fiz as outras tarefas retornarem cedo, mas o Locust continua aplicando a espera depois delas. O número medido era a aritmética dos pesos. Removendo a tarefa da lista, o teto real é 571,5 req/s — quase cinco vezes maior.",
  },
  {
    titulo: "Medi o custo de um trabalho sob saturação",
    conclui: "“A trilha dobra a latência”: 147 contra 128 req/s com 200 usuários.",
    era: "Sob saturação quase todo o tempo é espera em fila, e fila amplifica qualquer ruído: o coeficiente de variação ficou entre 30% e 40%. Fora da saturação ele caiu para 1% e o custo apareceu limpo — 4 ms.",
  },
];

export function Medicoes() {
  return (
    <section className="secao" aria-labelledby="medicoes-titulo">
      <p className="sobrelinha">Evidências</p>
      <h2 className="titulo" id="medicoes-titulo">
        O que eu medi — e onde errei
      </h2>
      <p className="lead">
        Nenhum número aqui veio de uma corrida só, e nenhum foi medido na AWS. As duas
        frases custaram quatro erros para serem escritas.
      </p>

      <div className="medidas">
        {MEDIDAS.map((medida) => (
          <article className="medida" key={medida.nome}>
            <h3 className="medida__nome">{medida.nome}</h3>
            <dl className="medida__linhas">
              {medida.linhas.map((linha) => (
                <div className="medida__linha" key={linha.rotulo}>
                  <dt className="medida__valor">{linha.valor}</dt>
                  <dd className="medida__rotulo">{linha.rotulo}</dd>
                </div>
              ))}
            </dl>
            <p className="medida__onde">{medida.onde}</p>
            <a className="decisao__fonte" href={medida.href}>
              {medida.fonte}
            </a>
          </article>
        ))}
      </div>

      <h3 className="medicoes__subtitulo">Os quatro erros</h3>
      <p className="medicoes__intro">
        Não são defeitos do código. São erros meus de método, e continuam versionados
        junto dos relatórios — inclusive as corridas inconclusivas.
      </p>

      <ol className="erros">
        {ERROS.map((erro) => (
          <li className="erro" key={erro.titulo}>
            <h4 className="erro__titulo">{erro.titulo}</h4>
            <p className="erro__linha erro__linha--errada">
              <span className="erro__marca">Eu concluí</span>
              {erro.conclui}
            </p>
            <p className="erro__linha erro__linha--certa">
              <span className="erro__marca">Era</span>
              {erro.era}
            </p>
          </li>
        ))}
      </ol>

      <blockquote className="licao">
        <p>
          O padrão comum aos quatro: eu olhei um número, formei uma explicação plausível e
          a publiquei. A explicação plausível foi errada todas as vezes.
        </p>
        <p className="licao__antidoto">
          O único antídoto que funcionou foi repetir a medição e olhar a dispersão antes
          de olhar a diferença.
        </p>
      </blockquote>

      <p className="medicoes__rodape">
        A disciplina vale também para o que ainda não sei: o cold start das funções foi
        medido depois do deploy — 1.416 ms na API, 732 ms no dispatcher, 573 ms no worker
        —, mas é <strong>uma observação por função</strong>. Pela lição acima, isso não é
        uma medição, e está escrito assim no relatório.{" "}
        <a href={`${REPO}docs/testing/phase-9-report.md`}>Ver a verificação do deploy</a>
      </p>
    </section>
  );
}
