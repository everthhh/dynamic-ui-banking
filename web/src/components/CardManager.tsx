// bank.CardManager — administrar UNA tarjeta.
//
// Tres acciones, las tres de bajo riesgo (no mueven dinero, por eso ninguna
// lleva el candado de dos pasos de inv.OrderTicket): bloquear/desbloquear es
// de un toque a propósito (urgencia real: tarjeta perdida), el límite se
// ajusta con un slider (soltar = confirmar, igual que inv.AmountSlider), y el
// alias es puramente cosmético.

import { useEffect, useRef, useState } from "react";
import { EditorAlias } from "./AccountsOverview";
import { CardVisual, type Tarjeta } from "./CardVisual";
import { moneda } from "../format";
import { useStore } from "../store";

export type CardManagerProps = {
  card?: unknown;
  ingresoMensual?: unknown;
  nodoId?: string;
};

// Debe coincidir con MULTIPLO_LIMITE_MAXIMO en services/banking.py — el
// servidor es quien de verdad lo hace valer, esto solo evita que el usuario
// arrastre el slider hasta un número que sabemos que va a rechazarse.
const MULTIPLO_LIMITE_MAXIMO = 3;

export function CardManager({ card, ingresoMensual }: CardManagerProps) {
  const emitir = useStore((s) => s.emitirAccion);
  const pensando = useStore((s) => s.estado === "pensando");
  const t = (typeof card === "object" && card !== null ? card : {}) as Tarjeta;

  const limiteActual = Number(t.limite_credito) || 0;
  const [limiteLocal, setLimiteLocal] = useState(limiteActual);
  const arrastrando = useRef(false);

  useEffect(() => {
    if (!arrastrando.current) setLimiteLocal(limiteActual);
  }, [limiteActual]);

  if (!t.card_id) {
    return <div className="rndr-hueco">No se encontró la tarjeta.</div>;
  }

  const bloqueada = t.estado === "bloqueada";
  const esCredito = t.tipo === "credito";
  const ingreso = Number(ingresoMensual) || 0;
  const topeLimite = Math.max(ingreso * MULTIPLO_LIMITE_MAXIMO, limiteActual);

  function soltarLimite() {
    arrastrando.current = false;
    if (Math.round(limiteLocal) === Math.round(limiteActual)) return;
    void emitir("update_card_limit", { card_id: t.card_id, nuevo_limite: Math.round(limiteLocal) });
  }

  return (
    <section className="cm">
      <CardVisual tarjeta={t} big />

      <header className="cm-cabeza">
        <div>
          <EditorAlias
            valorInicial={t.alias ?? ""}
            onGuardar={(alias) => void emitir("set_card_alias", { card_id: t.card_id, alias })}
          />
          <span className="cm-sub">
            {esCredito ? "Crédito" : "Débito"} •••• {t.last4}
          </span>
        </div>
        <span className={"ao-estado" + (bloqueada ? " bloqueada" : "")}>
          {bloqueada ? "Bloqueada" : "Activa"}
        </span>
      </header>

      <button
        type="button"
        className={"c-button " + (bloqueada ? "c-button-primary" : "c-button-ghost")}
        disabled={pensando}
        onClick={() => void emitir("toggle_card_block", { card_id: t.card_id, estado: t.estado })}
      >
        {bloqueada ? "Desbloquear tarjeta" : "Bloquear tarjeta"}
      </button>

      {esCredito ? (
        <label className="sl cm-slider">
          <span className="sl-cabeza">
            <span className="sl-label">Límite de crédito</span>
            <strong className="sl-valor">{moneda(limiteLocal)}</strong>
          </span>
          <input
            type="range"
            min={Math.max(1000, Number(t.saldo_utilizado) || 0)}
            max={topeLimite}
            step={1000}
            value={limiteLocal}
            disabled={pensando || bloqueada}
            onChange={(e) => {
              arrastrando.current = true;
              setLimiteLocal(Number(e.target.value));
            }}
            onMouseUp={soltarLimite}
            onTouchEnd={soltarLimite}
            onKeyUp={(e) => {
              if (e.key.startsWith("Arrow") || e.key === "Home" || e.key === "End") soltarLimite();
            }}
          />
          <span className="sl-limites">
            <span>Usado: {moneda(t.saldo_utilizado)}</span>
            <span>Máx: {moneda(topeLimite)}</span>
          </span>
        </label>
      ) : null}

      <p className="cm-nota">
        {bloqueada
          ? "Con la tarjeta bloqueada no se pueden hacer compras ni disposiciones."
          : esCredito
            ? "El límite no puede bajar del saldo ya usado ni pasar de 3 veces tu ingreso mensual."
            : "Puedes bloquearla en cualquier momento si la pierdes o ves un cargo que no reconoces."}
      </p>
    </section>
  );
}
