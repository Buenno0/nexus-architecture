/** Grafico de linha das series de sessao. */

import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { Ponto } from "../metrics/history";

const CORES = ["var(--serie-1)", "var(--serie-2)", "var(--serie-3)", "var(--serie-4)", "var(--serie-5)"];

interface Props {
  pontos: readonly Ponto[];
  series: { chave: string; rotulo: string }[];
  altura?: number | undefined;
  /** Mensagem quando ainda nao ha pontos suficientes para uma linha. */
  vazio?: string | undefined;
  /**
   * Espaca os pontos pelo instante real, nao em passos iguais.
   *
   * Obrigatorio para a serie persistida: ela tem buracos, e um eixo categorico
   * desenharia um intervalo de dez minutos com a mesma largura de um de quinze
   * segundos — o grafico mentiria sobre quando cada leitura aconteceu.
   */
  eixoTemporal?: boolean | undefined;
}

export function Chart({ pontos, series, altura = 200, vazio, eixoTemporal = false }: Props) {
  if (pontos.length < 2) {
    return (
      <div className="grafico-vazio">
        {vazio ?? "Aguardando leituras. A serie comeca a desenhar apos a segunda atualizacao."}
      </div>
    );
  }

  const dados = pontos.map((p) => ({
    ...p,
    hora: new Date(p.instante).toLocaleTimeString("pt-BR", {
      minute: "2-digit",
      second: "2-digit",
    }),
  }));

  return (
    <div style={{ width: "100%", height: altura }}>
      <ResponsiveContainer>
        <LineChart data={dados} margin={{ top: 4, right: 8, bottom: 0, left: -18 }}>
          <CartesianGrid stroke="var(--borda)" strokeDasharray="2 4" />
          {eixoTemporal ? (
            <XAxis
              dataKey="instante"
              type="number"
              scale="time"
              domain={["dataMin", "dataMax"]}
              tickFormatter={(v: number) =>
                new Date(v).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
              }
              stroke="var(--texto-fraco)"
              tick={{ fontSize: 10, fontFamily: "var(--mono)" }}
              minTickGap={40}
            />
          ) : (
            <XAxis
              dataKey="hora"
              stroke="var(--texto-fraco)"
              tick={{ fontSize: 10, fontFamily: "var(--mono)" }}
              minTickGap={40}
            />
          )}
          <YAxis
            stroke="var(--texto-fraco)"
            tick={{ fontSize: 10, fontFamily: "var(--mono)" }}
            allowDecimals={false}
            width={48}
          />
          <Tooltip
            contentStyle={{
              background: "var(--superficie-alta)",
              border: "1px solid var(--borda-forte)",
              borderRadius: 6,
              fontSize: 12,
            }}
            labelStyle={{ color: "var(--texto-suave)" }}
            {...(eixoTemporal
              ? {
                  labelFormatter: (v: number) =>
                    new Date(v).toLocaleTimeString("pt-BR"),
                }
              : {})}
          />
          {series.map((serie, i) => (
            <Line
              key={serie.chave}
              type="monotone"
              dataKey={serie.chave}
              name={serie.rotulo}
              stroke={CORES[i % CORES.length]}
              strokeWidth={1.8}
              dot={false}
              // Buraco na serie parte a linha. Interpolar sobre um periodo nao medido
              // produziria um grafico mais bonito e falso.
              connectNulls={false}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
