// inv.AllocationDonut — dona con Recharts.
//
// El hueco central con el monto y el hover que explica el bloque son lo que
// hace que se vea como un producto y no como un demo; eso se conserva con un
// overlay absoluto sobre el <PieChart> (Recharts no expone un slot de centro).

import { useState } from "react";
import { Cell, Pie, PieChart } from "recharts";
import { leerAccion } from "../a2ui";
import type { A2UIAction } from "../catalog.types";
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

function normalizar(entrada: unknown): Slice[] {
  if (!Array.isArray(entrada)) return [];
  return entrada.filter((s): s is Slice => typeof s === "object" && s !== null);
}

export function AllocationDonut({
  nodoId,
  slices,
  total,
  editable = false,
  action,
  subtitulo,
}: AllocationDonutProps) {
  const datos = normalizar(slices);
  const [activo, setActivo] = useState<number | null>(null);
  const emitir = useStore((s) => s.emitirAccion);
  const accion = leerAccion(action);

  if (!datos.length) {
    return <div className="rndr-hueco">La asignación llegó vacía.</div>;
  }

  const suma = datos.reduce((acc, s) => acc + (Number(s.peso) || 0), 0) || 1;
  const arcos = datos.map((s, i) => ({
    slice: s,
    peso: (Number(s.peso) || 0) / suma,
    color: COLOR_BLOQUE[s.bloque ?? ""] ?? COLORES_FALLBACK[i % COLORES_FALLBACK.length]!,
    i,
  }));

  const montoTotal = Number(total);
  const seleccionado = activo !== null ? arcos[activo] : null;

  function clicSlice(a: (typeof arcos)[number]) {
    if (accion && a.slice.instrument_id) {
      void emitir(accion.name, { ...accion.context, instrument_id: a.slice.instrument_id }, nodoId);
    }
  }

  return (
    <section className="ad">
      {subtitulo ? <p className="ad-subtitulo">{String(subtitulo)}</p> : null}
      <div className="ad-cuerpo">
        <div className="ad-svg" role="img" aria-label="Asignación propuesta">
          <PieChart width={220} height={220}>
            <Pie
              data={arcos}
              dataKey="peso"
              nameKey="i"
              cx="50%"
              cy="50%"
              innerRadius={58}
              outerRadius={92}
              startAngle={90}
              endAngle={-270}
              stroke="none"
              isAnimationActive={false}
            >
              {arcos.map((a) => (
                <Cell
                  key={a.slice.instrument_id ?? a.i}
                  fill={a.color}
                  opacity={activo === null || activo === a.i ? 1 : 0.35}
                  style={{ cursor: accion ? "pointer" : "default", transition: "opacity .15s" }}
                  onMouseEnter={() => setActivo(a.i)}
                  onMouseLeave={() => setActivo(null)}
                  onClick={() => clicSlice(a)}
                />
              ))}
            </Pie>
          </PieChart>
          <div className="ad-centro">
            <strong className="ad-centro-valor">
              {Number.isFinite(montoTotal) ? moneda(montoTotal) : ""}
            </strong>
            <span className="ad-centro-label">
              {seleccionado ? porcentaje(seleccionado.peso) : "a invertir"}
            </span>
          </div>
        </div>

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
