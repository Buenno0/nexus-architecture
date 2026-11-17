/**
 * Secao 4 — por que e dificil.
 *
 * Primeiro a orientacao (o mapa), depois o julgamento (as decisoes). Quem le na ordem
 * recebe o "onde" antes do "por que", e quem pula direto para uma decisao ainda
 * entende, porque cada uma e autocontida.
 *
 * Cada decisao segue a mesma forma: o problema, a escolha, e o que ela custa. O custo
 * nao e uma ressalva envergonhada no fim — e a parte que mostra que a escolha foi
 * feita com os olhos abertos.
 */

import { Mapa } from "./Mapa";
import { TradeOff } from "./TradeOff";

const ADR = "https://github.com/Buenno0/nexus-architecture/blob/main/docs/adr/";

export function Decisoes() {
  return (
    <section className="secao" aria-labelledby="decisoes-titulo">
      <p className="sobrelinha">Por trás da cena</p>
      <h2 className="titulo" id="decisoes-titulo">
        Como o sistema é montado, e o que cada escolha custou
      </h2>
      <p className="lead">
        Três decisões sustentam o que você acabou de ver acontecer. Nenhuma delas é de
        graça.
      </p>

      <Mapa />

      <div className="decisoes">
        <details className="decisao" open>
          <summary className="decisao__resumo">
            <span className="decisao__pergunta">E se a publicação na fila falhar?</span>
            <span className="decisao__dica">
              Registro e evento precisam continuar juntos
            </span>
          </summary>
          <div className="decisao__corpo">
            <p>
              A API grava a observação e o evento que a processa na{" "}
              <strong>mesma transação</strong>. Se a publicação falhar depois disso, o
              evento continua pendente no armazenamento e um dispatcher o republica.
            </p>

            <TradeOff
              esquerda={{
                titulo: "Sem outbox",
                passos: [
                  { nome: "Grava o registro", detalhe: "uma escrita", tom: "neutro" },
                  { nome: "Publica na fila", detalhe: "a rede falha aqui", tom: "falha" },
                  {
                    nome: "O evento some",
                    detalhe: "ninguém fica sabendo que faltou",
                    tom: "falha",
                  },
                ],
              }}
              direita={{
                titulo: "Com outbox",
                passos: [
                  {
                    nome: "Grava registro e evento",
                    detalhe: "na mesma transação",
                    tom: "bom",
                  },
                  { nome: "Publica na fila", detalhe: "a rede falha aqui", tom: "falha" },
                  {
                    nome: "Dispatcher republica",
                    detalhe: "o evento ficou pendente",
                    tom: "bom",
                  },
                ],
              }}
              custo="o worker passa a receber a mesma mensagem mais de uma vez, e precisa
                suportar isso. Por isso existe um segundo ponto de idempotência no consumo."
            />

            <a className="decisao__fonte" href={`${ADR}ADR-003-transactional-outbox.md`}>
              Ler a decisão sobre transactional outbox
            </a>
          </div>
        </details>

        <details className="decisao">
          <summary className="decisao__resumo">
            <span className="decisao__pergunta">E se a mesma requisição chegar duas vezes?</span>
            <span className="decisao__dica">
              Repetir uma operação não pode criar outro registro
            </span>
          </summary>
          <div className="decisao__corpo">
            <p>
              Uma chave de idempotência identifica a operação. A mesma chave com o mesmo
              conteúdo devolve a resposta anterior; com conteúdo diferente, responde
              conflito.
            </p>
            <p>
              São <strong>três conceitos de identidade separados de propósito</strong>: a
              chave diz que é a mesma operação, a impressão do conteúdo diz que é o mesmo
              dado, e a resolução de identidade diz que é a mesma pessoa. Derivar a
              primeira da chave natural pareceria economia — mas aí a mesma pessoa
              chegando com o telefone atualizado produziria a mesma chave, e a
              atualização seria descartada em silêncio. Isso não é deduplicação, é perda
              de dado.
            </p>
            <a className="decisao__fonte" href={`${ADR}ADR-002-identidade-e-idempotencia.md`}>
              Ler a decisão sobre identidade e idempotência
            </a>
          </div>
        </details>

        <details className="decisao">
          <summary className="decisao__resumo">
            <span className="decisao__pergunta">E quando a comparação fica no meio?</span>
            <span className="decisao__dica">Existe uma faixa que ninguém funde sozinho</span>
          </summary>
          <div className="decisao__corpo">
            <p>
              A comparação pesa cada campo disponível. Acima do limiar, associa; abaixo,
              descarta. No meio existe uma terceira resposta: o par vira um item de
              revisão humana e <strong>nunca é fundido automaticamente</strong>.
            </p>
            <p>
              Os pesos e limiares são parâmetros calibrados, não verdades. A avaliação
              usa dados sintéticos com gabarito conhecido — ela permite investigar erros
              nesse conjunto, não prever desempenho com dados reais.
            </p>
            <a className="decisao__fonte" href={`${ADR}ADR-006-entity-resolution.md`}>
              Ler a decisão sobre resolução de identidade
            </a>
          </div>
        </details>
      </div>
    </section>
  );
}
