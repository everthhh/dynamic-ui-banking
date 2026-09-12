// Tablas de dominio: inv.InstrumentTable y inv.PositionsTable.

import type { A2UIAction, ActionName } from "../catalog.types";
import {
  ETIQUETA_CLASE,
  ETIQUETA_LIQUIDEZ,
  ETIQUETA_RIESGO,
  conSigno,
  moneda,
  numero,
  porcentaje,
} from "../format";
import { useStore } from "../store";

type Fila = Record<string, unknown>;

const COLUMNAS: Record<string, { titulo: string; render: (f: Fila) => string; alinear?: "d" }> = {
  nombre: { titulo: "Instrumento", render: (f) => String(f.nombre ?? f.instrument_id ?? "") },
  clase: { titulo: "Tipo", render: (f) => ETIQUETA_CLASE[String(f.clase)] ?? String(f.clase ?? "") },
  emisor: { titulo: "Emisor", render: (f) => String(f.emisor ?? "") },
  rend_esperado_anual: {
    titulo: "Rendimiento",
    render: (f) => porcentaje(f.rend_esperado_anual),
    alinear: "d",
  },
  rend_neto_anual: {
    titulo: "Neto de comisión",
    render: (f) => porcentaje(f.rend_neto_anual),
    alinear: "d",
  },
  volatilidad_anual: { titulo: "Volatilidad", render: (f) => porcentaje(f.volatilidad_anual), alinear: "d" },
  comision_anual: { titulo: "Comisión", render: (f) => porcentaje(f.comision_anual), alinear: "d" },
  riesgo_1a5: {
    titulo: "Riesgo",
    render: (f) => ETIQUETA_RIESGO[Number(f.riesgo_1a5)] ?? "—",
  },
  liquidez: { titulo: "Liquidez", render: (f) => ETIQUETA_LIQUIDEZ[String(f.liquidez)] ?? "—" },
  plazo_dias: {
    titulo: "Plazo",
    render: (f) => (f.plazo_dias ? `${numero(f.plazo_dias)} días` : "Sin plazo"),
    alinear: "d",
  },
  monto_minimo: { titulo: "Mínimo", render: (f) => moneda(f.monto_minimo), alinear: "d" },
};

export type InstrumentTableProps = {
  rows?: unknown;
  columns?: unknown;
  selectable?: boolean;
  action?: A2UIAction;
  nodoId?: string;
};

export function InstrumentTable({ rows, columns, selectable = true, action }: InstrumentTableProps) {
  const emitir = useStore((s) => s.emitirAccion);
  const filas = Array.isArray(rows) ? (rows as Fila[]) : [];
  const cols = (Array.isArray(columns) ? (columns as string[]) : []).filter((c) => COLUMNAS[c]);
  const usar = cols.length ? cols : ["nombre", "rend_esperado_anual", "riesgo_1a5", "liquidez"];

  if (!filas.length) {
    return <div className="rndr-hueco">No hay instrumentos que cumplan ese filtro.</div>;
  }

  return (
    <div className="tbl-wrap">
      <table className="tbl">
        <thead>
          <tr>
            {usar.map((c) => (
              <th key={c} className={COLUMNAS[c]!.alinear === "d" ? "der" : undefined}>
                {COLUMNAS[c]!.titulo}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filas.map((f, i) => (
            <tr
              key={String(f.instrument_id ?? i)}
              className={selectable && action ? "clickable" : undefined}
              onClick={() => {
                if (selectable && action && f.instrument_id) {
                  void emitir(action.name as ActionName, {
                    ...action.context,
                    instrument_id: f.instrument_id,
                  });
                }
              }}
            >
              {usar.map((c) => (
                <td key={c} className={COLUMNAS[c]!.alinear === "d" ? "der" : undefined}>
                  {COLUMNAS[c]!.render(f)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export type PositionsTableProps = {
  positions?: unknown;
  resumen?: unknown;
  action?: A2UIAction;
  nodoId?: string;
};

export function PositionsTable({ positions, resumen, action }: PositionsTableProps) {
  const emitir = useStore((s) => s.emitirAccion);
  const filas = Array.isArray(positions) ? (positions as Fila[]) : [];
  const r = (typeof resumen === "object" && resumen !== null ? resumen : {}) as Fila;

  if (!filas.length) {
    return <div className="rndr-hueco">Todavía no hay posiciones en esta cuenta.</div>;
  }

  return (
    <section className="pos">
      {Object.keys(r).length ? (
        <div className="pos-resumen">
          <div>
            <span>Invertido</span>
            <strong>{moneda(r.costo_total)}</strong>
          </div>
          <div>
            <span>Valor hoy</span>
            <strong>{moneda(r.valor_mercado)}</strong>
          </div>
          <div>
            <span>Rendimiento</span>
            <strong className={Number(r.rendimiento) >= 0 ? "pos-up" : "pos-down"}>
              {conSigno(r.rendimiento)}
            </strong>
          </div>
        </div>
      ) : null}

      <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>Instrumento</th>
              <th className="der">Títulos</th>
              <th className="der">Invertido</th>
              <th className="der">Valor hoy</th>
              <th className="der">Rend.</th>
            </tr>
          </thead>
          <tbody>
            {filas.map((f, i) => {
              const pct = Number(f.rendimiento_pct);
              return (
                <tr
                  key={String(f.instrument_id ?? i)}
                  className={action ? "clickable" : undefined}
                  onClick={() => {
                    if (action && f.instrument_id) {
                      void emitir(action.name as ActionName, {
                        ...action.context,
                        instrument_id: f.instrument_id,
                      });
                    }
                  }}
                >
                  <td>
                    <strong>{String(f.instrumento ?? f.instrument_id)}</strong>
                    <span className="tbl-sub">{ETIQUETA_CLASE[String(f.clase)] ?? ""}</span>
                  </td>
                  <td className="der">{numero(f.titulos)}</td>
                  <td className="der">{moneda(f.costo_total)}</td>
                  <td className="der">{moneda(f.valor_mercado)}</td>
                  <td className={`der ${pct >= 0 ? "pos-up" : "pos-down"}`}>
                    {conSigno(pct, "porcentaje")}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
