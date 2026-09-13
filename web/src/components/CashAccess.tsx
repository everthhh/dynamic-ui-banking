// pay.CashAccess — meter y sacar dinero.
//
// Sacar: retiro sin tarjeta. El botón no genera el código: manda
// `prepare_withdrawal`, el agente llama el paso 1 y regresa un ticket, y el
// código aparece hasta confirmar. Meter: la CLABE para compartir (copiarla es
// local, no cambia nada) y los corresponsales. En una tienda, la referencia la
// genera el banco (`request_deposit_reference`) y el dinero llega cuando la
// tienda confirma: ningún botón de aquí acredita nada.

import { useState } from "react";
import { ETIQUETA_TIPO_CUENTA, enGrupos, fechaHora, moneda } from "../format";
import { useStore } from "../store";

type Cuenta = {
  account_id?: string;
  tipo?: string;
  alias?: string | null;
  clabe?: string;
  banco?: string;
  titular?: string;
  transaccional?: boolean;
};

type Canal = {
  canal_id?: string;
  nombre?: string;
  operaciones?: string[];
  comision_deposito?: number;
  monto_maximo_deposito?: number;
  requiere_referencia?: boolean;
  como?: string;
};

type Retiro = {
  monto_minimo?: number;
  monto_maximo?: number;
  multiplo?: number;
  vigencia_horas?: number;
  canal?: string;
};

type Referencia = {
  referencia?: string;
  canal?: string;
  como?: string;
  comision?: number;
  monto_maximo?: number;
  vence_en?: string;
};

export type CashAccessProps = {
  cuentas?: unknown;
  canales?: unknown;
  retiro?: unknown;
  referencia?: unknown;
  nodoId?: string;
};

const MONTOS_RAPIDOS = [500, 1000, 2000, 5000];

function nombreCuenta(c: Cuenta): string {
  return c.alias || ETIQUETA_TIPO_CUENTA[c.tipo ?? ""] || c.tipo || "Cuenta";
}

export function CashAccess({ nodoId, cuentas, canales, retiro, referencia }: CashAccessProps) {
  const emitir = useStore((s) => s.emitirAccion);
  const pensando = useStore((s) => s.estado === "pensando");
  const listaCuentas = Array.isArray(cuentas) ? (cuentas as Cuenta[]) : [];
  const transaccionales = listaCuentas.filter((c) => c.transaccional);
  const listaCanales = Array.isArray(canales) ? (canales as Canal[]) : [];
  const reglas = (typeof retiro === "object" && retiro !== null ? retiro : {}) as Retiro;
  const ref = (typeof referencia === "object" && referencia !== null ? referencia : null) as Referencia | null;

  const [cuenta, setCuenta] = useState(transaccionales[0]?.account_id ?? "");
  const [rapido, setRapido] = useState<number | null>(null);
  const [otro, setOtro] = useState("");
  const [copiada, setCopiada] = useState<string | null>(null);

  const multiplo = Number(reglas.multiplo) || 100;
  const minimo = Number(reglas.monto_minimo) || multiplo;
  const maximo = Number(reglas.monto_maximo) || Infinity;
  const monto = rapido ?? (otro ? Number(otro) : NaN);
  const montoValido =
    Number.isFinite(monto) && monto >= minimo && monto <= maximo && monto % multiplo === 0;

  async function copiar(clabe: string | undefined) {
    if (!clabe) return;
    try {
      await navigator.clipboard.writeText(clabe);
      setCopiada(clabe);
    } catch {
      setCopiada(null);
    }
  }

  return (
    <section className="pg-cash">
      <div className="pg-bloque">
        <h4 className="ao-titulo">Sacar efectivo sin tarjeta</h4>
        {transaccionales.length > 1 ? (
          <label className="pg-campo">
            <span>De la cuenta</span>
            <select value={cuenta} onChange={(e) => setCuenta(e.target.value)}>
              {transaccionales.map((c) => (
                <option key={c.account_id} value={c.account_id}>
                  {nombreCuenta(c)}
                </option>
              ))}
            </select>
          </label>
        ) : null}
        <div className="ts-chips">
          {MONTOS_RAPIDOS.filter((m) => m <= maximo).map((m) => (
            <button
              key={m}
              type="button"
              className={"ts-chip" + (rapido === m ? " activo" : "")}
              onClick={() => {
                setRapido(m);
                setOtro("");
              }}
            >
              {moneda(m)}
            </button>
          ))}
        </div>
        <label className="pg-campo">
          <span>Otro monto, en múltiplos de {moneda(multiplo)}</span>
          <input
            inputMode="numeric"
            value={otro}
            placeholder={`${moneda(minimo)} a ${moneda(maximo)}`}
            className={otro && !montoValido ? "invalido" : ""}
            onChange={(e) => {
              setOtro(e.target.value.replace(/\D/g, ""));
              setRapido(null);
            }}
          />
        </label>
        <div>
          <button
            type="button"
            className="c-button c-button-primary"
            disabled={!montoValido || !cuenta || pensando}
            onClick={() => void emitir("prepare_withdrawal", { account_id: cuenta, monto }, nodoId)}
          >
            {montoValido ? `Preparar retiro de ${moneda(monto)}` : "Preparar retiro"}
          </button>
        </div>
        <p className="pg-nota">
          El código se genera cuando confirmas y vence en {reglas.vigencia_horas ?? 24} horas. Úsalo en{" "}
          {reglas.canal ?? "un cajero del banco"}.
        </p>
      </div>

      <div className="pg-bloque">
        <h4 className="ao-titulo">Para que te depositen</h4>
        <ul className="pg-lista">
          {listaCuentas.map((c) => (
            <li key={c.account_id} className="pg-item">
              <div className="pg-item-info">
                <strong>{nombreCuenta(c)}</strong>
                <span className="pg-sub">
                  {c.banco} · {c.titular}
                </span>
                <code className="pg-clabe">{enGrupos(c.clabe)}</code>
              </div>
              <button type="button" className="c-button c-button-secondary" onClick={() => void copiar(c.clabe)}>
                {copiada === c.clabe ? "Copiada" : "Copiar CLABE"}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="pg-bloque">
        <h4 className="ao-titulo">Depositar efectivo</h4>
        {ref?.referencia ? (
          <div className="pt-codigo">
            <span>Referencia para {ref.canal}</span>
            <strong>{enGrupos(ref.referencia)}</strong>
            <small>
              {ref.como} Comisión de la tienda: {moneda(ref.comision, true)} · máximo{" "}
              {moneda(ref.monto_maximo)} · vence {fechaHora(ref.vence_en)}.
            </small>
          </div>
        ) : null}
        <ul className="pg-lista">
          {listaCanales
            .filter((c) => c.operaciones?.includes("deposito"))
            .map((c) => (
              <li key={c.canal_id} className="pg-item">
                <div className="pg-item-info">
                  <strong>{c.nombre}</strong>
                  <span className="pg-sub">{c.como}</span>
                </div>
                <div className="pg-item-cobro">
                  <strong>{c.comision_deposito ? moneda(c.comision_deposito, true) : "Sin comisión"}</strong>
                  <span className="pg-sub">hasta {moneda(c.monto_maximo_deposito)}</span>
                </div>
                {c.requiere_referencia ? (
                  <button
                    type="button"
                    className="c-button c-button-secondary"
                    disabled={pensando || !cuenta}
                    onClick={() =>
                      void emitir("request_deposit_reference", { canal_id: c.canal_id, account_id: cuenta }, nodoId)
                    }
                  >
                    Generar referencia
                  </button>
                ) : null}
              </li>
            ))}
        </ul>
        <p className="pg-nota">Las comisiones de las tiendas son estimadas y las cobra la tienda, no el banco.</p>
      </div>
    </section>
  );
}
