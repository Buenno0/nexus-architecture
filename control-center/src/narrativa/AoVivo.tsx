/**
 * Secao 6 — os numeros ao vivo.
 *
 * UMA CONSULTA, NAO UM LACO
 *
 * O painel atualiza a cada 30 segundos, e faz sentido para quem opera. Numa pagina
 * publica isso vira custo recorrente por visitante parado: alguem que abre a aba e vai
 * tomar cafe gera uma consulta por minuto a tarde inteira. Aqui a busca acontece uma
 * vez, quando a secao entra na tela, e a legenda diz o horario — um numero datado e
 * honesto, um numero que finge ser continuo nao e.
 *
 * O ADR-009 SOBREVIVE, MAIS QUIETO
 *
 * Todo numero continua declarando a origem, mas como marca discreta em vez de pilula
 * verde em cada cartao. E o que nao existe continua aparecendo como inexistente: sem
 * resposta da plataforma, a secao diz isso numa frase em vez de desenhar uma grade de
 * travessoes.
 */

import { useEffect, useRef, useState } from "react";

import { request } from "../api/client";
import type { Health, QueueStats, ResolutionStats } from "../api/types";

interface Numeros {
  saude: Health;
  fila: QueueStats;
  resolucao: ResolutionStats;
  em: Date;
}

function useNumerosAoVivo() {
  const [numeros, setNumeros] = useState<Numeros | null>(null);
  const [erro, setErro] = useState(false);
  const alvo = useRef<HTMLDivElement | null>(null);
  const buscou = useRef(false);

  useEffect(() => {
    const no = alvo.current;
    if (!no) return;

    const buscar = () => {
      if (buscou.current) return;
      buscou.current = true;
      void (async () => {
        try {
          const [saude, fila, resolucao] = await Promise.all([
            request<Health>("/health"),
            request<QueueStats>("/v1/ops/queue"),
            request<ResolutionStats>("/v1/resolution/stats"),
          ]);
          setNumeros({ saude, fila, resolucao, em: new Date() });
        } catch {
          setErro(true);
        }
      })();
    };

    // Sem IntersectionObserver (navegador antigo, ambiente de teste), busca na hora:
    // melhor uma consulta a mais do que a secao nunca mostrar nada.
    if (typeof IntersectionObserver === "undefined") {
      buscar();
      return;
    }
    const observador = new IntersectionObserver(
      (entradas) => {
        if (entradas.some((e) => e.isIntersecting)) {
          buscar();
          observador.disconnect();
        }
      },
      { rootMargin: "200px" },
    );
    observador.observe(no);
    return () => observador.disconnect();
  }, []);

  return { numeros, erro, alvo };
}

function contador(stats: ResolutionStats, chave: string): number | null {
  const valor = stats.counters[chave];
  return typeof valor === "number" ? valor : null;
}

export function AoVivo({ abrirConsole }: { abrirConsole: () => void }) {
  const { numeros, erro, alvo } = useNumerosAoVivo();

  return (
    <section className="secao" aria-labelledby="aovivo-titulo" ref={alvo}>
      <p className="sobrelinha">Agora</p>
      <h2 className="titulo" id="aovivo-titulo">
        O que a plataforma acumulou até aqui
      </h2>
      <p className="lead">
        Contadores gravados no banco, não em memória.
      </p>

      {erro ? (
        <p className="aviso" role="status">
          A plataforma não respondeu agora. Isso não significa que ela esteja fora — a
          consulta é única, então recarregue a página para tentar de novo.
        </p>
      ) : !numeros ? (
        <p className="legenda" role="status">
          Consultando a plataforma…
        </p>
      ) : (
        <Placar numeros={numeros} />
      )}

      <p className="aovivo__saida">
        Latência, fila, revisões e os onze ADRs estão no painel.{" "}
        <button type="button" className="elo" onClick={abrirConsole}>
          Abrir o painel técnico
        </button>
      </p>
    </section>
  );
}

function Placar({ numeros }: { numeros: Numeros }) {
  const { fila, resolucao } = numeros;
  const analisados = contador(resolucao, "records_analyzed");
  const correspondencias = contador(resolucao, "matches");
  const entidades = contador(resolucao, "entities_created");
  const comparados = contador(resolucao, "candidates_compared");

  // So entra na grade o que tem valor. Uma grade de travessoes nao informa nada e
  // faz a plataforma parecer quebrada — era o defeito do painel antigo.
  const itens = [
    { valor: analisados, nome: "registros analisados" },
    { valor: comparados, nome: "candidatos comparados" },
    { valor: correspondencias, nome: "correspondências encontradas" },
    { valor: entidades, nome: "entidades formadas" },
    { valor: resolucao.pending_reviews, nome: "pares aguardando revisão humana" },
    { valor: fila.pending, nome: "mensagens esperando na fila" },
  ].filter((item): item is { valor: number; nome: string } => item.valor !== null);

  if (itens.length === 0) {
    return (
      <p className="legenda">
        Ainda não há nada acumulado.
      </p>
    );
  }

  return (
    <>
      <dl className="placar">
        {itens.map((item) => (
          <div className="placar__item" key={item.nome}>
            <dt className="placar__valor">{item.valor.toLocaleString("pt-BR")}</dt>
            <dd className="placar__nome">{item.nome}</dd>
          </div>
        ))}
      </dl>
      <p className="placar__origem">
        Consultado às{" "}
        {numeros.em.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })},
        uma vez.
        {fila.dead > 0 ? (
          <>
            {" "}
            Há {fila.dead} mensagem(ns) na fila de falhas; o painel técnico mostra o
            alerta e permite devolvê-las.
          </>
        ) : null}
      </p>
    </>
  );
}
