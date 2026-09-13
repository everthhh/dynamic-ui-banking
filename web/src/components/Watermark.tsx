// Marca de agua del panel donde el agente monta la superficie: mismo
// isotipo que el header, en baja opacidad y fija en la esquina inferior
// derecha. Vive fuera del contenedor con scroll (ver .app-superficie-panel
// en theme.css) para quedar siempre visible sin importar cuánto se
// desplace el contenido generado, y escala con clamp() para no estorbar en
// pantallas chicas.

import { ISOTIPO_PATHS, ISOTIPO_VIEWBOX } from "../assets/banorteIsotipo";

export function Watermark() {
  return (
    <div className="marca-agua" aria-hidden="true">
      <svg viewBox={ISOTIPO_VIEWBOX} role="presentation">
        {ISOTIPO_PATHS.map((d, i) => (
          <path key={i} d={d} />
        ))}
      </svg>
    </div>
  );
}
