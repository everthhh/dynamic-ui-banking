// inv.ComparePanel — el componente que más vende la idea de UI generativa.
//
// Nadie programó una "pantalla de comparación". El agente decidió que la
// pregunta «¿y si fuera más conservador?» se responde con dos columnas y montó
// este componente con los datos que ya tenía. Cada fila marca cuál gana, y el
// marcador de abajo deja claro que ganar más métricas no vuelve a una opción la
// correcta.

import type { A2UIAction, ActionName } from "../catalog.types";
import { porFormato } from "../format";
import { useStore } from "../store";

type FilaMetrica = {
  metrica?: string;
  etiqueta?: string;
  formato?: string;
  izquierda?: number;
  derecha?: number;
  delta?: number;
  mejor?: "izquierda" | "derecha" | "empate";
};

type Lado = { etiqueta?: string; asignacion?: Record<string, number>; metricas?: Record<string, number> };

export type ComparePanelProps = {
  left?: unknown;
  right?: unknown;
  metrics?: unknown;
  action?: A2UIAction;
  disclaimer?: string;
  nodoId?: string;
};

function lado(v: unknown): Lado {
  return (typeof v === "object" && v !== null ? v : {}) as Lado;
}

export function ComparePanel({ left, right, metrics, action, disclaimer }: ComparePanelProps) {
  const emitir = useStore((s) => s.emitirAccion);
  const izq = lado(left);
  const der = lado(right);
  const filas: FilaMetrica[] = Array.isArray(metrics) ? (metrics as FilaMetrica[]) : [];

  if (!filas.length) {
    return <div className="rndr-hueco">La comparación llegó sin métricas.</div>;
  }

  const puntos = {
    izquierda: filas.filter((f) => f.mejor === "izquierda").length,
    derecha: filas.filter((f) => f.mejor === "derecha").length,
  };

  return (
    <section className="cmp">
      <div className="cmp-cabeza">
        <span />
        <div className="cmp-titulo">
          <strong>{izq.etiqueta ?? "Opción A"}</strong>
          <span className="cmp-sub">{Object.keys(izq.asignacion ?? {}).length} instrumentos</span>
        </div>
        <div className="cmp-titulo">
          <strong>{der.etiqueta ?? "Opción B"}</strong>
          <span className="cmp-sub">{Object.keys(der.asignacion ?? {}).length} instrumentos</span>
        </div>
      </div>

      <div className="cmp-filas">
        {filas.map((f) => (
          <div className="cmp-fila" key={f.metrica ?? f.etiqueta}>
            <span className="cmp-etiqueta">{f.etiqueta ?? f.metrica}</span>
            <span className={"cmp-celda" + (f.mejor === "izquierda" ? " gana" : "")}>
              {porFormato(f.izquierda, f.formato)}
            </span>
            <span className={"cmp-celda" + (f.mejor === "derecha" ? " gana" : "")}>
              {porFormato(f.derecha, f.formato)}
            </span>
          </div>
        ))}
      </div>

      <div className="cmp-pie">
        <span className="cmp-marcador">
          {puntos.izquierda} — {puntos.derecha} en métricas ganadas
        </span>
        {action ? (
          <span className="cmp-acciones">
            <button
              type="button"
              className="c-button c-button-secondary"
              onClick={() => void emitir(action.name as ActionName, { ...action.context, lado: "izquierda" })}
            >
              Quedarme como estoy
            </button>
            <button
              type="button"
              className="c-button c-button-primary"
              onClick={() => void emitir(action.name as ActionName, { ...action.context, lado: "derecha" })}
            >
              Cambiar a {der.etiqueta ?? "la otra"}
            </button>
          </span>
        ) : null}
      </div>

      <p className="cmp-disclaimer">{disclaimer ?? "Mismos supuestos en las dos columnas."}</p>
    </section>
  );
}
