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
            Construí o Nexus sozinho, de ponta a ponta: backend, infraestrutura,
            interface, testes e medição.
          </p>
          <p className="autor__tese">
            Python · FastAPI · AWS Lambda · DynamoDB · SQS · Terraform · React ·
            TypeScript
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
