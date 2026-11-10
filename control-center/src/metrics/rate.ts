/**
 * Taxa por segundo a partir de contadores cumulativos.
 *
 * O `/metrics` entrega totais acumulados, nao taxas. "Requisicoes por segundo" sai da
 * diferenca entre duas leituras dividida pelo tempo entre elas.
 */

export interface Amostra {
  valor: number;
  instante: number;
}

/**
 * Calcula a taxa entre duas amostras.
 *
 * Devolve `null` quando a taxa nao pode ser afirmada:
 *
 * - **O contador diminuiu.** Contador cumulativo nao anda para tras; isso significa
 *   que a API reiniciou e zerou os contadores em processo. A diferenca seria uma taxa
 *   negativa sem sentido, e tratar como zero inventaria um periodo de ociosidade que
 *   nao houve. Descartar a amostra e a unica leitura honesta.
 * - **Tempo nao positivo**, que produziria divisao invalida.
 */
export function taxaPorSegundo(anterior: Amostra, atual: Amostra): number | null {
  const intervaloMs = atual.instante - anterior.instante;
  if (intervaloMs <= 0) return null;
  if (atual.valor < anterior.valor) return null;
  return ((atual.valor - anterior.valor) * 1000) / intervaloMs;
}

/** Acompanha uma serie de contador e devolve a taxa a cada nova leitura. */
export class MedidorDeTaxa {
  private anterior: Amostra | null = null;

  medir(valor: number, instante: number = Date.now()): number | null {
    const atual: Amostra = { valor, instante };
    const anterior = this.anterior;
    this.anterior = atual;
    if (anterior === null) return null; // primeira leitura nao tem com o que comparar
    return taxaPorSegundo(anterior, atual);
  }

  reset(): void {
    this.anterior = null;
  }
}
