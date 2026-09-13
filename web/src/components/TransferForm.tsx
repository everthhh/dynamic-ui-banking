// pay.TransferForm — armar una transferencia.
//
// No transfiere: junta origen, destino, monto y concepto y los manda en
// `prepare_transfer`. El agente llama el paso 1 y regresa un ticket por
// confirmar. La CLABE se revisa aquí con su dígito verificador solo para
// ahorrarle al usuario un viaje de ida y vuelta; el servidor la vuelve a validar.

import { useState } from "react";
import { BANCOS_SPEI, ETIQUETA_TIPO_CUENTA, clabeValida, enGrupos, moneda } from "../format";
import { useStore } from "../store";

type Cuenta = {
  account_id?: string;
  tipo?: string;
  alias?: string | null;
  saldo_disponible?: number;
  transaccional?: boolean;
};

type Contacto = {
  beneficiary_id?: string;
  alias?: string;
  titular?: string;
  banco?: string;
  numero_mask?: string;
  destino_nuevo?: boolean;
  tope_por_operacion?: number | null;
};

type Destino = "beneficiario" | "clabe" | "cuenta_propia";

export type TransferFormProps = {
  cuentas?: unknown;
  beneficiarios?: unknown;
  monto?: unknown;
  concepto?: unknown;
  nodoId?: string;
};

// Debe coincidir con CONCEPTO_LARGO_MAXIMO en bank/pagos.py (el campo de SPEI).
const CONCEPTO_MAX = 40;

const PESTANAS: { id: Destino; label: string }[] = [
  { id: "beneficiario", label: "Contactos" },
  { id: "clabe", label: "CLABE nueva" },
  { id: "cuenta_propia", label: "Mis cuentas" },
];

function nombreCuenta(c: Cuenta): string {
  return c.alias || ETIQUETA_TIPO_CUENTA[c.tipo ?? ""] || c.tipo || "Cuenta";
}

export function TransferForm({ nodoId, cuentas, beneficiarios, monto, concepto }: TransferFormProps) {
  const emitir = useStore((s) => s.emitirAccion);
  const pensando = useStore((s) => s.estado === "pensando");
  const listaCuentas = Array.isArray(cuentas) ? (cuentas as Cuenta[]) : [];
  const contactos = Array.isArray(beneficiarios) ? (beneficiarios as Contacto[]) : [];

  const [origen, setOrigen] = useState(
    listaCuentas.find((c) => c.transaccional)?.account_id ?? listaCuentas[0]?.account_id ?? "",
  );
  const [destino, setDestino] = useState<Destino>(contactos.length ? "beneficiario" : "clabe");
  const [contactoId, setContactoId] = useState(contactos[0]?.beneficiary_id ?? "");
  const [clabe, setClabe] = useState("");
  const [titular, setTitular] = useState("");
  const [guardar, setGuardar] = useState(false);
  const [alias, setAlias] = useState("");
  const [cuentaDestino, setCuentaDestino] = useState("");
  const [importe, setImporte] = useState(Number(monto) > 0 ? String(monto) : "");
  const [texto, setTexto] = useState(
    typeof concepto === "string" ? concepto.slice(0, CONCEPTO_MAX) : "",
  );

  if (!listaCuentas.length) {
    return <div className="rndr-hueco">No llegaron las cuentas del cliente.</div>;
  }

  const cuentaOrigen = listaCuentas.find((c) => c.account_id === origen);
  const clabeLimpia = clabe.replace(/[\s-]/g, "");
  const clabeOk = clabeValida(clabeLimpia);
  const otrasCuentas = listaCuentas.filter((c) => c.account_id !== origen);
  const destinoPropio = otrasCuentas.some((c) => c.account_id === cuentaDestino)
    ? cuentaDestino
    : (otrasCuentas[0]?.account_id ?? "");
  const contacto = contactos.find((c) => c.beneficiary_id === contactoId);
  const cantidad = Number(importe);

  const destinoListo =
    destino === "beneficiario"
      ? !!contacto
      : destino === "clabe"
        ? clabeOk && titular.trim().length > 0 && (!guardar || alias.trim().length > 0)
        : !!destinoPropio;
  // La cuenta de inversión solo puede traspasar a otra cuenta propia.
  const origenPermitido = destino === "cuenta_propia" || cuentaOrigen?.transaccional !== false;
  const listo = !!origen && destinoListo && origenPermitido && Number.isFinite(cantidad) && cantidad > 0;

  function enviar() {
    const base = {
      account_id: origen,
      destino,
      monto: Math.round(cantidad * 100) / 100,
      concepto: texto.trim() || null,
    };
    const contexto =
      destino === "beneficiario"
        ? { ...base, beneficiary_id: contacto?.beneficiary_id }
        : destino === "clabe"
          ? {
              ...base,
              clabe: clabeLimpia,
              titular: titular.trim(),
              guardar_contacto: guardar,
              alias: guardar ? alias.trim() : null,
            }
          : { ...base, cuenta_destino_id: destinoPropio };
    void emitir("prepare_transfer", contexto, nodoId);
  }

  return (
    <section className="pg-form">
      <label className="pg-campo">
        <span>Desde</span>
        <select value={origen} onChange={(e) => setOrigen(e.target.value)}>
          {listaCuentas.map((c) => (
            <option key={c.account_id} value={c.account_id}>
              {nombreCuenta(c)} · {moneda(c.saldo_disponible)}
            </option>
          ))}
        </select>
      </label>

      <div className="pg-tabs" role="tablist">
        {PESTANAS.map((p) => (
          <button
            key={p.id}
            type="button"
            role="tab"
            aria-selected={destino === p.id}
            className={"pg-tab" + (destino === p.id ? " activo" : "")}
            onClick={() => setDestino(p.id)}
          >
            {p.label}
          </button>
        ))}
      </div>

      {destino === "beneficiario" ? (
        contactos.length ? (
          <ul className="pg-contactos">
            {contactos.map((c) => (
              <li key={c.beneficiary_id}>
                <label className={"pg-contacto" + (c.beneficiary_id === contactoId ? " activo" : "")}>
                  <input
                    type="radio"
                    name={`contacto-${nodoId ?? "transferencia"}`}
                    checked={c.beneficiary_id === contactoId}
                    onChange={() => setContactoId(c.beneficiary_id ?? "")}
                  />
                  <span className="pg-item-info">
                    <strong>{c.alias}</strong>
                    <span className="pg-sub">
                      {c.titular} · {c.banco} {c.numero_mask}
                    </span>
                  </span>
                  {c.destino_nuevo ? (
                    <span className="c-badge c-badge-warning">
                      Nuevo · hasta {moneda(c.tope_por_operacion)}
                    </span>
                  ) : null}
                </label>
              </li>
            ))}
          </ul>
        ) : (
          <div className="rndr-hueco">No tienes contactos guardados. Usa «CLABE nueva».</div>
        )
      ) : null}

      {destino === "clabe" ? (
        <div className="pg-grupo">
          <label className="pg-campo">
            <span>CLABE (18 dígitos)</span>
            <input
              inputMode="numeric"
              autoComplete="off"
              maxLength={24}
              value={clabe}
              className={clabeLimpia.length === 18 && !clabeOk ? "invalido" : ""}
              onChange={(e) => setClabe(e.target.value)}
            />
            {clabeLimpia.length !== 18 ? (
              <small className="pg-sub">{clabeLimpia.length}/18</small>
            ) : clabeOk ? (
              <small className="pg-ok">
                {BANCOS_SPEI[clabeLimpia.slice(0, 3)] ?? "Banco no participante"} · {enGrupos(clabeLimpia)}
              </small>
            ) : (
              <small className="pg-error">El dígito verificador no cuadra: revisa la CLABE.</small>
            )}
          </label>
          <label className="pg-campo">
            <span>Nombre de quien recibe</span>
            <input maxLength={60} value={titular} onChange={(e) => setTitular(e.target.value)} />
          </label>
          <label className="pg-check">
            <input type="checkbox" checked={guardar} onChange={(e) => setGuardar(e.target.checked)} />
            <span>Guardar como contacto</span>
          </label>
          {guardar ? (
            <label className="pg-campo">
              <span>Apodo del contacto</span>
              <input
                maxLength={40}
                value={alias}
                placeholder="Ej. Mamá"
                onChange={(e) => setAlias(e.target.value)}
              />
            </label>
          ) : null}
          <p className="pg-nota">
            A una cuenta nueva el banco le pone tope por operación; guardarla no lo quita de inmediato.
          </p>
        </div>
      ) : null}

      {destino === "cuenta_propia" ? (
        otrasCuentas.length ? (
          <label className="pg-campo">
            <span>A mi cuenta</span>
            <select value={destinoPropio} onChange={(e) => setCuentaDestino(e.target.value)}>
              {otrasCuentas.map((c) => (
                <option key={c.account_id} value={c.account_id}>
                  {nombreCuenta(c)}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <div className="rndr-hueco">No tienes otra cuenta a la cual traspasar.</div>
        )
      ) : null}

      <div className="pg-fila">
        <label className="pg-campo">
          <span>Monto</span>
          <input
            inputMode="decimal"
            value={importe}
            placeholder="0.00"
            onChange={(e) => setImporte(e.target.value.replace(/[^\d.]/g, ""))}
          />
        </label>
        <label className="pg-campo">
          <span>Concepto</span>
          <input
            maxLength={CONCEPTO_MAX}
            value={texto}
            placeholder="Ej. Renta septiembre"
            onChange={(e) => setTexto(e.target.value)}
          />
        </label>
      </div>

      {!origenPermitido ? (
        <p className="pg-error">De la cuenta de inversión solo puedes traspasar a tus otras cuentas.</p>
      ) : null}

      <div>
        <button
          type="button"
          className="c-button c-button-primary"
          disabled={!listo || pensando}
          onClick={enviar}
        >
          Revisar transferencia
        </button>
      </div>
      <p className="pg-nota">Todavía no se mueve nada: en el siguiente paso revisas y confirmas.</p>
    </section>
  );
}
