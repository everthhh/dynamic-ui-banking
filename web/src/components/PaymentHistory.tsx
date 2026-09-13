// pay.PaymentHistory — lo que salió: servicios, transferencias y retiros.
//
// Los chips no filtran en el cliente: mandan `filter_history` y el agente vuelve
// a llamar `get_payment_history`, igual que bank.TransactionSearch.

import { ETIQUETA_ESTADO_PAGO, ETIQUETA_TIPO_PAGO, fechaCorta, moneda } from "../format";
import { useStore } from "../store";

type Pago = {
  payment_id?: string;
  folio?: string;
  tipo?: string;
  estado?: string;
  total?: number;
  fecha?: string;
  destino?: { nombre?: string; banco?: string; numero_mask?: string | null; referencia_mask?: string | null };
};

type Resumen = {
  total_pagado?: number;
  por_tipo?: { tipo?: string; operaciones?: number; total?: number }[];
};

export type PaymentHistoryProps = {
  pagos?: unknown;
  resumen?: unknown;
  filtro?: unknown;
  nodoId?: string;
};

const TIPOS = ["servicio", "transferencia", "retiro_sin_tarjeta"];

const TONO_ESTADO: Record<string, string> = {
  ejecutada: "positive",
  pendiente: "warning",
  rechazada: "danger",
  cancelada: "neutral",
};

export function PaymentHistory({ nodoId, pagos, resumen, filtro }: PaymentHistoryProps) {
  const emitir = useStore((s) => s.emitirAccion);
  const filas = Array.isArray(pagos) ? (pagos as Pago[]) : [];
  const r = (typeof resumen === "object" && resumen !== null ? resumen : {}) as Resumen;
  const activo = typeof filtro === "string" && filtro ? filtro : null;

  return (
    <section className="ts">
      <div className="ts-chips">
        <button
          type="button"
          className={"ts-chip" + (!activo ? " activo" : "")}
          onClick={() => void emitir("filter_history", { tipo: null }, nodoId)}
        >
          Todo
        </button>
        {TIPOS.map((t) => (
          <button
            key={t}
            type="button"
            className={"ts-chip" + (activo === t ? " activo" : "")}
            onClick={() => void emitir("filter_history", { tipo: t }, nodoId)}
          >
            {ETIQUETA_TIPO_PAGO[t]}
          </button>
        ))}
      </div>

      {r.total_pagado !== undefined ? (
        <div className="pg-totales">
          <div>
            <span>Total pagado</span>
            <strong>{moneda(r.total_pagado, true)}</strong>
          </div>
          {(r.por_tipo ?? []).map((t) => (
            <div key={t.tipo}>
              <span>
                {ETIQUETA_TIPO_PAGO[t.tipo ?? ""] ?? t.tipo} · {t.operaciones}
              </span>
              <strong>{moneda(t.total, true)}</strong>
            </div>
          ))}
        </div>
      ) : null}

      {!filas.length ? (
        <div className="rndr-hueco">No hay operaciones con ese filtro.</div>
      ) : (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Destino</th>
                <th>Estado</th>
                <th className="der">Monto</th>
              </tr>
            </thead>
            <tbody>
              {filas.map((p, i) => {
                const numero = p.destino?.referencia_mask ?? p.destino?.numero_mask;
                const hecha = p.estado === "ejecutada";
                return (
                  <tr key={p.payment_id ?? i}>
                    <td>{fechaCorta(p.fecha)}</td>
                    <td>
                      <strong>{p.destino?.nombre ?? ETIQUETA_TIPO_PAGO[p.tipo ?? ""]}</strong>
                      <span className="tbl-sub">
                        {[ETIQUETA_TIPO_PAGO[p.tipo ?? ""], p.destino?.banco, numero, p.folio]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </td>
                    <td>
                      <span className={`c-badge c-badge-${TONO_ESTADO[p.estado ?? ""] ?? "neutral"}`}>
                        {ETIQUETA_ESTADO_PAGO[p.estado ?? ""] ?? p.estado}
                      </span>
                    </td>
                    <td className={"der " + (hecha ? "pos-down" : "pg-tachado")}>
                      −{moneda(p.total, true)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
