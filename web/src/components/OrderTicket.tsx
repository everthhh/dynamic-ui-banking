// inv.OrderTicket — el único componente que mueve dinero.
//
// La confirmación en dos pasos existe en tres capas, a propósito:
//   1. aquí, el usuario tiene que marcar la casilla y después presionar;
//   2. en el agente, `place_order` se llama dos veces;
//   3. en el banco, sin `confirmation_token` válido la orden no se ejecuta.
// Quitar cualquiera de las tres y la demo dejaría de ser defendible.

import { useState } from "react";
import { leerAccion } from "../a2ui";
import type { A2UIAction } from "../catalog.types";
import { moneda, numero, porcentaje } from "../format";
import { useStore } from "../store";

type Leg = {
  instrument_id?: string;
  instrumento?: string;
  peso?: number;
  monto?: number;
  titulos?: number;
};

type Orden = {
  folio?: string;
  order_id?: string;
  estado?: string;
  monto?: number;
  legs?: Leg[];
  saldo_antes?: number;
  saldo_despues_estimado?: number;
  saldo_despues?: number;
  confirmation_token?: string;
  account_id?: string;
  mensaje?: string;
};

export type OrderTicketProps = {
  order?: unknown;
  action?: A2UIAction;
  requiresConfirmation?: boolean;
  disclaimer?: string;
  nodoId?: string;
};

export function OrderTicket({
  nodoId,
  order,
  action,
  requiresConfirmation = true,
  disclaimer,
}: OrderTicketProps) {
  const emitir = useStore((s) => s.emitirAccion);
  const pensando = useStore((s) => s.estado === "pensando");
  const [acepto, setAcepto] = useState(false);
  const accion = leerAccion(action);

  const o = (typeof order === "object" && order !== null ? order : {}) as Orden;

  if (!o.folio && !o.monto) {
    return <div className="rndr-hueco">El ticket llegó sin orden.</div>;
  }

  if (requiresConfirmation === false) {
    // El renderer también se niega: el catálogo lo prohíbe y aquí se hace valer.
    return (
      <div className="rndr-hueco">
        Este ticket venía sin confirmación en dos pasos. No lo monto.
      </div>
    );
  }

  const ejecutada = o.estado === "ejecutada";
  const legs = Array.isArray(o.legs) ? o.legs : [];

  return (
    <section className={"ot" + (ejecutada ? " ot-ejecutada" : "")}>
      <header className="ot-cabeza">
        <div>
          <span className="ot-label">{ejecutada ? "Orden ejecutada" : "Orden por confirmar"}</span>
          <strong className="ot-monto">{moneda(o.monto)}</strong>
        </div>
        <div className="ot-folio">
          <span>Folio</span>
          <code>{o.folio ?? "—"}</code>
        </div>
      </header>

      <ul className="ot-legs">
        {legs.map((l, i) => (
          <li key={String(l.instrument_id ?? i)}>
            <span className="ot-leg-nombre">{l.instrumento ?? l.instrument_id}</span>
            <span className="ot-leg-peso">{porcentaje(l.peso)}</span>
            <span className="ot-leg-monto">{moneda(l.monto)}</span>
            <span className="ot-leg-titulos">{numero(l.titulos)} títulos</span>
          </li>
        ))}
      </ul>

      <div className="ot-saldos">
        <span>
          Cuenta <code>{o.account_id ?? "—"}</code>
        </span>
        <span>
          Saldo {ejecutada ? "después" : "estimado"}:{" "}
          <strong>{moneda(ejecutada ? o.saldo_despues : o.saldo_despues_estimado)}</strong>
        </span>
      </div>

      {ejecutada ? (
        <p className="ot-listo">{o.mensaje ?? "Listo. Ya quedó registrada."}</p>
      ) : (
        <>
          <label className="ot-acepto">
            <input
              type="checkbox"
              checked={acepto}
              onChange={(e) => setAcepto(e.target.checked)}
              disabled={pensando}
            />
            <span>
              Entiendo que es una operación simulada y que los escenarios no garantizan
              resultados.
            </span>
          </label>
          <div className="ot-botones">
            <button
              type="button"
              className="c-button c-button-ghost"
              disabled={pensando}
              onClick={() => void emitir("cancel_order", { order_id: o.order_id }, nodoId)}
            >
              Cancelar
            </button>
            <button
              type="button"
              className="c-button c-button-primary"
              disabled={!acepto || pensando || !accion || !o.confirmation_token}
              onClick={() => {
                if (!accion) return;
                void emitir(
                  accion.name,
                  { ...accion.context, order_id: o.order_id, confirmation_token: o.confirmation_token },
                  nodoId,
                );
              }}
            >
              {pensando ? "Procesando…" : `Confirmar ${moneda(o.monto)}`}
            </button>
          </div>
          {!o.confirmation_token ? (
            <p className="ot-aviso">
              Esta orden no trae token de confirmación, así que no se puede ejecutar.
            </p>
          ) : null}
        </>
      )}

      <p className="ot-disclaimer">
        {disclaimer ?? "Operación simulada sobre datos sintéticos. No mueve dinero real."}
      </p>
    </section>
  );
}
