// inv.ProjectionChart — p10/p50/p90 con Recharts.
//
// Tres decisiones de diseño que importan (y que sobreviven al cambio de
// librería, ver docs/trade-offs.md):
//   · el área entre p10 y p90 es el mensaje principal (la incertidumbre), no la
//     línea del medio; una sola línea le vende certeza al cliente. En Recharts
//     esto se logra apilando dos `Area`: una invisible (`base` = p10) que
//     empuja la banda visible (`rango` = p90-p10) a su lugar;
//   · la línea de "total aportado" deja ver de un golpe dónde empieza la
//     ganancia real;
//   · el disclaimer es una prop obligatoria del catálogo, no prosa del modelo.

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";
import { compacto, moneda } from "../format";

type Punto = { mes?: number; anios?: number; valor?: number };

export type ProjectionChartProps = {
  scenarios?: unknown;
  horizonYears?: unknown;
  aportado?: unknown;
  disclaimer?: string;
  resaltar?: "p10" | "p50" | "p90";
  nodoId?: string;
};

type Fila = { anios: number; p10: number; p50: number; p90: number; base: number; rango: number };

function serie(entrada: unknown): Punto[] {
  return Array.isArray(entrada)
    ? entrada.filter((p): p is Punto => typeof p === "object" && p !== null)
    : [];
}

function armarFilas(p10: Punto[], p50: Punto[], p90: Punto[]): Fila[] {
  return p50.map((p, i) => {
    const v10 = Number(p10[i]?.valor) || 0;
    const v50 = Number(p.valor) || 0;
    const v90 = Number(p90[i]?.valor) || 0;
    return {
      anios: Number(p.anios ?? i / 12),
      p10: v10,
      p50: v50,
      p90: v90,
      base: v10,
      rango: Math.max(0, v90 - v10),
    };
  });
}

function TooltipEscenarios({ active, payload, label }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;
  const fila = payload[0]?.payload as Fila | undefined;
  if (!fila) return null;
  return (
    <div className="pc-tooltip">
      <strong>{Number(label).toFixed(1)} años</strong>
      <span className="pc-tooltip-medio">medio {moneda(fila.p50)}</span>
      <span>
        malo {moneda(fila.p10)} · bueno {moneda(fila.p90)}
      </span>
    </div>
  );
}

export function ProjectionChart({
  scenarios,
  horizonYears,
  aportado,
  disclaimer,
}: ProjectionChartProps) {
  const esc = (typeof scenarios === "object" && scenarios !== null
    ? (scenarios as Record<string, unknown>)
    : {}) as Record<string, unknown>;
  const filas = armarFilas(serie(esc.p10), serie(esc.p50), serie(esc.p90));

  if (!filas.length) {
    return <div className="rndr-hueco">Todavía no hay escenarios que graficar.</div>;
  }

  const ultima = filas[filas.length - 1]!;
  const refAportado = Number(aportado);
  const horizonte = Number(horizonYears);

  return (
    <section className="pc">
      <div className="pc-encabezado">
        <div>
          <span className="pc-label">En {ultima.anios.toFixed(1)} años, escenario medio</span>
          <strong className="pc-valor">{moneda(ultima.p50)}</strong>
        </div>
        <div className="pc-rango">
          <span>
            malo <strong>{moneda(ultima.p10)}</strong>
          </span>
          <span>
            bueno <strong>{moneda(ultima.p90)}</strong>
          </span>
        </div>
      </div>

      <div
        className="pc-svg"
        role="img"
        aria-label={`Proyección a ${Number.isFinite(horizonte) ? horizonte : "?"} años`}
      >
        <ResponsiveContainer width="100%" height={240}>
          <ComposedChart data={filas} margin={{ top: 8, right: 8, bottom: 4, left: 0 }}>
            <CartesianGrid stroke="var(--linea)" vertical={false} />
            <XAxis
              dataKey="anios"
              tickFormatter={(v: number) => `${v.toFixed(0)}a`}
              stroke="var(--apagado)"
              tick={{ fontSize: 10, fill: "var(--apagado)" }}
              tickLine={false}
              axisLine={false}
            />
            <YAxis
              tickFormatter={(v: number) => compacto(v)}
              stroke="var(--apagado)"
              tick={{ fontSize: 10, fill: "var(--apagado)" }}
              tickLine={false}
              axisLine={false}
              width={52}
            />
            <Tooltip
              content={<TooltipEscenarios />}
              cursor={{ stroke: "var(--tinta-2)", strokeOpacity: 0.35 }}
            />
            <Area
              dataKey="base"
              stackId="banda"
              stroke="none"
              fill="transparent"
              isAnimationActive={false}
            />
            <Area
              dataKey="rango"
              stackId="banda"
              stroke="none"
              fill="var(--rojo)"
              fillOpacity={0.1}
              isAnimationActive={false}
            />
            <Line
              dataKey="p10"
              stroke="var(--rojo)"
              strokeOpacity={0.4}
              strokeDasharray="3 3"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              dataKey="p90"
              stroke="var(--rojo)"
              strokeOpacity={0.4}
              strokeDasharray="3 3"
              strokeWidth={1.5}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              dataKey="p50"
              stroke="var(--rojo)"
              strokeWidth={2.5}
              dot={false}
              activeDot={{ r: 4, fill: "var(--rojo)", stroke: "#fff", strokeWidth: 2 }}
              isAnimationActive={false}
            />
            {Number.isFinite(refAportado) ? (
              <ReferenceLine
                y={refAportado}
                stroke="var(--tinta-2)"
                strokeDasharray="5 4"
                label={{
                  value: `aportado ${compacto(refAportado)}`,
                  position: "insideTopRight",
                  fontSize: 10,
                  fill: "var(--apagado)",
                }}
              />
            ) : null}
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      <p className="pc-disclaimer">
        {disclaimer ?? "Escenarios probabilísticos sobre datos sintéticos."}
      </p>
    </section>
  );
}
