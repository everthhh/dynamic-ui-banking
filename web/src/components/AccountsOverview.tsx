// bank.AccountsOverview — panorama de cuentas y tarjetas.
//
// Tocar una tarjeta pide administrarla (`manage_card`); el agente decide qué
// pintar después (normalmente `bank.CardManager`). El alias de una cuenta se
// edita en línea porque es de bajo riesgo — no necesita un viaje completo de
// ida y vuelta con el agente para confirmarse antes de mostrarse.

import { useState } from "react";
import { CardVisual, type Tarjeta } from "./CardVisual";
import { ETIQUETA_TIPO_CUENTA, moneda } from "../format";
import { useStore } from "../store";

type Cuenta = {
  account_id?: string;
  tipo?: string;
  alias?: string | null;
  moneda?: string;
  saldo_disponible?: number;
};

export type AccountsOverviewProps = {
  cuentas?: unknown;
  tarjetas?: unknown;
  nodoId?: string;
};

export function EditorAlias({
  valorInicial,
  onGuardar,
}: {
  valorInicial: string;
  onGuardar: (valor: string | null) => void;
}) {
  const [editando, setEditando] = useState(false);
  const [valor, setValor] = useState(valorInicial);

  function guardar() {
    setEditando(false);
    const limpio = valor.trim();
    if (limpio === valorInicial) return;
    onGuardar(limpio || null);
  }

  if (!editando) {
    return (
      <button type="button" className="ao-alias-editar" onClick={() => setEditando(true)}>
        {valorInicial || "Ponle un apodo"} <span aria-hidden>✎</span>
      </button>
    );
  }
  return (
    <input
      className="ao-alias-input"
      autoFocus
      maxLength={40}
      value={valor}
      onChange={(e) => setValor(e.target.value)}
      onBlur={guardar}
      onKeyDown={(e) => {
        if (e.key === "Enter") guardar();
        if (e.key === "Escape") {
          setValor(valorInicial);
          setEditando(false);
        }
      }}
    />
  );
}

export function AccountsOverview({ cuentas, tarjetas }: AccountsOverviewProps) {
  const emitirAccion = useStore((s) => s.emitirAccion);
  const listaCuentas = Array.isArray(cuentas) ? (cuentas as Cuenta[]) : [];
  const listaTarjetas = Array.isArray(tarjetas) ? (tarjetas as Tarjeta[]) : [];

  if (!listaCuentas.length && !listaTarjetas.length) {
    return <div className="rndr-hueco">Este cliente todavía no tiene cuentas ni tarjetas.</div>;
  }

  return (
    <section className="ao">
      {listaCuentas.length ? (
        <div className="ao-bloque">
          <h4 className="ao-titulo">Cuentas</h4>
          <ul className="ao-lista">
            {listaCuentas.map((c) => (
              <li key={c.account_id} className="ao-item">
                <div className="ao-item-info">
                  <span className="ao-item-tipo">
                    {ETIQUETA_TIPO_CUENTA[c.tipo ?? ""] ?? c.tipo}
                  </span>
                  <EditorAlias
                    valorInicial={c.alias ?? ""}
                    onGuardar={(alias) =>
                      void emitirAccion("set_account_alias", { account_id: c.account_id, alias })
                    }
                  />
                </div>
                <strong className="ao-item-saldo">{moneda(c.saldo_disponible)}</strong>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {listaTarjetas.length ? (
        <div className="ao-bloque">
          <h4 className="ao-titulo">Tarjetas</h4>
          <div className="ao-cards-grid">
            {listaTarjetas.map((t) => (
              <CardVisual
                key={t.card_id}
                tarjeta={t}
                onClick={() => void emitirAccion("manage_card", { card_id: t.card_id, card: t })}
              />
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
