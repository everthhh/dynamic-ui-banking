// Formato de cifras. Vive en un solo lugar para que la pantalla no mezcle
// "9.5%" con "0.095" según qué componente la pinte.

const MXN = new Intl.NumberFormat("es-MX", {
  style: "currency",
  currency: "MXN",
  maximumFractionDigits: 0,
});

const MXN_CENTAVOS = new Intl.NumberFormat("es-MX", {
  style: "currency",
  currency: "MXN",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const PCT = new Intl.NumberFormat("es-MX", {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 2,
});

const NUM = new Intl.NumberFormat("es-MX", { maximumFractionDigits: 2 });

export function moneda(v: unknown, centavos = false): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return centavos ? MXN_CENTAVOS.format(n) : MXN.format(n);
}

/** Cifra con signo explícito: "+$1,240" / "−$310" / "$0" (sin signo si es cero). */
export function conSigno(v: unknown, formato: "moneda" | "porcentaje" = "moneda"): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  const fmt = formato === "moneda" ? moneda : porcentaje;
  if (n === 0) return fmt(0);
  return (n > 0 ? "+" : "−") + fmt(Math.abs(n));
}

export function porcentaje(v: unknown): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return PCT.format(n);
}

export function numero(v: unknown): string {
  const n = Number(v);
  return Number.isFinite(n) ? NUM.format(n) : "—";
}

export function anios(v: unknown): string {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  return n === 1 ? "1 año" : `${NUM.format(n)} años`;
}

export function porFormato(v: unknown, formato: string | undefined): string {
  switch (formato) {
    case "moneda":
      return moneda(v);
    case "porcentaje":
      return porcentaje(v);
    case "anios":
      return anios(v);
    case "texto":
      return String(v ?? "—");
    default:
      return numero(v);
  }
}

/** Cifra compacta para ejes: 1.2M, 340k. */
export function compacto(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1_000_000) return `${(v / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}M`;
  if (abs >= 1_000) return `${Math.round(v / 1_000)}k`;
  return Math.round(v).toString();
}

export const ETIQUETA_RIESGO: Record<number, string> = {
  1: "Muy bajo",
  2: "Bajo",
  3: "Medio",
  4: "Alto",
  5: "Muy alto",
};

export const ETIQUETA_LIQUIDEZ: Record<string, string> = {
  diaria: "Diaria",
  "24h": "24 horas",
  "48h": "48 horas",
  al_vencimiento: "Al vencimiento",
};

export const ETIQUETA_CATEGORIA: Record<string, string> = {
  super: "Súper",
  restaurantes: "Restaurantes",
  transporte: "Transporte",
  servicios: "Servicios del hogar",
  renta: "Renta",
  salud: "Salud",
  entretenimiento: "Entretenimiento",
  educacion: "Educación",
  nomina: "Nómina",
  traspaso: "Traspaso",
  inversion: "Inversión",
};

export const ETIQUETA_TIPO_CUENTA: Record<string, string> = {
  cheques: "Cuenta de cheques",
  ahorro: "Cuenta de ahorro",
  nomina: "Cuenta de nómina",
  inversion: "Cuenta de inversión",
};

export const ETIQUETA_CLASE: Record<string, string> = {
  deuda_gub: "Deuda gubernamental",
  deuda_corp: "Deuda corporativa",
  renta_variable: "Renta variable",
  fondo_deuda: "Fondo de deuda",
  fondo_rv: "Fondo de renta variable",
  etf: "ETF",
  pagare: "Pagaré",
  accion: "Acción BMV",
};
