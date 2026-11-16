/**
 * Secao 1 — a pergunta.
 *
 * O topo da pagina nao e um diagrama de arquitetura. E a pergunta que o sistema
 * existe para responder, escrita de um jeito que alguem de fora entenda sem
 * saber o que e uma fila.
 *
 * O par abaixo e um exemplo fixo, e esta rotulado como tal. Ele reproduz uma
 * variacao que o gerador sintetico do projeto realmente produz — abreviar o nome
 * do meio e omitir o telefone (ver `vary` em src/nexus/demo/synthetic.py) — para
 * que a ilustracao e a plataforma nao contem historias diferentes.
 */

const PAR = [
  {
    fonte: "Cadastro do site",
    nome: "Mariana Ferraz Guimarães",
    campos: [
      { rotulo: "E-mail", valor: "mariana.guimaraes@exemplo.com", igual: true },
      { rotulo: "Telefone", valor: "(11) 98412-7730", igual: false },
    ],
  },
  {
    fonte: "Planilha importada",
    nome: "Mariana F. Guimarães",
    campos: [
      { rotulo: "E-mail", valor: "mariana.guimaraes@exemplo.com", igual: true },
      { rotulo: "Telefone", valor: "não informado", igual: false },
    ],
  },
] as const;

export function Pergunta() {
  return (
    <section className="secao secao--pergunta" aria-labelledby="pergunta-titulo">
      <p className="sobrelinha">Resolução de identidade</p>

      <h1 className="pergunta__titulo" id="pergunta-titulo">
        Essas duas pessoas <em>são a mesma pessoa?</em>
      </h1>

      <p className="pergunta__lead">
        Toda empresa que recebe dados de mais de um lugar acaba com esta pergunta na
        mesa. O Nexus é um sistema que a responde — e que mostra por que respondeu.
      </p>

      <div className="par" role="group" aria-label="Dois registros vindos de fontes diferentes">
        {PAR.map((registro) => (
          <article className="ficha" key={registro.fonte}>
            <p className="ficha__fonte">{registro.fonte}</p>
            <p className="ficha__nome">{registro.nome}</p>
            <dl className="ficha__campos">
              {registro.campos.map((campo) => (
                <div className="ficha__campo" key={campo.rotulo}>
                  <dt>{campo.rotulo}</dt>
                  <dd className={campo.igual ? "ficha__valor ficha__valor--igual" : "ficha__valor"}>
                    {campo.valor}
                  </dd>
                </div>
              ))}
            </dl>
          </article>
        ))}
      </div>

      <p className="par__nota">
        Exemplo ilustrativo. O e-mail destacado é idêntico nos dois; o nome não.
      </p>

      <div className="pergunta__consequencia">
        <p>
          <strong>Errar para os dois lados custa caro.</strong> Tratar os dois como
          pessoas diferentes duplica o cadastro, e a mesma pessoa passa a receber tudo
          em dobro. Juntá-los sem cuidado mistura duas pessoas num registro só — e aí o
          erro vai junto para todo lugar que consome esse dado.
        </p>
      </div>
    </section>
  );
}
