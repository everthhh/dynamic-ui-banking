// CardVisual — la tarjeta como tarjeta, no como fila de texto.
//
// Inspirada en la tarjeta real de Banorte que compartió el equipo: rojo con
// un patrón de zigzag, chip plateado, ícono de contactless, wordmark arriba
// a la izquierda, etiqueta de producto arriba a la derecha. Recreada en SVG
// propio — sin marca de red (Visa/Mastercard): la base de datos no tiene ese
// dato (`card_id, tipo, alias, last4, estado, limite_credito,
// saldo_utilizado`, nada de red/vigencia/titular) y una marca de pago
// inventada implicaría una afiliación que no existe. La identidad de marca
// la da el logo Banorte, no una red ficticia.
//
// Proporción real de tarjeta (ID-1, ~1.586). Overlay HTML sobre SVG, mismo
// patrón que ya usa AllocationDonut para el centro de la dona.

import { Logo } from "./Logo";
import { moneda } from "../format";

export type Tarjeta = {
  card_id?: string;
  tipo?: string;
  alias?: string | null;
  last4?: string;
  estado?: string;
  limite_credito?: number | null;
  saldo_utilizado?: number;
};

export type CardVisualProps = {
  tarjeta: Tarjeta;
  big?: boolean;
  onClick?: () => void;
};

const W = 344;
const H = 216;

// 3 tonos por tipo, elegidos determinísticamente por el id de la tarjeta —
// misma tarjeta, mismo tono siempre, sin depender de una librería de hash.
const TONOS_CREDITO: [string, string][] = [
  ["#eb0029", "#7a0016"],
  ["#c2392e", "#5c1210"],
  ["#8e1f2f", "#400a14"],
];
const TONOS_DEBITO: [string, string][] = [
  ["#16181d", "#3c4350"],
  ["#1f2430", "#4a5568"],
  ["#0f1115", "#2b303b"],
];

function hashCorto(texto: string | undefined): number {
  let h = 0;
  for (const ch of texto ?? "") h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return h;
}

export function CardVisual({ tarjeta: t, big = false, onClick }: CardVisualProps) {
  const esCredito = t.tipo === "credito";
  const bloqueada = t.estado === "bloqueada";
  const tonos = esCredito ? TONOS_CREDITO : TONOS_DEBITO;
  const [claro, oscuro] = tonos[hashCorto(t.card_id) % tonos.length]!;
  const patternId = `zigzag-${t.card_id ?? "x"}`;
  const gradId = `grad-${t.card_id ?? "x"}`;

  return (
    <div
      className={"cv" + (big ? " cv-grande" : "") + (bloqueada ? " cv-bloqueada" : "")}
      role={onClick ? "button" : undefined}
      tabIndex={onClick ? 0 : undefined}
      onClick={onClick}
      onKeyDown={(e) => {
        if (onClick && (e.key === "Enter" || e.key === " ")) onClick();
      }}
    >
      <svg className="cv-bg" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Tarjeta">
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={claro} />
            <stop offset="100%" stopColor={oscuro} />
          </linearGradient>
          <pattern
            id={patternId}
            width="28"
            height="28"
            patternUnits="userSpaceOnUse"
            patternTransform="rotate(15)"
          >
            <path
              d="M0 14 L7 0 L14 14 L21 0 L28 14 L21 28 L14 14 L7 28 Z"
              fill="#ffffff"
              opacity="0.06"
            />
          </pattern>
        </defs>
        <rect width={W} height={H} rx={16} fill={`url(#${gradId})`} />
        <rect width={W} height={H} rx={16} fill={`url(#${patternId})`} />
        {bloqueada ? <rect width={W} height={H} rx={16} fill="#0a0a0a" opacity="0.45" /> : null}

        {/* chip */}
        <g transform="translate(28,96)">
          <rect width="44" height="34" rx="6" fill="#e3c877" stroke="#b89b4a" strokeWidth="1" />
          <line x1="0" y1="11" x2="44" y2="11" stroke="#b89b4a" strokeWidth="1" />
          <line x1="0" y1="23" x2="44" y2="23" stroke="#b89b4a" strokeWidth="1" />
          <line x1="15" y1="0" x2="15" y2="34" stroke="#b89b4a" strokeWidth="1" />
          <line x1="29" y1="0" x2="29" y2="34" stroke="#b89b4a" strokeWidth="1" />
        </g>
        {/* contactless */}
        <g transform="translate(86,102)" stroke="#ffffff" strokeWidth="2.4" fill="none" opacity="0.9">
          <path d="M0 22 A22 22 0 0 1 0 -22" strokeLinecap="round" transform="translate(0,22) scale(0.9)" />
          <path d="M-8 14 A14 14 0 0 1 -8 -14" strokeLinecap="round" transform="translate(8,17) scale(0.9)" />
          <path d="M-4 7 A7 7 0 0 1 -4 -7" strokeLinecap="round" transform="translate(4,10) scale(0.9)" />
        </g>
      </svg>

      <div className="cv-overlay">
        <div className="cv-fila-arriba">
          <Logo size="sm" sobreOscuro />
          <span className="cv-etiqueta">{esCredito ? "CRÉDITO" : "DÉBITO"}</span>
        </div>

        {bloqueada ? <span className="cv-badge-bloqueada">Bloqueada</span> : null}

        <div className="cv-fila-abajo">
          <div className="cv-identidad">
            <span className="cv-alias">{t.alias || (esCredito ? "Tarjeta de crédito" : "Tarjeta de débito")}</span>
            <span className="cv-numero">•••• {t.last4 ?? "····"}</span>
          </div>
          {esCredito && t.limite_credito ? (
            <div className="cv-saldo">
              <span>Disponible</span>
              <strong>{moneda((t.limite_credito ?? 0) - (t.saldo_utilizado ?? 0))}</strong>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
