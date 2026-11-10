import "@testing-library/jest-dom/vitest";

/**
 * jsdom nao implementa ResizeObserver, e o `ResponsiveContainer` do Recharts depende
 * dele para medir o contêiner.
 *
 * O stub nao e uma concessao de teste: ele deixa o grafico montar e falhar visivelmente
 * se quebrar. Ate a Fase 6 os graficos nunca chegavam a renderizar nos testes, porque
 * as series de sessao comecavam vazias — os testes passavam sem nunca exercitar o
 * componente. Com a serie persistida vindo preenchida, eles passam a exercitar.
 */
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;
