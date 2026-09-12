// Primitivos del catálogo. Deliberadamente pocos: el modelo debe alcanzar los
// componentes de dominio, no reinventarlos apilando Row y Text.

import type { ReactNode } from "react";
import { leerAccion } from "../a2ui";
import type { A2UIAction } from "../catalog.types";
import { porFormato } from "../format";
import { useStore } from "../store";

export type ComunProps = { nodoId?: string; children?: ReactNode };

export function Column({
  children,
  gap = 16,
  align = "stretch",
}: ComunProps & { gap?: number; align?: string }) {
  return (
    <div className="c-column" style={{ gap, alignItems: align }}>
      {children}
    </div>
  );
}

export function Row({
  children,
  gap = 12,
  align = "center",
  wrap = true,
}: ComunProps & { gap?: number; align?: string; wrap?: boolean }) {
  return (
    <div
      className="c-row"
      style={{ gap, alignItems: align, flexWrap: wrap ? "wrap" : "nowrap" }}
    >
      {children}
    </div>
  );
}

export function Card({
  children,
  title,
  subtitle,
  tone = "neutral",
}: ComunProps & { title?: string; subtitle?: string; tone?: string }) {
  return (
    <section className={`c-card c-tone-${tone}`}>
      {title ? <h3 className="c-card-title">{title}</h3> : null}
      {subtitle ? <p className="c-card-subtitle">{subtitle}</p> : null}
      {children}
    </section>
  );
}

export function Text({
  text,
  variant = "body",
  tone = "default",
}: ComunProps & { text?: unknown; variant?: string; tone?: string }) {
  const contenido = text === null || text === undefined ? "" : String(text);
  const clase = `c-text c-text-${variant} c-tone-text-${tone}`;
  if (variant === "h1") return <h1 className={clase}>{contenido}</h1>;
  if (variant === "h2") return <h2 className={clase}>{contenido}</h2>;
  if (variant === "h3") return <h3 className={clase}>{contenido}</h3>;
  if (variant === "caption") return <p className={`${clase} c-caption`}>{contenido}</p>;
  return <p className={clase}>{contenido}</p>;
}

export function Divider() {
  return <hr className="c-divider" />;
}

export function Button({
  nodoId,
  label,
  action,
  variant = "secondary",
  disabled = false,
}: ComunProps & { label?: string; action?: A2UIAction; variant?: string; disabled?: boolean }) {
  const emitir = useStore((s) => s.emitirAccion);
  const pensando = useStore((s) => s.estado === "pensando");
  const accion = leerAccion(action);
  return (
    <button
      type="button"
      className={`c-button c-button-${variant}`}
      disabled={disabled || pensando || !accion}
      onClick={() => {
        if (accion) void emitir(accion.name, accion.context, nodoId);
      }}
    >
      {label ?? "…"}
    </button>
  );
}

export function Badge({ label, tone = "neutral" }: ComunProps & { label?: unknown; tone?: string }) {
  return <span className={`c-badge c-badge-${tone}`}>{String(label ?? "")}</span>;
}

export function Stat({
  label,
  value,
  format = "numero",
  delta,
  hint,
}: ComunProps & {
  label?: string;
  value?: unknown;
  format?: string;
  delta?: unknown;
  hint?: string;
}) {
  const d = Number(delta);
  const tieneDelta = Number.isFinite(d) && d !== 0;
  return (
    <div className="c-stat">
      <span className="c-stat-label">{label}</span>
      <strong className="c-stat-value">{porFormato(value, format)}</strong>
      {tieneDelta ? (
        <span className={`c-stat-delta ${d > 0 ? "pos" : "neg"}`}>
          {d > 0 ? "▲" : "▼"} {porFormato(Math.abs(d), format)}
        </span>
      ) : null}
      {hint ? <span className="c-stat-hint">{hint}</span> : null}
    </div>
  );
}
