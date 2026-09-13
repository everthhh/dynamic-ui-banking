// CategoryIcon — un glifo simple por categoría de gasto (ETIQUETA_CATEGORIA)
// y por categoría de servicio (ETIQUETA_SERVICIO), para que los chips de
// color en BillsPanel/SpendingBudgets/FinancialProfile no dependan solo del
// texto. Trazos a mano, mismo estilo minimal que el resto de los SVG del
// proyecto (CardVisual, ProjectionChart): sin librería de íconos externa.

import type { ReactNode } from "react";

const TRAZOS: Record<string, ReactNode> = {
  // --- gasto (bank.*) ---
  super: <path d="M3 4h2l2.4 12.2a2 2 0 0 0 2 1.8h7.2a2 2 0 0 0 2-1.6L20 8H6" />,
  restaurantes: <path d="M7 2v7a2 2 0 0 0 2 2M9 2v7M7 2v7M9 11v11M16 2c-1.8 1.8-1.8 5 0 7l1 1v10" />,
  transporte: (
    <>
      <path d="M3 13l1.5-4.5A2 2 0 0 1 6.4 7h11.2a2 2 0 0 1 1.9 1.5L21 13v5a1 1 0 0 1-1 1h-1a1 1 0 0 1-1-1v-1H6v1a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" />
      <circle cx="7.5" cy="18" r="1.4" />
      <circle cx="16.5" cy="18" r="1.4" />
    </>
  ),
  servicios: (
    <>
      <path d="M3 11l9-7 9 7" />
      <path d="M5 10v9a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1v-9" />
    </>
  ),
  renta: (
    <>
      <path d="M3 11l9-7 9 7" />
      <path d="M5 10v9a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1v-9" />
    </>
  ),
  salud: (
    <path d="M12 21s-7-4.4-9.5-8.5C1 9 2.5 5.5 6 5c2-.3 3.6.7 6 3 2.4-2.3 4-3.3 6-3 3.5.5 5 4 3.5 7.5C19 16.6 12 21 12 21z" />
  ),
  entretenimiento: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M10 8.3l6 3.7-6 3.7z" fill="currentColor" stroke="none" />
    </>
  ),
  educacion: (
    <>
      <path d="M2 6l10-4 10 4-10 4z" />
      <path d="M6 8v6c0 1.5 3 3 6 3s6-1.5 6-3V8" />
    </>
  ),
  nomina: (
    <>
      <rect x="3" y="6" width="18" height="13" rx="2" />
      <path d="M3 10h18" />
      <circle cx="16" cy="14" r="1.3" fill="currentColor" stroke="none" />
    </>
  ),
  honorarios: (
    <>
      <rect x="3" y="8" width="18" height="11" rx="2" />
      <path d="M8 8V6a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <path d="M3 13h18" />
    </>
  ),
  traspaso: (
    <>
      <path d="M4 7h12" />
      <path d="M13 3l3 4-3 4" />
      <path d="M20 17H8" />
      <path d="M11 13l-3 4 3 4" />
    </>
  ),
  inversion: (
    <>
      <path d="M3 17l6-6 4 4 7-8" />
      <path d="M15 6h5v5" />
    </>
  ),
  pago_tarjeta: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M3 10h18" />
    </>
  ),
  credito: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M3 10h18" />
    </>
  ),
  costo_financiero: (
    <>
      <circle cx="7" cy="7" r="2.1" />
      <circle cx="17" cy="17" r="2.1" />
      <path d="M18 6L6 18" />
    </>
  ),
  comisiones: (
    <>
      <circle cx="7" cy="7" r="2.1" />
      <circle cx="17" cy="17" r="2.1" />
      <path d="M18 6L6 18" />
    </>
  ),
  transferencia: (
    <>
      <path d="M4 7h12" />
      <path d="M13 3l3 4-3 4" />
      <path d="M20 17H8" />
      <path d="M11 13l-3 4 3 4" />
    </>
  ),
  efectivo: (
    <>
      <rect x="2" y="7" width="20" height="10" rx="2" />
      <circle cx="12" cy="12" r="2.4" />
    </>
  ),
  deposito: (
    <>
      <path d="M12 3v10" />
      <path d="M8 9l4 4 4-4" />
      <path d="M4 19h16" />
    </>
  ),

  // --- servicios (pay.*) ---
  luz: <path d="M13 2L4 14h7l-1 8 9-12h-7z" fill="currentColor" stroke="none" />,
  agua: <path d="M12 2S5 11 5 15.5a7 7 0 0 0 14 0C19 11 12 2 12 2z" />,
  internet: (
    <>
      <path d="M2 8.5a16 16 0 0 1 20 0" />
      <path d="M5.5 12.5a11 11 0 0 1 13 0" />
      <path d="M9 16.5a6 6 0 0 1 6 0" />
      <circle cx="12" cy="20" r="1.1" fill="currentColor" stroke="none" />
    </>
  ),
  telefonia: (
    <path d="M5 4h3l2 5-2.5 1.5a13 13 0 0 0 6 6L15 14l5 2v3a2 2 0 0 1-2 2C10.5 21 3 13.5 3 6a2 2 0 0 1 2-2z" />
  ),
  gas: (
    <path d="M12 2c1 3-3 4-3 8a4 4 0 0 0 8 0c0-1.5-1-2.5-1-2.5 1 3-1 4-2 4-1.5 0-2-1.5-1-3C14 6 12 4 12 2z" />
  ),
  television: (
    <>
      <rect x="3" y="5" width="18" height="12" rx="2" />
      <path d="M8 21h8" />
      <path d="M12 17v4" />
    </>
  ),
};

const GENERICO: ReactNode = (
  <>
    <path d="M20 12l-8 8-9-9V4h7z" />
    <circle cx="7.5" cy="7.5" r="1.2" fill="currentColor" stroke="none" />
  </>
);

export type CategoryIconProps = {
  categoria?: string | null;
  className?: string;
};

export function CategoryIcon({ categoria, className }: CategoryIconProps) {
  const trazo = (categoria && TRAZOS[categoria]) || GENERICO;
  return (
    <svg
      className={"cat-icono" + (className ? ` ${className}` : "")}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {trazo}
    </svg>
  );
}
