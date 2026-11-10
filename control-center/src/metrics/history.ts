/**
 * Historico acumulado na sessao.
 *
 * O backend nao guarda serie temporal: os contadores sao cumulativos e a latencia e um
 * resumo. As series dos graficos sao montadas aqui, no navegador, a partir do polling.
 *
 * **Isso significa que o historico vive enquanto a aba vive.** Recarregar zera. A
 * interface rotula esses numeros como "sessao" justamente por isso — ver ADR-009.
 *
 * O limite de pontos existe para que uma aba esquecida aberta por horas nao consuma
 * memoria sem parar: a cada 3 segundos, 600 pontos sao 30 minutos de historico.
 */

export const MAX_PONTOS = 600;

export interface Ponto {
  instante: number;
  [serie: string]: number;
}

export class HistoricoDeSessao {
  private readonly pontos: Ponto[] = [];

  constructor(private readonly maximo: number = MAX_PONTOS) {}

  registrar(valores: Record<string, number>, instante: number = Date.now()): void {
    this.pontos.push({ instante, ...valores });
    // Buffer circular: descarta o mais antigo em vez de crescer.
    while (this.pontos.length > this.maximo) this.pontos.shift();
  }

  listar(): readonly Ponto[] {
    return this.pontos;
  }

  get tamanho(): number {
    return this.pontos.length;
  }

  /** Segundos cobertos pelo historico, ou 0 com menos de dois pontos. */
  get janelaSegundos(): number {
    if (this.pontos.length < 2) return 0;
    const primeiro = this.pontos[0];
    const ultimo = this.pontos[this.pontos.length - 1];
    if (!primeiro || !ultimo) return 0;
    return (ultimo.instante - primeiro.instante) / 1000;
  }

  limpar(): void {
    this.pontos.length = 0;
  }
}
