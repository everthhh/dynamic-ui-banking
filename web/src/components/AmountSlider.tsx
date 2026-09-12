// inv.AmountSlider — donde vive el binding bidireccional.
//
// Hacia abajo: el agente escribe la ruta y el control se redibuja.
// Hacia arriba: el usuario arrastra, se escribe el valor local de inmediato
// (para que se sienta instantáneo) y al SOLTAR se manda la acción. Arrastrar no
// dispara un turno por píxel; soltar dispara uno.

import { useEffect, useRef, useState } from "react";
import { esBinding, leerAccion } from "../a2ui";
import type { A2UIAction } from "../catalog.types";
import { porFormato } from "../format";
import { useStore } from "../store";

export type AmountSliderProps = {
  label?: string;
  value?: unknown;
  min?: number;
  max?: number;
  step?: number;
  format?: string;
  action?: A2UIAction;
  nodoId?: string;
};

export function AmountSlider({
  label,
  value,
  min = 0,
  max = 100,
  step = 100,
  format = "moneda",
  action,
  nodoId,
}: AmountSliderProps) {
  const escribirLocal = useStore((s) => s.escribirLocal);
  const emitir = useStore((s) => s.emitirAccion);
  const pensando = useStore((s) => s.estado === "pensando");

  // La ruta a la que está enlazado este control. El renderer ya resolvió el
  // binding, así que la recuperamos del nodo original para poder escribir.
  const ruta = useStore((s) => {
    const sid = s.superficieActiva;
    if (!sid || !nodoId) return null;
    const nodo = s.superficies[sid]?.componentes[nodoId];
    const v = nodo?.value;
    return esBinding(v) ? v.path : null;
  });

  const numerico = Number(value);
  const [local, setLocal] = useState(Number.isFinite(numerico) ? numerico : min);
  const arrastrando = useRef(false);

  // Si el agente reescribe el valor mientras no estamos arrastrando, obedecemos.
  useEffect(() => {
    if (!arrastrando.current && Number.isFinite(numerico)) setLocal(numerico);
  }, [numerico]);

  function soltar() {
    arrastrando.current = false;
    const accion = leerAccion(action);
    if (!accion) return;
    void emitir(accion.name, { ...accion.context, [claveDeContexto(label)]: local }, nodoId);
  }

  return (
    <label className="sl">
      <span className="sl-cabeza">
        <span className="sl-label">{label}</span>
        <strong className="sl-valor">{porFormato(local, format)}</strong>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={local}
        disabled={pensando}
        onChange={(e) => {
          arrastrando.current = true;
          const v = Number(e.target.value);
          setLocal(v);
          if (ruta) escribirLocal(ruta, v);
        }}
        onMouseUp={soltar}
        onTouchEnd={soltar}
        onKeyUp={(e) => {
          if (e.key.startsWith("Arrow") || e.key === "Home" || e.key === "End") soltar();
        }}
      />
      <span className="sl-limites">
        <span>{porFormato(min, format)}</span>
        <span>{porFormato(max, format)}</span>
      </span>
    </label>
  );
}

/** El agente espera `amount`, `horizon` o `monthly` en el contexto de `simulate`. */
function claveDeContexto(label: string | undefined): string {
  const l = (label ?? "").toLowerCase();
  if (l.includes("plazo") || l.includes("año") || l.includes("horizonte")) return "horizon";
  if (l.includes("mensual") || l.includes("aporta")) return "monthly";
  return "amount";
}
