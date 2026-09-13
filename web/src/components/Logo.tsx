// Logo — logotipo completo de Banorte (isotipo + wordmark "BANORTE"), tal
// cual el SVG oficial que compartió el equipo: las letras son el path
// vectorial original, no texto renderizado con una fuente aproximada (ver
// assets/banorteLogotipo.ts).
//
// `size="sm"` se usa dentro de la tarjeta (CardVisual); `size="md"` en el
// header de la app.

import { LOGOTIPO_PATHS, LOGOTIPO_RATIO, LOGOTIPO_VIEWBOX } from "../assets/banorteLogotipo";

export type LogoProps = {
  size?: "sm" | "md";
  /** Blanco sobre fondo oscuro (ej. dentro de una tarjeta) en vez del rojo de marca. */
  sobreOscuro?: boolean;
};

export function Logo({ size = "md", sobreOscuro = false }: LogoProps) {
  const alto = size === "sm" ? 16 : 26;
  const ancho = Math.round(alto * LOGOTIPO_RATIO);
  const color = sobreOscuro ? "#ffffff" : "var(--rojo)";

  return (
    <svg
      className={`logo logo-${size}`}
      viewBox={LOGOTIPO_VIEWBOX}
      height={alto}
      width={ancho}
      role="img"
      aria-label="Banorte"
    >
      {LOGOTIPO_PATHS.map((d, i) => (
        <path key={i} d={d} fill={color} />
      ))}
    </svg>
  );
}
