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

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";

import { config } from "../api/config";
import { setTokenProvider } from "../api/client";

interface AuthState {
  modo: "none" | "cognito";
  autenticado: boolean;
  usuario: string | null;
  erro: string | null;
  entrando: boolean;
  /**
   * O login automatico de convidado esta em curso.
   *
   * Existe para o chamador nao mostrar o formulario de login durante essa janela. Sem
   * isso, quem abre a demonstracao publica ve um pedido de usuario e senha piscar por
   * dois segundos antes de entrar sozinho — e a primeira impressao do painel vira uma
   * porta trancada. Falhando, vira `false` e o formulario aparece com o erro.
   */
  autenticandoConvidado: boolean;
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

  // Login automatico do convidado, em modo demonstracao.
  //
  // O visitante nao deveria ver tela de login para olhar um painel publico. A
  // tentativa acontece UMA vez: sem a trava, uma credencial errada entraria em laco
  // de autenticacao contra o Cognito, que cobra por usuario ativo e limita taxa.
  // Falhando, o formulario aparece com o erro — degradar para o caminho manual e
  // melhor que uma tela em branco tentando para sempre.
  const tentouConvidado = useRef(false);
  useEffect(() => {
    if (modo !== "cognito" || sessao || tentouConvidado.current) return;
    const { usuario, senha } = config.demoGuest;
    if (!config.demoMode || !usuario || !senha) return;
    tentouConvidado.current = true;
    void entrar(usuario, senha).catch(() => {
      // O erro ja esta no estado; aqui so evitamos uma rejeicao nao tratada.
    });
  }, [modo, sessao, entrar]);

  const sair = useCallback(() => {
    setSessao(null);
    setErro(null);
  }, []);

  // Verdadeiro desde o primeiro render ate a sessao chegar ou a tentativa falhar.
  // Nao depende de `entrando`, que so vira true depois que o efeito acima roda: a
  // janela entre o primeiro render e o efeito e justamente onde o formulario piscava.
  const autenticandoConvidado =
    modo === "cognito" &&
    config.demoMode &&
    config.demoGuest.usuario !== "" &&
    config.demoGuest.senha !== "" &&
    sessao === null &&
    erro === null;

  const valor = useMemo<AuthState>(
    () => ({
      modo,
      autenticado: modo === "none" || sessao !== null,
      usuario: sessao?.usuario ?? null,
      erro,
      entrando,
      autenticandoConvidado,
      entrar,
      sair,
    }),
    [modo, sessao, erro, entrando, autenticandoConvidado, entrar, sair],
  );

  return <AuthContext.Provider value={valor}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const contexto = useContext(AuthContext);
  if (!contexto) throw new Error("useAuth exige AuthProvider acima na arvore");
  return contexto;
}
