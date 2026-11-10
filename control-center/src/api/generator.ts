/**
 * Gerador de registros sinteticos no navegador.
 *
 * Espelha `tools/generator.py`: mesmas taxas de duplicidade e de variante, mesmas
 * variacoes realistas. **Todos os dados sao ficticios** — nenhum dado pessoal real
 * e usado, como exige SECURITY.md.
 *
 * As variantes importam: alterar so o telefone tornaria a demonstracao trivial, porque
 * documento, e-mail e nome continuariam identicos e qualquer resolvedor acertaria.
 */

import { ingerir } from "./queries";

const PRIMEIROS = [
  "Maria", "Jose", "Ana", "Carlos", "Beatriz", "Lucas", "Fernanda", "Rafael",
  "Juliana", "Pedro", "Camila", "Bruno", "Larissa", "Thiago", "Patricia", "Eduardo",
];
const SOBRENOMES = [
  "Souza", "Silva", "Oliveira", "Pereira", "Costa", "Almeida", "Lima", "Ribeiro",
  "Carvalho", "Gomes", "Martins", "Rocha", "Barbosa", "Teixeira",
];
const MEIOS = ["Aparecida", "dos Santos", "de Almeida", "Gabriel", "Helena", "Augusto"];

function inteiro(max: number): number {
  return Math.floor(Math.random() * max);
}

function escolher<T>(lista: readonly T[]): T {
  const item = lista[inteiro(lista.length)];
  if (item === undefined) throw new Error("lista vazia");
  return item;
}

function digitos(n: number): string {
  return Array.from({ length: n }, () => inteiro(10)).join("");
}

function semAcento(texto: string): string {
  return texto.normalize("NFKD").replace(/[̀-ͯ]/g, "");
}

export interface RegistroSintetico {
  payload: Record<string, unknown>;
  /** Entidade verdadeira que originou o registro. E o gabarito. */
  entidade: number;
}

function novaPessoa(fonte: string): Record<string, unknown> {
  const primeiro = escolher(PRIMEIROS);
  const sobrenome = escolher(SOBRENOMES);
  const meio = Math.random() < 0.4 ? ` ${escolher(MEIOS)}` : "";
  const local = semAcento(`${primeiro}.${sobrenome}`).toLowerCase();
  return {
    source: fonte,
    full_name: `${primeiro}${meio} ${sobrenome}`,
    email: `${local}.${inteiro(99999)}@example.com`,
    document: digitos(11),
    phone: `11${digitos(9)}`,
  };
}

/** Outra observacao da MESMA entidade, com uma diferenca realista. */
function variar(base: Record<string, unknown>): Record<string, unknown> {
  const variante = { ...base };
  const nome = String(variante.full_name ?? "");

  switch (inteiro(5)) {
    case 0:
      variante.phone = `11${digitos(9)}`;
      break;
    case 1: {
      // Nome do meio omitido — a variacao mais comum entre fontes.
      const partes = nome.split(" ");
      if (partes.length > 2) variante.full_name = `${partes[0]} ${partes[partes.length - 1]}`;
      break;
    }
    case 2: {
      const local = String(variante.email ?? "").split("@")[0] ?? "";
      variante.email = `${local}@outro-provedor.com`;
      break;
    }
    case 3:
      delete variante.phone;
      break;
    default:
      // O caso mais dificil: sem o identificador forte, o par so e encontrado se
      // nome, e-mail ou telefone bastarem.
      delete variante.document;
      break;
  }
  return variante;
}

export function montarLote(
  quantidade: number,
  fonte: string,
  taxaDuplicata: number,
  taxaVariante: number,
): RegistroSintetico[] {
  const lote: RegistroSintetico[] = [];
  const originais: RegistroSintetico[] = [];

  for (let i = 0; i < quantidade; i += 1) {
    const sorteio = Math.random();
    if (originais.length > 0 && sorteio < taxaDuplicata) {
      const origem = escolher(originais);
      lote.push({ payload: { ...origem.payload }, entidade: origem.entidade });
    } else if (originais.length > 0 && sorteio < taxaDuplicata + taxaVariante) {
      const origem = escolher(originais);
      lote.push({ payload: variar(origem.payload), entidade: origem.entidade });
    } else {
      const registro: RegistroSintetico = { payload: novaPessoa(fonte), entidade: originais.length };
      originais.push(registro);
      lote.push(registro);
    }
  }
  return lote;
}

export interface ProgressoGeracao {
  enviados: number;
  aceitos: number;
  duplicados: number;
  falhas: number;
  total: number;
}

/**
 * Envia o lote, em blocos pequenos e concorrentes.
 *
 * A concorrencia e limitada de proposito: disparar mil requisicoes de uma vez
 * atrapalharia a propria medicao que o painel existe para mostrar.
 */
export async function enviarLote(
  lote: RegistroSintetico[],
  aoProgredir: (progresso: ProgressoGeracao) => void,
  concorrencia = 4,
): Promise<ProgressoGeracao> {
  const progresso: ProgressoGeracao = {
    enviados: 0,
    aceitos: 0,
    duplicados: 0,
    falhas: 0,
    total: lote.length,
  };

  let proximo = 0;
  async function trabalhar(): Promise<void> {
    for (;;) {
      const indice = proximo;
      proximo += 1;
      const item = lote[indice];
      if (!item) return;

      try {
        const resposta = await ingerir("person", item.payload);
        if (resposta.status === "duplicate") progresso.duplicados += 1;
        else progresso.aceitos += 1;
      } catch {
        progresso.falhas += 1;
      }
      progresso.enviados += 1;
      aoProgredir({ ...progresso });
    }
  }

  await Promise.all(Array.from({ length: concorrencia }, trabalhar));
  return progresso;
}
