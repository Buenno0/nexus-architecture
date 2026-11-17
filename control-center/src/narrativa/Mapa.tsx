/**
 * O mapa do sistema.
 *
 * HTML, nao SVG. Um SVG de 680px de largura escala para caber num celular de 375 e
 * leva o texto junto: rotulo de 14px vira 7px. A alternativa seria rolagem lateral, que
 * e justamente o que foi tirado do desenho antigo. Em HTML os nos reflui­rem e o texto
 * continua do tamanho que foi escrito.
 *
 * O mapa nao repete o percurso da secao 2. Aquele mostra POR ONDE o registro passa;
 * este mostra duas coisas que o outro nao diz: o que e alcancavel de fora, e quem
 * espera por quem.
 */

const ADR = "https://github.com/Buenno0/nexus-architecture/blob/main/docs/adr/";

export function Mapa() {
  return (
    <figure className="mapa">
      <div className="mapa__fluxo">
        <div className="no no--externo">
          <p className="no__nome">Cliente</p>
          <p className="no__faz">navegador de quem visita</p>
        </div>

        {/* Sincrono: a resposta da API depende deste salto. */}
        <div className="elo">
          <span className="elo__linha elo__linha--sincrona" aria-hidden="true" />
          <span className="elo__texto">Síncrono — o cliente espera a resposta</span>
        </div>

        <div className="fronteira">
          <p className="fronteira__rotulo">Fronteira de confiança</p>

          <div className="no no--servico">
            <p className="no__nome">Serviço de API</p>
            <p className="no__faz">aceita, valida, enfileira — e para por aí</p>
          </div>

          <div className="elo">
            <span className="elo__linha elo__linha--assincrona" aria-hidden="true" />
            <span className="elo__texto">Assíncrono — ninguém espera daqui para baixo</span>
          </div>

          <div className="no no--infra">
            <p className="no__nome">Fila de mensagens</p>
            <p className="no__faz">alimentada pelo outbox</p>
          </div>

          <div className="elo">
            <span className="elo__linha elo__linha--assincrona" aria-hidden="true" />
            <span className="elo__texto">Só anda quando alguém pede</span>
          </div>

          <div className="no no--servico">
            <p className="no__nome">Worker</p>
            <p className="no__faz">compara, decide e grava a evidência</p>
          </div>
        </div>
      </div>

      <aside className="mapa__dado">
        <div className="no no--dado">
          <p className="no__nome">Armazenamento</p>
          <p className="no__faz">DynamoDB, tabela única</p>
        </div>
        <p className="mapa__dado-nota">
          A API grava o registro na entrada. O worker grava a decisão depois, no mesmo
          lugar.
        </p>
      </aside>

      <figcaption className="mapa__legenda">
        Só a API é alcançável de fora. Na demonstração pública, nem toda ela: as rotas de
        ingestão livre saem do roteamento do gateway <em>e</em> respondem 404 na
        aplicação — duas camadas, porque uma delas pode ser esquecida num deploy.{" "}
        <a href={`${ADR}ADR-011-demonstracao-somente-leitura.md`}>
          Ler a decisão sobre a demonstração
        </a>
      </figcaption>
    </figure>
  );
}
