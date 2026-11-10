import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { AuthProvider } from "./auth/provider";
import "./styles/theme.css";

const cliente = new QueryClient({
  defaultOptions: {
    queries: {
      // Uma falha transitoria nao pode transformar a tela em erro; mas tambem nao
      // adianta insistir muito num painel que atualiza a cada poucos segundos.
      retry: 1,
      // Dado antigo nunca e exibido como atual: a tela mostra o estado de falha.
      staleTime: 0,
    },
  },
});

const raiz = document.getElementById("root");
if (!raiz) throw new Error("elemento #root nao encontrado");

createRoot(raiz).render(
  <StrictMode>
    <QueryClientProvider client={cliente}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
);
