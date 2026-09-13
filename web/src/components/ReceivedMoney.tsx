// pay.ReceivedMoney — lo que entró y quién lo mandó.
//
// Los totales por canal los calcula el banco (`por_canal`); aquí solo se escala
// cada barra contra la mayor para pintarla. Tocar un canal manda
// `filter_received` y el agente vuelve a pedir `get_received_money`.

import { ETIQUETA_CANAL_INGRESO, fechaCorta, moneda } from "../format";
import { useStore } from "../store";

type Movimiento = {
  txn_id?: string;
  fecha?: string;
  monto?: number;
  canal?: string;
  remitente?: string;
  banco_origen?: string | null;
  concepto?: string;
};

type Canal = { canal?: string; total?: number; movimientos?: number };

type Resumen = { total_recibido?: number; por_canal?: Canal[] };

export type ReceivedMoneyProps = {
  movimientos?: unknown;
  resumen?: unknown;
  filtro?: unknown;
  nodoId?: string;
};

export function ReceivedMoney({ nodoId, movimientos, resumen, filtro }: ReceivedMoneyProps) {
  const emitir = useStore((s) => s.emitirAccion);
  const filas = Array.isArray(movimientos) ? (movimientos as Movimiento[]) : [];
  const r = (typeof resumen === "object" && resumen !== null ? resumen : {}) as Resumen;
  const canales = Array.isArray(r.por_canal) ? r.por_canal : [];
  const mayor = Math.max(1, ...canales.map((c) => Number(c.total) || 0));
  const activo = typeof filtro === "string" && filtro ? filtro : null;

  return (
    <section className="ts">
      {r.total_recibido !== undefined ? (
        <div className="pg-totales">
          <div>
            <span>Dinero nuevo recibido</span>
            <strong className="pos-up">+{moneda(r.total_recibido, true)}</strong>
          </div>
        </div>
      ) : null}

      {canales.length ? (
        <ul className="pg-canales">
          {canales.map((c) => (
            <li key={c.canal}>
              <button
                type="button"
                className={"pg-canal" + (activo === c.canal ? " activo" : "")}
                onClick={() =>
                  void emitir("filter_received", { canal: activo === c.canal ? null : c.canal }, nodoId)
                }
              >
                <span className="pg-canal-nombre">
                  {ETIQUETA_CANAL_INGRESO[c.canal ?? ""] ?? c.canal}
                  <small>{c.movimientos}</small>
                </span>
                <span className="pg-barra">
                  <span style={{ width: `${((Number(c.total) || 0) / mayor) * 100}%` }} />
                </span>
                <span className="pg-canal-total">{moneda(c.total)}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {activo ? (
        <div>
          <button
            type="button"
            className="ts-chip"
            onClick={() => void emitir("filter_received", { canal: null }, nodoId)}
          >
            Ver todo lo recibido
          </button>
        </div>
      ) : null}

      {!filas.length ? (
        <div className="rndr-hueco">No entró dinero con ese filtro.</div>
      ) : (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Fecha</th>
                <th>De</th>
                <th>Canal</th>
                <th className="der">Monto</th>
              </tr>
            </thead>
            <tbody>
              {filas.map((m, i) => (
                <tr key={m.txn_id ?? i}>
                  <td>{fechaCorta(m.fecha)}</td>
                  <td>
                    <strong>{m.remitente}</strong>
                    <span className="tbl-sub">
                      {[m.banco_origen, m.concepto].filter(Boolean).join(" · ")}
                    </span>
                  </td>
                  <td>{ETIQUETA_CANAL_INGRESO[m.canal ?? ""] ?? m.canal}</td>
                  <td className="der pos-up">+{moneda(m.monto, true)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
