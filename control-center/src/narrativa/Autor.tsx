/**
 * Secao 7 — quem fez.
 *
 * Fecha a pagina onde ela comecou: uma pessoa respondendo uma pergunta. Depois de
 * cinco secoes de sistema, o visitante precisa saber de quem e aquilo e como falar com
 * essa pessoa — e um recrutador chega aqui procurando exatamente isso.
 *
 * So entram links verificaveis. Um contato errado numa pagina de portfolio custa a
 * vaga inteira, entao nada aqui e deduzido ou suposto.
 */

const REPO = "https://github.com/Buenno0/nexus-architecture";
const PERFIL = "https://github.com/Buenno0";
const DEMO = "https://nexus.mateus-bueno.dev";

export function Autor() {
  return (
    <section className="secao secao--autor" aria-labelledby="autor-titulo">
      <p className="sobrelinha">Quem fez</p>
      <h2 className="titulo" id="autor-titulo">
        Mateus Bueno
      </h2>

      <div className="autor">
        <div className="autor__texto">
          <p>
            Construí o Nexus para investigar uma pergunta inteira, do começo ao fim: como
            receber registros de fontes diferentes, decidir quais descrevem a mesma
            pessoa, e deixar essa decisão auditável. O projeto reúne a implementação, a
            infraestrutura, a interface e a documentação — porque nenhuma das quatro
            responde sozinha.
          </p>
          <p>
            Python com FastAPI e Pydantic, rodando em Lambda com Mangum. DynamoDB em
            tabela única com quatro índices, SQS com fila de falhas, Cognito e API
            Gateway, tudo em Terraform. O painel é React com TypeScript. A suíte roda
            inteira no CI, testes de integração incluídos, contra um DynamoDB local que
            sobe pelo mesmo compose do desenvolvimento.
          </p>
          <p className="autor__tese">
            A regra que governa o repositório: <strong>nenhuma capacidade não
            implementada é declarada em lugar nenhum</strong>. Quando um número não
            existe, está escrito que não existe. Quando uma conclusão estava errada, ela
            continua lá, marcada como errada.
          </p>
        </div>

        <ul className="autor__links">
          <li>
            <a className="autor__link" href={REPO}>
              Repositório do Nexus
              <span className="autor__link-nota">código, ADRs e relatórios</span>
            </a>
          </li>
          <li>
            <a className="autor__link" href={PERFIL}>
              Perfil no GitHub
              <span className="autor__link-nota">outros projetos</span>
            </a>
          </li>
          <li>
            <a className="autor__link" href={DEMO}>
              Demonstração pública
              <span className="autor__link-nota">esta página, no ar</span>
            </a>
          </li>
        </ul>
      </div>
    </section>
  );
}
