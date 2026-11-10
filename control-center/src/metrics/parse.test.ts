import { describe, expect, it } from "vitest";

import { agruparPorRotulo, parseChave, somarPorNome } from "./parse";

describe("parseChave", () => {
  it("le chave sem rotulos", () => {
    expect(parseChave("ingestion_accepted_total")).toEqual({
      nome: "ingestion_accepted_total",
      rotulos: {},
      chave: "ingestion_accepted_total",
    });
  });

  it("le rotulos simples", () => {
    const serie = parseChave("http_requests_total{method=GET,status=200}");
    expect(serie.nome).toBe("http_requests_total");
    expect(serie.rotulos).toEqual({ method: "GET", status: "200" });
  });

  it("preserva caminho com barras", () => {
    const serie = parseChave("http_requests_total{path=/v1/records/person}");
    expect(serie.rotulos.path).toBe("/v1/records/person");
  });

  it("preserva caminho com chaves dentro do valor", () => {
    // O caso que quebra um regex ingenuo: o valor contem `}` antes do fechamento.
    const serie = parseChave(
      "http_requests_total{method=GET,path=/v1/records/{record_id},status=200}",
    );
    expect(serie.rotulos.path).toBe("/v1/records/{record_id}");
    expect(serie.rotulos.method).toBe("GET");
    expect(serie.rotulos.status).toBe("200");
  });

  it("preserva igual dentro do valor", () => {
    const serie = parseChave("x{filtro=a=b}");
    expect(serie.rotulos.filtro).toBe("a=b");
  });

  it("junta valor que contem virgula", () => {
    const serie = parseChave("x{lista=a,b,c}");
    expect(serie.rotulos.lista).toBe("a,b,c");
  });

  it("tolera chave malformada sem quebrar", () => {
    expect(parseChave("x{sem_fechamento").nome).toBe("x{sem_fechamento");
    expect(parseChave("x{}").rotulos).toEqual({});
  });
});

describe("somarPorNome", () => {
  const contadores = {
    "http_requests_total{method=GET,status=200}": 10,
    "http_requests_total{method=POST,status=202}": 5,
    "worker_processed_total": 3,
  };

  it("soma todas as series do nome", () => {
    expect(somarPorNome(contadores, "http_requests_total")).toBe(15);
  });

  it("soma contador sem rotulos", () => {
    expect(somarPorNome(contadores, "worker_processed_total")).toBe(3);
  });

  it("devolve zero para nome inexistente", () => {
    expect(somarPorNome(contadores, "nao_existe")).toBe(0);
  });
});

describe("agruparPorRotulo", () => {
  const contadores = {
    "http_requests_total{method=GET,path=/health,status=200}": 10,
    "http_requests_total{method=POST,path=/v1/records/person,status=202}": 5,
    "http_requests_total{method=POST,path=/v1/records/person,status=422}": 2,
    "outro_total{path=/x}": 99,
  };

  it("agrupa pela rota", () => {
    expect(agruparPorRotulo(contadores, "http_requests_total", "path")).toEqual({
      "/health": 10,
      "/v1/records/person": 7,
    });
  });

  it("agrupa por status", () => {
    expect(agruparPorRotulo(contadores, "http_requests_total", "status")).toEqual({
      "200": 10,
      "202": 5,
      "422": 2,
    });
  });

  it("nao mistura nomes diferentes", () => {
    const grupos = agruparPorRotulo(contadores, "http_requests_total", "path");
    expect(grupos["/x"]).toBeUndefined();
  });

  it("agrupa o que nao tem o rotulo", () => {
    const grupos = agruparPorRotulo({ "x{a=1}": 4 }, "x", "inexistente");
    expect(grupos["(sem rotulo)"]).toBe(4);
  });
});
