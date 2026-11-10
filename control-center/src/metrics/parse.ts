/**
 * Leitura das chaves de metrica do Nexus.
 *
 * O backend serializa cada serie como `nome{rotulo=valor,outro=valor}`, com os rotulos
 * em ordem alfabetica (ver `_key` em `src/nexus/observability/metrics.py`).
 *
 * ## Por que nao basta um regex simples
 *
 * O valor de `path` pode conter chaves: a rota `/v1/records/{record_id}` produz
 *
 *     http_requests_total{method=GET,path=/v1/records/{record_id},status=200}
 *
 * Um regex como `/\{(.*?)\}/` casaria ate o primeiro `}`, cortando o rotulo no meio e
 * devolvendo um `path` truncado. Por isso a delimitacao usa o PRIMEIRO `{` e o ULTIMO
 * `}` da chave.
 */

export interface SerieDeMetrica {
  /** Nome sem os rotulos. */
  nome: string;
  rotulos: Record<string, string>;
  /** A chave original, util como identidade estavel de serie. */
  chave: string;
}

export function parseChave(chave: string): SerieDeMetrica {
  const abertura = chave.indexOf("{");
  const fechamento = chave.lastIndexOf("}");

  if (abertura === -1 || fechamento === -1 || fechamento < abertura) {
    return { nome: chave, rotulos: {}, chave };
  }

  const nome = chave.slice(0, abertura);
  const corpo = chave.slice(abertura + 1, fechamento);
  return { nome, rotulos: parseRotulos(corpo), chave };
}

function parseRotulos(corpo: string): Record<string, string> {
  const rotulos: Record<string, string> = {};
  if (corpo.length === 0) return rotulos;

  let ultimaChave: string | null = null;

  for (const parte of corpo.split(",")) {
    const igual = parte.indexOf("=");
    if (igual === -1) {
      // Sem `=`: a virgula pertencia ao valor anterior, nao separava rotulos.
      // Acontece com rotas que contenham virgula.
      if (ultimaChave !== null) {
        rotulos[ultimaChave] = `${rotulos[ultimaChave] ?? ""},${parte}`;
      }
      continue;
    }
    const nome = parte.slice(0, igual);
    // Divide no PRIMEIRO `=`: o valor pode conter outros.
    rotulos[nome] = parte.slice(igual + 1);
    ultimaChave = nome;
  }

  return rotulos;
}

/** Soma os contadores cujo nome casa, independentemente dos rotulos. */
export function somarPorNome(contadores: Record<string, number>, nome: string): number {
  let total = 0;
  for (const [chave, valor] of Object.entries(contadores)) {
    if (parseChave(chave).nome === nome) total += valor;
  }
  return total;
}

/** Agrupa os contadores de um nome pelo valor de um rotulo. */
export function agruparPorRotulo(
  contadores: Record<string, number>,
  nome: string,
  rotulo: string,
): Record<string, number> {
  const grupos: Record<string, number> = {};
  for (const [chave, valor] of Object.entries(contadores)) {
    const serie = parseChave(chave);
    if (serie.nome !== nome) continue;
    const grupo = serie.rotulos[rotulo] ?? "(sem rotulo)";
    grupos[grupo] = (grupos[grupo] ?? 0) + valor;
  }
  return grupos;
}
