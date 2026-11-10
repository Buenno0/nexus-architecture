import { describe, expect, it } from "vitest";

import { MedidorDeTaxa, taxaPorSegundo } from "./rate";

describe("taxaPorSegundo", () => {
  it("calcula a taxa entre duas amostras", () => {
    const taxa = taxaPorSegundo({ valor: 100, instante: 0 }, { valor: 130, instante: 3000 });
    expect(taxa).toBe(10);
  });

  it("devolve zero quando o contador nao mudou", () => {
    expect(taxaPorSegundo({ valor: 5, instante: 0 }, { valor: 5, instante: 1000 })).toBe(0);
  });

  it("descarta quando o contador diminuiu", () => {
    // Contador cumulativo nao anda para tras: a API reiniciou. Tratar como zero
    // inventaria uma ociosidade que nao houve.
    expect(taxaPorSegundo({ valor: 500, instante: 0 }, { valor: 3, instante: 1000 })).toBeNull();
  });

  it("descarta intervalo nao positivo", () => {
    expect(taxaPorSegundo({ valor: 1, instante: 1000 }, { valor: 2, instante: 1000 })).toBeNull();
    expect(taxaPorSegundo({ valor: 1, instante: 2000 }, { valor: 2, instante: 1000 })).toBeNull();
  });

  it("lida com intervalo fracionario", () => {
    const taxa = taxaPorSegundo({ valor: 0, instante: 0 }, { valor: 1, instante: 500 });
    expect(taxa).toBe(2);
  });
});

describe("MedidorDeTaxa", () => {
  it("nao mede na primeira leitura", () => {
    expect(new MedidorDeTaxa().medir(100, 0)).toBeNull();
  });

  it("mede a partir da segunda", () => {
    const medidor = new MedidorDeTaxa();
    medidor.medir(100, 0);
    expect(medidor.medir(110, 1000)).toBe(10);
  });

  it("acompanha leituras sucessivas", () => {
    const medidor = new MedidorDeTaxa();
    medidor.medir(0, 0);
    expect(medidor.medir(10, 1000)).toBe(10);
    expect(medidor.medir(40, 2000)).toBe(30);
  });

  it("descarta a amostra apos reinicio e volta a medir depois", () => {
    const medidor = new MedidorDeTaxa();
    medidor.medir(500, 0);
    expect(medidor.medir(2, 1000)).toBeNull();
    expect(medidor.medir(12, 2000)).toBe(10);
  });

  it("reset descarta o historico", () => {
    const medidor = new MedidorDeTaxa();
    medidor.medir(100, 0);
    medidor.reset();
    expect(medidor.medir(110, 1000)).toBeNull();
  });
});
