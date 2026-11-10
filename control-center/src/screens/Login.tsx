/** Login do Cognito. So aparece quando VITE_AUTH_MODE=cognito. */

import { useState } from "react";

import { useAuth } from "../auth/provider";

export function Login() {
  const { entrar, erro, entrando } = useAuth();
  const [usuario, setUsuario] = useState("");
  const [senha, setSenha] = useState("");

  return (
    <div style={{ display: "grid", placeItems: "center", minHeight: "100vh", padding: 20 }}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void entrar(usuario, senha).catch(() => undefined);
        }}
        style={{
          background: "var(--superficie)",
          border: "1px solid var(--borda)",
          borderRadius: "var(--raio)",
          padding: 24,
          width: "min(360px, 100%)",
        }}
      >
        <h1 style={{ fontSize: 16, margin: "0 0 4px" }}>Nexus Control Center</h1>
        <p style={{ fontSize: 12, color: "var(--texto-fraco)", margin: "0 0 18px" }}>
          A API exige autenticacao neste ambiente.
        </p>

        <label style={{ display: "block", fontSize: 12, marginBottom: 10 }}>
          Usuario
          <input
            value={usuario}
            onChange={(e) => setUsuario(e.target.value)}
            autoComplete="username"
            required
            style={campo}
          />
        </label>

        <label style={{ display: "block", fontSize: 12, marginBottom: 16 }}>
          Senha
          <input
            type="password"
            value={senha}
            onChange={(e) => setSenha(e.target.value)}
            autoComplete="current-password"
            required
            style={campo}
          />
        </label>

        {erro ? (
          <p style={{ color: "var(--erro)", fontSize: 12, margin: "0 0 12px" }}>{erro}</p>
        ) : null}

        <button type="submit" className="op" disabled={entrando} style={{ width: "100%" }}>
          {entrando ? "entrando…" : "Entrar"}
        </button>
      </form>
    </div>
  );
}

const campo: React.CSSProperties = {
  display: "block",
  width: "100%",
  marginTop: 4,
  padding: "7px 10px",
  background: "var(--fundo)",
  border: "1px solid var(--borda-forte)",
  borderRadius: "var(--raio)",
  color: "var(--texto)",
  fontFamily: "inherit",
  fontSize: 13,
};
