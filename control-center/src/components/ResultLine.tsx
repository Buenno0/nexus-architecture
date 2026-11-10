/** Mostra o resultado da ultima operacao, para que o clique tenha resposta visivel. */

import "./ResultLine.css";

export function ResultLine({ resultado }: { resultado: Record<string, unknown> | null }) {
  if (!resultado) return null;
  const partes = Object.entries(resultado)
    .filter(([, v]) => typeof v === "number" || typeof v === "string")
    .map(([k, v]) => `${k}=${String(v)}`);
  return <p className="resultado numero">{partes.join("  ")}</p>;
}
