import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AlertBanner } from "./AlertBanner";
import type { Alert } from "../api/types";

const DLQ: Alert = {
  id: "dlq_not_empty",
  severity: "error",
  title: "Mensagens na DLQ",
  detail: "2 mensagens esgotaram as tentativas.",
  origin: "persistido",
  value: 2,
  threshold: 0,
  context: {},
};

const TAXA: Alert = {
  id: "http_error_rate",
  severity: "warning",
  title: "Taxa de erro HTTP acima do limite",
  detail: "5 de 35 respostas foram 5xx.",
  origin: "processo",
  value: 0.14,
  threshold: 0.05,
  context: {},
};

describe("AlertBanner", () => {
  it("nao ocupa espaco quando nao ha alerta", () => {
    const { container } = render(<AlertBanner alertas={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("mostra titulo e detalhe de cada condicao", () => {
    render(<AlertBanner alertas={[DLQ, TAXA]} />);

    expect(screen.getByText("Mensagens na DLQ")).toBeInTheDocument();
    expect(screen.getByText("Taxa de erro HTTP acima do limite")).toBeInTheDocument();
  });

  it("declara a origem do numero que acendeu cada alerta", () => {
    /* Regra do ADR-009: um alerta que some sozinho ao reiniciar a API precisa dizer
       que vive no processo, senao sugere uma garantia que nao tem. */
    render(<AlertBanner alertas={[DLQ, TAXA]} />);

    expect(screen.getByText("persistido")).toBeInTheDocument();
    expect(screen.getByText("processo")).toBeInTheDocument();
  });

  it("distingue erro de atencao por texto, nao so por cor", () => {
    render(<AlertBanner alertas={[DLQ, TAXA]} />);

    expect(screen.getByText("erro")).toBeInTheDocument();
    expect(screen.getByText("atencao")).toBeInTheDocument();
  });

  it("falha ao avaliar nao e silencio", () => {
    /* Silencio seria indistinguivel de plataforma saudavel — o pior resultado
       possivel para um painel de operacao. */
    render(<AlertBanner alertas={undefined} erro />);

    expect(screen.getByText("alertas indisponiveis")).toBeInTheDocument();
    expect(screen.getByText(/nao significa que esta tudo bem/i)).toBeInTheDocument();
  });
});
