// inv.AllocationDonut — SVG a mano, sin librería de gráficas.
//
// Dos razones: el bundle no carga 300 kB para pintar siete arcos, y el control
// del detalle (el hueco central con el monto, el hover que explica el bloque)
// es justo lo que hace que se vea como un producto y no como un demo.

import { useState } from "react";
import type { A2UIAction, ActionName } from "../catalog.types";
import { moneda, porcentaje } from "../format";
import { useStore } from "../store";

export type Slice = {
  instrument_id?: string;
  instrumento?: string;
  etiqueta?: string;
  bloque?: string;
  peso?: number;
  monto?: number;
  porque?: string;
  riesgo_1a5?: number;
};

export type AllocationDonutProps = {
  slices?: unknown;
  total?: unknown;
  editable?: boolean;
  action?: A2UIAction;
  subtitulo?: unknown;
  nodoId?: string;
};

// Paleta por bloque: el color dice "qué tan defensivo es", de gris a rojo.
const COLOR_BLOQUE: Record<string, string> = {
  liquidez: "#9AA4B2",
  deuda_corta: "#6B7B94",
  deuda_larga: "#3F5A80",
  deuda_corp: "#2F6F6B",
  rv_local: "#D1762B",
  rv_global: "#C2392E",
  rv_agresiva: "#8E1F2F",
};
const COLORES_FALLBACK = ["#3F5A80", "#2F6F6B", "#D1762B", "#C2392E", "#6B7B94", "#8E1F2F", "#9AA4B2"];

const R_EXT = 92;
const R_INT = 58;
const CENTRO = 110;

function arco(desde: number, hasta: number): string {
  const a0 = desde * 2 * Math.PI - Math.PI / 2;
  const a1 = hasta * 2 * Math.PI - Math.PI / 2;
  const grande = hasta - desde > 0.5 ? 1 : 0;
  const x0 = CENTRO + R_EXT * Math.cos(a0);
  const y0 = CENTRO + R_EXT * Math.sin(a0);
  const x1 = CENTRO + R_EXT * Math.cos(a1);
  const y1 = CENTRO + R_EXT * Math.sin(a1);
  const xi1 = CENTRO + R_INT * Math.cos(a1);
  const yi1 = CENTRO + R_INT * Math.sin(a1);
  const xi0 = CENTRO + R_INT * Math.cos(a0);
  const yi0 = CENTRO + R_INT * Math.sin(a0);
  return [
    `M ${x0} ${y0}`,
    `A ${R_EXT} ${R_EXT} 0 ${grande} 1 ${x1} ${y1}`,
    `L ${xi1} ${yi1}`,
    `A ${R_INT} ${R_INT} 0 ${grande} 0 ${xi0} ${yi0}`,
    "Z",
  ].join(" ");
}

function normalizar(entrada: unknown): Slice[] {
  if (!Array.isArray(entrada)) return [];
  return entrada.filter((s): s is Slice => typeof s === "object" && s !== null);
}

export function AllocationDonut({
  slices,
  total,
  editable = false,
  action,
  subtitulo,
}: AllocationDonutProps) {
  const datos = normalizar(slices);
  const [activo, setActivo] = useState<number | null>(null);
  const emitir = useStore((s) => s.emitirAccion);

  if (!datos.length) {
    return <div className="rndr-hueco">La asignación llegó vacía.</div>;
  }

  const suma = datos.reduce((acc, s) => acc + (Number(s.peso) || 0), 0) || 1;
  let acumulado = 0;
  const arcos = datos.map((s, i) => {
    const peso = (Number(s.peso) || 0) / suma;
    const desde = acumulado;
    acumulado += peso;
    return {
      slice: s,
      d: arco(desde, acumulado),
      color: COLOR_BLOQUE[s.bloque ?? ""] ?? COLORES_FALLBACK[i % COLORES_FALLBACK.length]!,
      peso,
      i,
    };
  });

  const montoTotal = Number(total);
  const seleccionado = activo !== null ? arcos[activo] : null;

  return (
    <section className="ad">
      {subtitulo ? <p className="ad-subtitulo">{String(subtitulo)}</p> : null}
      <div className="ad-cuerpo">
        <svg viewBox="0 0 220 220" className="ad-svg" role="img" aria-label="Asignación propuesta">
          {arcos.map((a) => (
            <path
              key={a.slice.instrument_id ?? a.i}
              d={a.d}
              fill={a.color}
              className={"ad-arco" + (activo === a.i ? " activo" : "")}
              opacity={activo === null || activo === a.i ? 1 : 0.35}
              onMouseEnter={() => setActivo(a.i)}
              onMouseLeave={() => setActivo(null)}
              onClick={() => {
                if (action && a.slice.instrument_id) {
                  void emitir(action.name as ActionName, {
                    ...action.context,
                    instrument_id: a.slice.instrument_id,
                  });
                }
              }}
            />
          ))}
          <text x={CENTRO} y={CENTRO - 6} className="ad-centro-valor" textAnchor="middle">
            {Number.isFinite(montoTotal) ? moneda(montoTotal) : ""}
          </text>
          <text x={CENTRO} y={CENTRO + 14} className="ad-centro-label" textAnchor="middle">
            {seleccionado ? porcentaje(seleccionado.peso) : "a invertir"}
          </text>
        </svg>

        <ul className="ad-leyenda">
          {arcos.map((a) => (
            <li
              key={a.slice.instrument_id ?? a.i}
              className={"ad-item" + (activo === a.i ? " activo" : "")}
              onMouseEnter={() => setActivo(a.i)}
              onMouseLeave={() => setActivo(null)}
            >
              <span className="ad-punto" style={{ background: a.color }} />
              <span className="ad-item-texto">
                <strong>{a.slice.etiqueta ?? a.slice.bloque ?? a.slice.instrument_id}</strong>
                <span className="ad-item-sub">{a.slice.instrumento ?? ""}</span>
              </span>
              <span className="ad-item-cifras">
                <strong>{porcentaje(a.peso)}</strong>
                {Number.isFinite(Number(a.slice.monto)) ? (
                  <span className="ad-item-sub">{moneda(a.slice.monto)}</span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
      </div>

      {seleccionado?.slice.porque ? (
        <p className="ad-porque">{seleccionado.slice.porque}</p>
      ) : (
        <p className="ad-porque ad-porque-placeholder">
          Pasa el cursor sobre un bloque para ver por qué está ahí.
        </p>
      )}

      {editable ? (
        <p className="ad-nota">
          Los pesos son ajustables; cada cambio vuelve al agente para recalcular.
        </p>
      ) : null}
    </section>
  );
}
