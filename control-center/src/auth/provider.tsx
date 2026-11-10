/**
 * Autenticacao.
 *
 * Duas implementacoes atras da mesma interface:
 *
 * - `none` — ambiente local, onde a API nao exige token.
 * - `cognito` — AWS, onde todas as rotas menos `/health` exigem JWT.
 *
 * Apontar o dashboard para a nuvem e trocar variaveis de ambiente, nao codigo.
 *
 * **O token fica em memoria, nunca em `localStorage`.** Em `localStorage` ele
 * sobrevive ao fechamento da aba e fica legivel por qualquer script da pagina; o custo
 * de manter em memoria e um login a cada recarga.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { config } from "../api/config";
import { setTokenProvider } from "../api/client";

interface AuthState {
  modo: "none" | "cognito";
  autenticado: boolean;
  usuario: string | null;
  erro: string | null;
  entrando: boolean;
  entrar: (usuario: string, senha: string) => Promise<void>;
  sair: () => void;
}

const AuthContext = createContext<AuthState | null>(null);

interface Sessao {
  idToken: string;
  expiraEm: number;
  usuario: string;
}

export function AuthProvider({
  children,
  modo: modoForcado,
}: {
  children: ReactNode;
  /** Sobrescreve o modo lido do ambiente. Usado em teste. */
  modo?: "none" | "cognito" | undefined;
}) {
  const [sessao, setSessao] = useState<Sessao | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [entrando, setEntrando] = useState(false);

  const modo = modoForcado ?? config.authMode;

  useEffect(() => {
    if (modo === "none") {
      setTokenProvider(async () => null);
      return;
    }
    setTokenProvider(async () => {
      if (!sessao) return null;
      // Token vencido e pior que token ausente: produz 401 confuso em vez de um
      // pedido de login claro.
      if (Date.now() >= sessao.expiraEm) return null;
      return sessao.idToken;
    });
  }, [modo, sessao]);

  const entrar = useCallback(async (usuario: string, senha: string) => {
    setEntrando(true);
    setErro(null);
    try {
      // O SDK do Cognito pesa centenas de kilobytes e so e usado quando o dashboard
      // aponta para a AWS. Carregar sob demanda evita que o modo local pague por ele:
      // o bundle inicial cai de ~870 kB para ~600 kB.
      const { CognitoIdentityProviderClient, InitiateAuthCommand } = await import(
        "@aws-sdk/client-cognito-identity-provider"
      );
      const cliente = new CognitoIdentityProviderClient({ region: config.cognito.region });
      const resposta = await cliente.send(
        new InitiateAuthCommand({
          AuthFlow: "USER_PASSWORD_AUTH",
          ClientId: config.cognito.clientId,
          AuthParameters: { USERNAME: usuario, PASSWORD: senha },
        }),
      );
      const resultado = resposta.AuthenticationResult;
      if (!resultado?.IdToken) throw new Error("Resposta sem token");
      setSessao({
        idToken: resultado.IdToken,
        expiraEm: Date.now() + (resultado.ExpiresIn ?? 3600) * 1000,
        usuario,
      });
    } catch (causa) {
      setErro(causa instanceof Error ? causa.message : "Falha ao autenticar");
      throw causa;
    } finally {
      setEntrando(false);
    }
  }, []);

  const sair = useCallback(() => {
    setSessao(null);
    setErro(null);
  }, []);

  const valor = useMemo<AuthState>(
    () => ({
      modo,
      autenticado: modo === "none" || sessao !== null,
      usuario: sessao?.usuario ?? null,
      erro,
      entrando,
      entrar,
      sair,
    }),
    [modo, sessao, erro, entrando, entrar, sair],
  );

  return <AuthContext.Provider value={valor}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const contexto = useContext(AuthContext);
  if (!contexto) throw new Error("useAuth exige AuthProvider acima na arvore");
  return contexto;
}
