// Logo — ícono + wordmark, inspirado en la identidad real de Banorte que
// compartió el equipo (dos óvalos rojos formando un moño, wordmark
// "BANORTE" condensado en mayúsculas). Recreado como SVG propio: no es una
// copia del archivo oficial, es una aproximación para no depender de un
// asset externo que todavía no vive en el repo.
//
// `size="sm"` se usa dentro de la tarjeta (CardVisual); `size="md"` en el
// header de la app.

export type LogoProps = {
  size?: "sm" | "md";
  /** Verde/negro sobre fondo oscuro (ej. dentro de una tarjeta) en vez del rojo de marca. */
  sobreOscuro?: boolean;
};

export function Logo({ size = "md", sobreOscuro = false }: LogoProps) {
  const alto = size === "sm" ? 16 : 26;
  const colorIcono = sobreOscuro ? "#ffffff" : "var(--rojo)";
  const colorTexto = sobreOscuro ? "#ffffff" : "var(--rojo)";

  return (
    <span className={`logo logo-${size}`} role="img" aria-label="Banorte">
      <svg
        className="logo-icono"
        viewBox="0 0 100 100"
        height={alto}
        width={alto}
        aria-hidden="true"
      >
        <path
          d="M50 50 C20 50 10 32 19 17 C28 3 72 3 81 17 C90 32 80 50 50 50 Z"
          fill={colorIcono}
        />
        <path
          d="M50 50 C20 50 10 68 19 83 C28 97 72 97 81 83 C90 68 80 50 50 50 Z"
          fill={colorIcono}
          opacity={0.82}
        />
      </svg>
      <span className="logo-texto" style={{ color: colorTexto }}>
        BANORTE
      </span>
    </span>
  );
}
