/** Configuracao lida do ambiente em tempo de build. */

export type AuthMode = "none" | "cognito";

function texto(chave: string, padrao: string): string {
  const valor = import.meta.env[chave];
  return typeof valor === "string" && valor.length > 0 ? valor : padrao;
}

export const config = {
  apiUrl: texto("VITE_API_URL", "http://localhost:8080").replace(/\/$/, ""),
  authMode: texto("VITE_AUTH_MODE", "none") as AuthMode,
  cognito: {
    userPoolId: texto("VITE_COGNITO_USER_POOL_ID", ""),
    clientId: texto("VITE_COGNITO_CLIENT_ID", ""),
    region: texto("VITE_AWS_REGION", "us-east-1"),
  },
  pollIntervalMs: Number(texto("VITE_POLL_INTERVAL_MS", "3000")),
} as const;
