/**
 * Botao de operacao.
 *
 * Operacoes com efeito amplo — devolver da DLQ, reprocessar o acervo, gerar milhares
 * de registros — pedem confirmacao explicita. O projeto exige teto e confirmacao em
 * toda operacao cara; um clique acidental nao pode disparar trabalho em volume.
 */

import { useState } from "react";
import "./OpButton.css";

interface Props {
  rotulo: string;
  onExecutar: () => Promise<unknown>;
  /** Texto da confirmacao. Ausente, executa direto. */
  confirmacao?: string | undefined;
  variante?: "normal" | "perigo" | undefined;
  desabilitado?: boolean | undefined;
  dica?: string | undefined;
}

export function OpButton({
  rotulo,
  onExecutar,
  confirmacao,
  variante = "normal",
  desabilitado = false,
  dica,
}: Props) {
  const [executando, setExecutando] = useState(false);
  const [confirmando, setConfirmando] = useState(false);

  async function executar() {
    setExecutando(true);
    try {
      await onExecutar();
    } finally {
      setExecutando(false);
      setConfirmando(false);
    }
  }

  if (confirmando) {
    return (
      <span className="op-confirma">
        <span className="op-confirma__texto">{confirmacao}</span>
        <button type="button" className="op op--perigo" onClick={() => void executar()}>
          Confirmar
        </button>
        <button type="button" className="op" onClick={() => setConfirmando(false)}>
          Cancelar
        </button>
      </span>
    );
  }

  return (
    <button
      type="button"
      className={`op op--${variante}`}
      title={dica}
      disabled={desabilitado || executando}
      onClick={() => (confirmacao ? setConfirmando(true) : void executar())}
    >
      {executando ? "executando…" : rotulo}
    </button>
  );
}
