/**
 * Conversao da serie persistida para os pontos do grafico — ADR-010.
 *
 * A serie da Fase 6 vem do armazenamento em baldes de tempo fixos. O `Ponto` dos
 * graficos usa milissegundos de epoca; a conversao e so isso.
 */

import type { Ponto } from "./history";
import type { Series, SeriesPoint } from "../api/types";

/**
 * Converte amostras em pontos, renomeando as chaves para os rotulos do grafico.
 *
 * `mapa` traduz o nome gravado (`queue_pending`) para o nome da serie no grafico
 * (`aguardando`). Amostras que nao trazem a chave sao mantidas sem ela, em vez de
 * receber zero: o grafico interrompe a linha, que e a representacao correta de um
 * balde em que a fonte estava indisponivel.
 */
export function paraPontos(
  amostras: readonly SeriesPoint[],
  mapa: Record<string, string>,
  intervaloSegundos?: number,
): Ponto[] {
  const pontos: Ponto[] = [];
  const passo = (intervaloSegundos ?? 0) * 1000;
  let anterior: number | null = null;

  for (const amostra of amostras) {
    const instante = new Date(amostra.bucket).getTime();

    // Balde ausente vira um ponto sem nenhuma serie. Com `connectNulls` desligado, a
    // linha se parte ali — que e a representacao correta de um periodo nao medido.
    // Sem isso, a janela sem amostra viraria um segmento reto entre dois instantes
    // distantes, e o grafico afirmaria que o valor se manteve estavel durante um
    // intervalo em que ninguem olhou.
    if (passo > 0 && anterior !== null && instante - anterior > passo) {
      pontos.push({ instante: anterior + passo });
    }

    const ponto: Ponto = { instante };
    for (const [gravado, rotulo] of Object.entries(mapa)) {
      const valor = amostra.values[gravado];
      if (valor !== undefined) ponto[rotulo] = valor;
    }
    pontos.push(ponto);
    anterior = instante;
  }

  return pontos;
}

/**
 * Frase que explica o estado da serie, incluindo os buracos.
 *
 * A amostragem e oportunista: sem ninguem observando, nada e amostrado. Dizer isso e
 * melhor que desenhar uma reta sobre um periodo que ninguem mediu.
 */
export function descreverCobertura(serie: Series | undefined): string {
  if (!serie) return "Carregando a serie persistida.";
  if (serie.points.length === 0) {
    return (
      `Nenhuma amostra nos ultimos ${serie.window_minutes} minutos. ` +
      "A amostragem e oportunista: a serie so avanca quando alguem consulta a plataforma."
    );
  }
  const total = serie.points.length + serie.gaps;
  const cobertura = Math.round((serie.points.length / total) * 100);
  const base =
    `${serie.points.length} amostras de ${serie.interval_seconds}s em ` +
    `${serie.window_minutes} minutos (${cobertura}% da janela).`;
  return serie.gaps === 0
    ? base
    : `${base} Os ${serie.gaps} baldes restantes nao foram medidos e aparecem como ` +
        "interrupcao, nao como zero.";
}
