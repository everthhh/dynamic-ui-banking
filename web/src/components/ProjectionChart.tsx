// inv.ProjectionChart — p10/p50/p90 en SVG.
//
// Tres decisiones de diseño que importan:
//   · el área entre p10 y p90 es el mensaje principal (la incertidumbre), no la
//     línea del medio; una sola línea le vende certeza al cliente;
//   · la línea de "total aportado" deja ver de un golpe dónde empieza la
//     ganancia real;
//   · el disclaimer es una prop obligatoria del catálogo, no prosa del modelo.

import { useMemo, useState } from "react";
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

const W = 560;
const H = 260;
const M = { top: 16, right: 16, bottom: 28, left: 52 };

function serie(entrada: unknown): Punto[] {
  return Array.isArray(entrada)
    ? entrada.filter((p): p is Punto => typeof p === "object" && p !== null)
    : [];
}

export function ProjectionChart({
  scenarios,
  horizonYears,
  aportado,
  disclaimer,
  resaltar = "p50",
}: ProjectionChartProps) {
  const [hover, setHover] = useState<number | null>(null);

  const esc = (typeof scenarios === "object" && scenarios !== null
    ? (scenarios as Record<string, unknown>)
    : {}) as Record<string, unknown>;
  const p10 = serie(esc.p10);
  const p50 = serie(esc.p50);
  const p90 = serie(esc.p90);

  const geometria = useMemo(() => {
    if (!p50.length) return null;
    const n = p50.length;
    const valores = [...p10, ...p50, ...p90].map((p) => Number(p.valor) || 0);
    const refAportado = Number(aportado);
    if (Number.isFinite(refAportado)) valores.push(refAportado);
    const maxY = Math.max(...valores) * 1.06;
    const minY = Math.min(0, ...valores);

    const x = (i: number) => M.left + (i / Math.max(1, n - 1)) * (W - M.left - M.right);
    const y = (v: number) =>
      H - M.bottom - ((v - minY) / Math.max(1e-9, maxY - minY)) * (H - M.top - M.bottom);

    const linea = (s: Punto[]) =>
      s.map((p, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(Number(p.valor) || 0).toFixed(1)}`).join(" ");

    const area =
      p10.length === n && p90.length === n
        ? [
            p90.map((p, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(Number(p.valor) || 0).toFixed(1)}`).join(" "),
            [...p10]
              .reverse()
              .map((p, i) => `L ${x(n - 1 - i).toFixed(1)} ${y(Number(p.valor) || 0).toFixed(1)}`)
              .join(" "),
            "Z",
          ].join(" ")
        : null;

    const ticksY = [0, 0.25, 0.5, 0.75, 1].map((f) => {
      const v = minY + f * (maxY - minY);
      return { v, y: y(v) };
    });

    return { n, x, y, linea, area, ticksY, maxY, minY };
  }, [p10, p50, p90, aportado]);

  if (!geometria) {
    return <div className="rndr-hueco">Todavía no hay escenarios que graficar.</div>;
  }

  const { n, x, y, linea, area, ticksY } = geometria;
  const refAportado = Number(aportado);
  const idx = hover === null ? n - 1 : hover;
  const vP10 = Number(p10[idx]?.valor);
  const vP50 = Number(p50[idx]?.valor);
  const vP90 = Number(p90[idx]?.valor);
  const aniosEnPunto = Number(p50[idx]?.anios ?? idx / 12);
  const horizonte = Number(horizonYears);

  return (
    <section className="pc">
      <div className="pc-encabezado">
        <div>
          <span className="pc-label">En {aniosEnPunto.toFixed(1)} años, escenario medio</span>
          <strong className="pc-valor">{moneda(vP50)}</strong>
        </div>
        <div className="pc-rango">
          <span>
            malo <strong>{moneda(vP10)}</strong>
          </span>
          <span>
            bueno <strong>{moneda(vP90)}</strong>
          </span>
        </div>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="pc-svg"
        role="img"
        aria-label={`Proyección a ${Number.isFinite(horizonte) ? horizonte : "?"} años`}
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const caja = e.currentTarget.getBoundingClientRect();
          const rel = ((e.clientX - caja.left) / caja.width) * W;
          const frac = (rel - M.left) / (W - M.left - M.right);
          setHover(Math.max(0, Math.min(n - 1, Math.round(frac * (n - 1)))));
        }}
      >
        {ticksY.map((t) => (
          <g key={t.v}>
            <line x1={M.left} x2={W - M.right} y1={t.y} y2={t.y} className="pc-grid" />
            <text x={M.left - 8} y={t.y + 4} className="pc-tick" textAnchor="end">
              {compacto(t.v)}
            </text>
          </g>
        ))}

        {area ? <path d={area} className="pc-area" /> : null}
        <path d={linea(p10)} className="pc-linea pc-p10" />
        <path d={linea(p90)} className="pc-linea pc-p90" />
        <path d={linea(p50)} className={`pc-linea pc-p50${resaltar === "p50" ? " resaltada" : ""}`} />

        {Number.isFinite(refAportado) ? (
          <g>
            <line
              x1={M.left}
              x2={W - M.right}
              y1={y(refAportado)}
              y2={y(refAportado)}
              className="pc-aportado"
            />
            <text x={W - M.right} y={y(refAportado) - 6} className="pc-tick" textAnchor="end">
              aportado {compacto(refAportado)}
            </text>
          </g>
        ) : null}

        <line x1={x(idx)} x2={x(idx)} y1={M.top} y2={H - M.bottom} className="pc-cursor" />
        <circle cx={x(idx)} cy={y(vP50)} r={4} className="pc-punto" />

        {[0, 0.25, 0.5, 0.75, 1].map((f) => {
          const i = Math.round(f * (n - 1));
          return (
            <text key={f} x={x(i)} y={H - 8} className="pc-tick" textAnchor="middle">
              {(Number(p50[i]?.anios ?? i / 12)).toFixed(0)}a
            </text>
          );
        })}
      </svg>

      <p className="pc-disclaimer">
        {disclaimer ?? "Escenarios probabilísticos sobre datos sintéticos."}
      </p>
    </section>
  );
}
