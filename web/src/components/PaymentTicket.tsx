// pay.PaymentTicket — confirmar y comprobar un pago, una transferencia o un retiro.
//
// Igual que inv.OrderTicket, el candado vive en tres capas: aquí hay que marcar
// la casilla y presionar; el agente llama `confirm_payment` solo con la acción
// del usuario; y el banco no ejecuta sin el `confirmation_token` del paso 1.
// Ya ejecutada, el mismo componente es el comprobante: folio, clave de rastreo
// o el código del retiro sin tarjeta.

import { useState } from "react";
import { leerAccion } from "../a2ui";
import type { A2UIAction } from "../catalog.types";
import { ETIQUETA_TIPO_PAGO, enGrupos, fechaHora, moneda } from "../format";
import { useStore } from "../store";

type Destino = {
  nombre?: string;
  convenio?: string;
  referencia_mask?: string | null;
  periodo?: string | null;
  banco?: string;
  numero_mask?: string | null;
  cuenta_propia?: boolean;
  canal?: string;
  codigo_vence_en?: string | null;
};

type Pago = {
  payment_id?: string;
  folio?: string;
  tipo?: string;
  estado?: string;
  monto?: number;
  comision?: number;
  total?: number;
  concepto?: string | null;
  account_id?: string;
  destino?: Destino;
  saldo_despues_estimado?: number;
  saldo_despues?: number;
  confirmation_token?: string;
  vence_en_minutos?: number;
  destino_nuevo?: boolean;
  clave_rastreo?: string | null;
  codigo_retiro?: string;
  codigo_vence_en?: string;
  mensaje?: string;
  motivo_rechazo?: string | null;
};

export type PaymentTicketProps = {
  payment?: unknown;
  action?: A2UIAction;
  requiresConfirmation?: boolean;
  disclaimer?: string;
  nodoId?: string;
};

export function PaymentTicket({
  nodoId,
  payment,
  action,
  requiresConfirmation = true,
  disclaimer,
}: PaymentTicketProps) {
  const emitir = useStore((s) => s.emitirAccion);
  const pensando = useStore((s) => s.estado === "pensando");
  const [acepto, setAcepto] = useState(false);
  const accion = leerAccion(action);
  const p = (typeof payment === "object" && payment !== null ? payment : {}) as Pago;

  if (!p.payment_id) {
    return <div className="rndr-hueco">El ticket llegó sin operación.</div>;
  }
  if (requiresConfirmation === false) {
    // El validador ya lo rechaza; el renderer tampoco lo monta.
    return (
      <div className="rndr-hueco">Este ticket venía sin confirmación en dos pasos. No lo monto.</div>
    );
  }

  const estado = p.estado ?? "pendiente";
  const pendiente = estado === "pendiente";
  const ejecutada = estado === "ejecutada";
  const esRetiro = p.tipo === "retiro_sin_tarjeta";
  const d = p.destino ?? {};
  const tipo = ETIQUETA_TIPO_PAGO[p.tipo ?? ""] ?? "Operación";
  const titulo = pendiente
    ? `${tipo} por confirmar`
    : ejecutada
      ? esRetiro
        ? "Retiro sin tarjeta listo"
        : `${tipo} hecha`
      : estado === "cancelada"
        ? "Operación cancelada"
        : "Operación rechazada";

  const cancelar = () => void emitir("cancel_payment", { payment_id: p.payment_id }, nodoId);

  return (
    <section className={`pt pt-${estado}`}>
      <header className="ot-cabeza">
        <div>
          <span className="ot-label">{titulo}</span>
          <strong className="ot-monto">{moneda(p.total ?? p.monto, true)}</strong>
        </div>
        <div className="ot-folio">
          <span>Folio</span>
          <code>{p.folio ?? "—"}</code>
        </div>
      </header>

      <dl className="pt-datos">
        {p.tipo === "servicio" ? (
          <>
            <div>
              <dt>Servicio</dt>
              <dd>{d.nombre}{d.convenio && d.convenio !== d.nombre ? ` · ${d.convenio}` : ""}</dd>
            </div>
            <div>
              <dt>Referencia</dt>
              <dd>{d.referencia_mask ?? "—"}</dd>
            </div>
            {d.periodo ? (
              <div>
                <dt>Periodo</dt>
                <dd>{d.periodo}</dd>
              </div>
            ) : null}
          </>
        ) : null}
        {p.tipo === "transferencia" ? (
          <>
            <div>
              <dt>Para</dt>
              <dd>{d.cuenta_propia ? `Tu cuenta ${d.numero_mask ?? ""}` : d.nombre}</dd>
            </div>
            {!d.cuenta_propia ? (
              <div>
                <dt>Banco</dt>
                <dd>{d.banco} {d.numero_mask}</dd>
              </div>
            ) : null}
            {p.concepto ? (
              <div>
                <dt>Concepto</dt>
                <dd>{p.concepto}</dd>
              </div>
            ) : null}
            {p.clave_rastreo ? (
              <div>
                <dt>Clave de rastreo</dt>
                <dd><code>{p.clave_rastreo}</code></dd>
              </div>
            ) : null}
          </>
        ) : null}
        {esRetiro ? (
          <div>
            <dt>Dónde</dt>
            <dd>{d.canal ?? "Cajeros del banco"}</dd>
          </div>
        ) : null}
        {p.comision ? (
          <div>
            <dt>Comisión</dt>
            <dd>{moneda(p.comision, true)}</dd>
          </div>
        ) : null}
        <div>
          <dt>Cuenta</dt>
          <dd><code>{p.account_id ?? "—"}</code></dd>
        </div>
        {pendiente || p.saldo_despues !== undefined ? (
          <div>
            <dt>{pendiente ? "Saldo estimado" : "Saldo después"}</dt>
            <dd>{moneda(pendiente ? p.saldo_despues_estimado : p.saldo_despues, true)}</dd>
          </div>
        ) : null}
      </dl>

      {ejecutada && esRetiro ? (
        p.codigo_retiro ? (
          <div className="pt-codigo">
            <span>Código para el cajero</span>
            <strong>{enGrupos(p.codigo_retiro)}</strong>
            <small>
              Vence {fechaHora(p.codigo_vence_en ?? d.codigo_vence_en)}. Se muestra una sola vez.
            </small>
          </div>
        ) : (
          <p className="ot-aviso">
            El código ya se mostró una vez. Si lo perdiste, cancela el retiro y genera otro.
          </p>
        )
      ) : null}

      {pendiente ? (
        <>
          {p.destino_nuevo ? (
            <p className="pt-aviso">
              Es la primera vez que le mandas dinero a esta cuenta: revisa bien el nombre y el banco.
            </p>
          ) : null}
          <label className="ot-acepto">
            <input
              type="checkbox"
              checked={acepto}
              disabled={pensando}
              onChange={(e) => setAcepto(e.target.checked)}
            />
            <span>Revisé el destino y el monto. Entiendo que es una operación simulada.</span>
          </label>
          <div className="ot-botones">
            <button type="button" className="c-button c-button-ghost" disabled={pensando} onClick={cancelar}>
              Cancelar
            </button>
            <button
              type="button"
              className="c-button c-button-primary"
              disabled={!acepto || pensando || !accion || !p.confirmation_token}
              onClick={() => {
                if (!accion) return;
                void emitir(
                  accion.name,
                  { ...accion.context, payment_id: p.payment_id, confirmation_token: p.confirmation_token },
                  nodoId,
                );
              }}
            >
              {pensando ? "Procesando…" : `Confirmar ${moneda(p.total ?? p.monto, true)}`}
            </button>
          </div>
          {!p.confirmation_token ? (
            <p className="ot-aviso">Esta operación no trae token de confirmación, así que no se puede ejecutar.</p>
          ) : p.vence_en_minutos ? (
            <p className="pt-nota">La confirmación vence en {p.vence_en_minutos} minutos.</p>
          ) : null}
        </>
      ) : null}

      {ejecutada && esRetiro ? (
        <div className="ot-botones">
          <button type="button" className="c-button c-button-ghost" disabled={pensando} onClick={cancelar}>
            Cancelar retiro
          </button>
        </div>
      ) : null}

      {!pendiente && p.mensaje ? (
        <p className={ejecutada ? "ot-listo" : "pt-cerrada"}>{p.mensaje}</p>
      ) : null}
      {estado === "rechazada" && p.motivo_rechazo ? <p className="ot-aviso">{p.motivo_rechazo}</p> : null}

      <p className="ot-disclaimer">
        {disclaimer ?? "Operación simulada sobre datos sintéticos. No mueve dinero real."}
      </p>
    </section>
  );
}
