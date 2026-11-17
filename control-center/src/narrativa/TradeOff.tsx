/**
 * O par de comparacao de uma decisao.
 *
 * A mesma falha nos dois lados — e isso que torna a comparacao justa. Um desenho em
 * que o lado "errado" falha e o lado "certo" nao falha nao compara nada: so afirma
 * que a escolha foi boa. Aqui a rede cai nos dois; o que muda e o que sobra depois.
 *
 * O custo fica no rodape, sempre. Uma decisao apresentada sem o preco dela e
 * propaganda, nao engenharia.
 */

export interface Caminho {
  titulo: string;
  passos: { nome: string; detalhe: string; tom: "neutro" | "falha" | "bom" }[];
}

export function TradeOff({
  esquerda,
  direita,
  custo,
}: {
  esquerda: Caminho;
  direita: Caminho;
  custo: string;
}) {
  return (
    <figure className="tradeoff">
      <div className="tradeoff__par">
        {[esquerda, direita].map((caminho) => (
          <div className="caminho" key={caminho.titulo}>
            <p className="caminho__titulo">{caminho.titulo}</p>
            <ol className="caminho__passos">
              {caminho.passos.map((passo) => (
                <li className={`passo passo--${passo.tom}`} key={passo.nome}>
                  <span className="passo__nome">{passo.nome}</span>
                  <span className="passo__detalhe">{passo.detalhe}</span>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </div>
      <figcaption className="tradeoff__custo">
        <strong>O que isso custa:</strong> {custo}
      </figcaption>
    </figure>
  );
}
