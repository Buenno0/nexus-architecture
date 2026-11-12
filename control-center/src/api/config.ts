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
  /**
   * Modo demonstracao publica.
   *
   * Muda duas coisas: a geracao passa a acontecer no servidor, por `/v1/demo/seed`,
   * e o painel deixa de oferecer qualquer caminho de ingestao livre. Numa URL publica
   * `POST /v1/records/person` aceita o conteudo que qualquer visitante queira gravar,
   * e esse conteudo aparece nesta tela.
   *
   * O valor aqui so controla a interface. **O teto de verdade e do servidor**: a
   * credencial de convidado viaja neste mesmo bundle, entao qualquer pessoa chama a
   * API sem passar por aqui.
   */
  demoMode: texto("VITE_DEMO_MODE", "false") === "true",
  /**
   * Credenciais do convidado, usadas para entrar sozinho em modo demonstracao.
   *
   * **Isto esta no bundle publico, e e intencional.** Uma SPA nao guarda segredo:
   * qualquer chave embutida no JavaScript esta publica, com ou sem esta variavel. O
   * que protege a plataforma nao e esconder isto — sao os tetos do servidor, o
   * throttle do API Gateway, a ausencia das rotas de ingestao livre, e o fato de este
   * usuario nao ter credencial nenhuma da AWS. Ver SECURITY.md.
   *
   * Vazio desliga o login automatico: a tela de login aparece normalmente.
   */
  demoGuest: {
    usuario: texto("VITE_DEMO_GUEST_USERNAME", ""),
    senha: texto("VITE_DEMO_GUEST_PASSWORD", ""),
  },
} as const;
