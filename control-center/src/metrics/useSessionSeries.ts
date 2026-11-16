/**
 * Acumula series temporais enquanto a pagina esta aberta.
 *
 * O backend nao guarda historico; estas series existem so aqui. Por isso tudo que sai
 * deste hook e rotulado como origem "sessao" na interface — ver ADR-009.
 */

import { useEffect, useRef, useState } from "react";

import { HistoricoDeSessao } from "./history";
import type { Ponto } from "./history";
import { MedidorDeTaxa } from "./rate";

/**
 * Registra um ponto por atualizacao de `valores`.
 *
 * `chaveDeAtualizacao` evita registrar o mesmo ponto duas vezes quando o React
 * re-renderiza sem dado novo — tipicamente o carimbo da ultima busca bem-sucedida.
 */
export function useSessionSeries(
  valores: Record<string, number> | null,
  chaveDeAtualizacao: number | undefined,
): readonly Ponto[] {
  const historico = useRef(new HistoricoDeSessao());
  const ultimaChave = useRef<number | undefined>(undefined);
  const [pontos, setPontos] = useState<readonly Ponto[]>([]);

  useEffect(() => {
    if (!valores || chaveDeAtualizacao === undefined) return;
    if (ultimaChave.current === chaveDeAtualizacao) return;
    ultimaChave.current = chaveDeAtualizacao;
    historico.current.registrar(valores, chaveDeAtualizacao);
    setPontos([...historico.current.listar()]);
  }, [valores, chaveDeAtualizacao]);

  return pontos;
}

/** Converte contadores cumulativos em taxas por segundo, serie a serie. */
export function useRates(
  contadores: Record<string, number> | null,
  chaveDeAtualizacao: number | undefined,
  instancia: string | undefined,
): { taxas: Record<string, number>; instante: number | undefined } {
  const medidores = useRef(new Map<string, MedidorDeTaxa>());
  const ultimaInstancia = useRef<string | undefined>(undefined);
  const ultimaChave = useRef<number | undefined>(undefined);
  const [resultado, setResultado] = useState<{ taxas: Record<string, number>; instante: number | undefined }>({ taxas: {}, instante: undefined });

  useEffect(() => {
    if (!contadores || chaveDeAtualizacao === undefined) return;
    if (ultimaChave.current === chaveDeAtualizacao) return;
    ultimaChave.current = chaveDeAtualizacao;

    if (!instancia || instancia !== ultimaInstancia.current) {
      medidores.current.clear();
      ultimaInstancia.current = instancia;
    }

    const proximas: Record<string, number> = {};
    for (const [chave, valor] of Object.entries(contadores)) {
      let medidor = medidores.current.get(chave);
      if (!medidor) {
        medidor = new MedidorDeTaxa();
        medidores.current.set(chave, medidor);
      }
      const taxa = medidor.medir(valor, chaveDeAtualizacao);
      // null = primeira leitura ou reinicio da API. Omitir e mais honesto que zerar.
      if (instancia && taxa !== null) proximas[chave] = taxa;
    }
    setResultado({ taxas: proximas, instante: chaveDeAtualizacao });
  }, [contadores, chaveDeAtualizacao, instancia]);

  return resultado;
}
