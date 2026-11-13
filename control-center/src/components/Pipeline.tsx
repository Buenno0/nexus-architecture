/**
 * Uma observacao atravessando a plataforma, passo a passo.
 *
 * **Nada aqui consulta a API.** E a explicacao do mecanismo em movimento, nao leitura
 * do estado real — e a tela diz isso em texto, porque numero simulado apresentado como
 * medicao e precisamente o que a secao 7 do projeto proibe. Os numeros reais estao nas
 * outras abas, cada um com a origem rotulada.
 *
 * Movimento foi a escolha certa aqui por um motivo especifico: as tres ideias mais
 * dificeis de transmitir sao temporais. A espera na fila, o intervalo crescente entre
 * retentativas e a trilha sendo escrita por dois processos diferentes viram setas num
 * desenho estatico, e seta nao distingue "imediato" de "oito segundos depois".
 */

import { useCallback, useEffect, useRef, useState } from "react";

import "./Pipeline.css";
import { OpButton } from "./OpButton";

type Servico = "api" | "worker" | "fila";

interface Etapa {
  nome: string;
  onde: Servico;
  titulo: string;
  texto: string;
  /** Marco gravado na trilha ao entrar nesta etapa — ADR-010. */
  marco?: string;
  /** Pausa antes da proxima etapa. A da fila e maior de proposito: e a espera. */
  duracaoMs: number;
  espera?: boolean;
  erro?: boolean;
}

const FELIZ: Etapa[] = [
  {
    nome: "aceita",
    onde: "api",
    titulo: "POST /v1/records/person",
    texto:
      "Chega com Idempotency-Key. A mesma chave nunca produz duas observacoes: a repeticao devolve a resposta guardada, sem efeito novo.",
    marco: "accepted",
    duracaoMs: 1100,
  },
  {
    nome: "valida",
    onde: "api",
    titulo: "Validacao na borda",
    texto:
      "Pydantic recusa payload invalido aqui, com 422. Nada invalido alcanca a persistencia, e o resto do sistema fica livre de verificacoes defensivas espalhadas.",
    duracaoMs: 1000,
  },
  {
    nome: "grava",
    onde: "api",
    titulo: "TransactWriteItems",
    texto:
      "Observacao, evento de outbox e registro de idempotencia numa unica transacao. Ou os tres existem, ou nenhum — e o que impede o registro salvo e nunca processado.",
    duracaoMs: 1300,
  },
  {
    nome: "publica",
    onde: "api",
    titulo: "Publicacao na fila",
    texto:
      "Best-effort: se falhar, o evento continua pendente num indice esparso e o despachante o recupera depois. Perder o evento seria inaceitavel; publica-lo duas vezes, nao.",
    marco: "published",
    duracaoMs: 1200,
  },
  {
    nome: "espera",
    onde: "fila",
    titulo: "A mensagem aguarda",
    texto:
      "Nada acontece aqui — e esse nada e o diagnostico. O tempo entre 'published' e 'consumed' e espera na fila, e nenhuma otimizacao do processador o recupera. E por isso que a trilha mede o intervalo entre marcos, nao so o total.",
    duracaoMs: 2600,
    espera: true,
  },
  {
    nome: "consome",
    onde: "worker",
    titulo: "Worker consome o lote",
    texto:
      "Outro processo, outro log. Antes de processar, consulta o marcador: reentrega encontra o marcador e nao processa de novo. A entrega e at-least-once por construcao.",
    marco: "consumed",
    duracaoMs: 1300,
  },
  {
    nome: "resolve",
    onde: "worker",
    titulo: "Resolucao de identidade",
    texto:
      "Blocking seleciona candidatos, o score compara campo a campo, e a decisao tem tres faixas. Em duvida, vai para revisao humana — nunca funde no palpite.",
    marco: "resolved",
    duracaoMs: 1400,
  },
];

const FALHA: Etapa[] = [
  ...FELIZ.slice(0, 5),
  {
    nome: "falha",
    onde: "worker",
    titulo: "1a tentativa falha",
    texto:
      "O processamento levanta erro. A mensagem nao e confirmada e volta a ficar visivel na fila depois do prazo de visibilidade.",
    marco: "failed",
    duracaoMs: 1300,
    erro: true,
  },
  {
    nome: "retenta",
    onde: "fila",
    titulo: "2a e 3a tentativas",
    texto:
      "Backoff exponencial: cada retentativa espera mais que a anterior. Sem isso, um erro persistente vira um laco apertado que consome a fila inteira.",
    duracaoMs: 2400,
    espera: true,
    erro: true,
  },
  {
    nome: "DLQ",
    onde: "fila",
    titulo: "Dead letter queue",
    texto:
      "Esgotadas as tentativas, a mensagem sai do caminho quente e fica na DLQ: visivel, inspecionavel e devolvivel por um redrive explicito. Ela nao some — e um alerta acende sozinho.",
    marco: "dead_lettered",
    duracaoMs: 1500,
    erro: true,
  },
];

interface Marco {
  nome: string;
  servico: Servico;
  erro: boolean;
}

export function Pipeline() {
  const [roteiro, setRoteiro] = useState<Etapa[]>(FELIZ);
  const [indice, setIndice] = useState(-1);
  const [marcos, setMarcos] = useState<Marco[]>([]);
  const [rodando, setRodando] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  const parar = useCallback(() => {
    if (timer.current !== undefined) window.clearTimeout(timer.current);
    timer.current = undefined;
  }, []);

  // Um unico efeito conduz a sequencia. Agendar o proximo passo de dentro do
  // callback anterior criaria uma cadeia que o unmount nao cancela.
  useEffect(() => {
    if (indice < 0 || indice >= roteiro.length) return;
    const etapa = roteiro[indice];
    if (!etapa) return;
    if (etapa.marco) {
      setMarcos((atuais) => [
        ...atuais,
        { nome: etapa.marco as string, servico: etapa.onde, erro: etapa.erro ?? false },
      ]);
    }
    if (indice === roteiro.length - 1) return;
    timer.current = window.setTimeout(() => setIndice((i) => i + 1), etapa.duracaoMs);
    return parar;
  }, [indice, roteiro, parar]);

  useEffect(() => parar, [parar]);

  // Devolve uma promessa que resolve quando a sequencia termina: e assim que o
  // OpButton sabe mostrar "executando…" e voltar sozinho ao fim, sem eu duplicar o
  // controle de estado do botao aqui dentro.
  function executar(novo: Etapa[]): Promise<void> {
    parar();
    setRoteiro(novo);
    setMarcos([]);
    setIndice(0);
    const total = novo.reduce((soma, e) => soma + e.duracaoMs, 0);
    return new Promise((resolver) => {
      window.setTimeout(() => {
        setRodando(false);
        resolver();
      }, total);
    });
  }

  const etapa = indice >= 0 ? roteiro[indice] : undefined;
  const posicao = `${((Math.max(indice, 0) + 0.5) / roteiro.length) * 100}%`;

  return (
    <div className="pipe">
      <div className="pipe__controles">
        <OpButton
          rotulo="Executar uma observacao"
          onExecutar={() => {
            setRodando(true);
            return executar(FELIZ);
          }}
          desabilitado={rodando}
          dica="Percorre o caminho feliz, da chamada HTTP ate a decisao de identidade."
        />
        <OpButton
          rotulo="Simular uma falha"
          onExecutar={() => {
            setRodando(true);
            return executar(FALHA);
          }}
          desabilitado={rodando}
          variante="perigo"
          dica="Mesmo inicio, mas o processamento falha: retentativa com backoff e DLQ."
        />
      </div>

      <div className="pipe__trilho">
        {roteiro.map((e, i) => (
          <div
            key={e.nome}
            className={[
              "pipe__etapa",
              i < indice ? "pipe__etapa--feita" : "",
              i === indice ? "pipe__etapa--ativa" : "",
              e.erro ? "pipe__etapa--falha" : "",
            ]
              .filter(Boolean)
              .join(" ")}
          >
            <span className="pipe__nome">{e.nome}</span>
            <span className="pipe__onde">{e.onde}</span>
          </div>
        ))}
        <span
          className={[
            "pipe__token",
            indice < 0 ? "pipe__token--parado" : "",
            etapa?.espera ? "pipe__token--esperando" : "",
            etapa?.erro ? "pipe__token--falha" : "",
          ]
            .filter(Boolean)
            .join(" ")}
          style={{ "--pos": posicao } as React.CSSProperties}
          aria-hidden="true"
        />
      </div>

      <div
        className={`pipe__legenda ${etapa?.erro ? "pipe__legenda--falha" : ""}`}
        aria-live="polite"
      >
        <p className="pipe__legenda-titulo">
          {etapa ? etapa.titulo : "Aperte um dos botoes acima"}
        </p>
        <p className="pipe__legenda-texto">
          {etapa
            ? etapa.texto
            : "A sequencia percorre o caminho real de um registro, da chamada HTTP ate a decisao de identidade — ou ate a DLQ, se voce escolher a falha."}
        </p>
      </div>

      <div className="pipe__trilha">
        <div className="pipe__trilha-titulo">
          Trilha — marcos gravados, com o processo que emitiu cada um
        </div>
        <div className="pipe__marcos">
          {marcos.length === 0 && (
            <span className="pipe__legenda-texto">
              Nenhum marco ainda.
            </span>
          )}
          {marcos.map((m) => (
            <span
              key={m.nome}
              className={`pipe__marco ${m.erro ? "pipe__marco--erro" : ""}`}
            >
              {m.nome}
              <span className="pipe__marco-servico">{m.servico}</span>
            </span>
          ))}
        </div>
      </div>

      <p className="pipe__aviso">
        Esta animacao e uma explicacao do mecanismo, nao uma leitura do sistema. Nenhum
        numero aqui vem da API — os reais estao nas outras abas, cada um com a origem
        rotulada.
      </p>
    </div>
  );
}
