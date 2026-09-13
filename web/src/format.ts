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
  transferencia: "Transferencias",
  efectivo: "Efectivo",
  deposito: "Depósitos",
  comisiones: "Comisiones",
};

export const ETIQUETA_SERVICIO: Record<string, string> = {
  luz: "Luz",
  agua: "Agua",
  internet: "Internet",
  telefonia: "Telefonía",
  gas: "Gas",
  television: "Televisión",
};

export const ETIQUETA_TIPO_PAGO: Record<string, string> = {
  servicio: "Pago de servicio",
  transferencia: "Transferencia",
  retiro_sin_tarjeta: "Retiro sin tarjeta",
};

export const ETIQUETA_ESTADO_PAGO: Record<string, string> = {
  pendiente: "Por confirmar",
  ejecutando: "En proceso",
  ejecutada: "Hecha",
  rechazada: "Rechazada",
  cancelada: "Cancelada",
};

export const ETIQUETA_CANAL_INGRESO: Record<string, string> = {
  nomina: "Nómina",
  spei: "SPEI recibido",
  interna: "Del mismo banco",
  deposito_efectivo: "Depósito en efectivo",
  traspaso_propio: "Entre tus cuentas",
  reembolso: "Reembolso",
  otro: "Otro",
};

// Espejo de BANCOS en bank/pagos.py, solo para decir en pantalla de qué banco
// es una CLABE mientras se teclea. Quien valida de verdad es el servidor.
export const BANCOS_SPEI: Record<string, string> = {
  "002": "BANAMEX",
  "012": "BBVA MEXICO",
  "014": "SANTANDER",
  "021": "HSBC",
  "030": "BAJIO",
  "036": "INBURSA",
  "044": "SCOTIABANK",
  "058": "BANREGIO",
  "062": "AFIRME",
  "072": "BANORTE",
  "127": "AZTECA",
  "137": "BANCOPPEL",
  "638": "NU MEXICO",
  "646": "STP",
  "722": "MERCADO PAGO W",
};

/** Dígito verificador de CLABE (pesos 3-7-1, módulo 10). Ayuda en pantalla, no candado. */
export function clabeValida(clabe: string): boolean {
  if (!/^\d{18}$/.test(clabe)) return false;
  let suma = 0;
  for (let i = 0; i < 17; i++) {
    const peso = i % 3 === 0 ? 3 : i % 3 === 1 ? 7 : 1;
    suma += (Number(clabe[i]) * peso) % 10;
  }
  return (10 - (suma % 10)) % 10 === Number(clabe[17]);
}

/** "0721 8000 0000 0000 07": una CLABE o una referencia se leen mejor en grupos. */
export function enGrupos(numero: unknown, tamano = 4): string {
  const s = String(numero ?? "");
  return s.replace(new RegExp(`(.{${tamano}})(?=.)`, "g"), "$1 ");
}

/** "04 sep". */
export function fechaCorta(iso: unknown): string {
  if (typeof iso !== "string" || !iso) return "—";
  const d = new Date(iso.length === 10 ? `${iso}T12:00:00` : iso);
  return Number.isNaN(d.getTime())
    ? iso.slice(0, 10)
    : d.toLocaleDateString("es-MX", { day: "2-digit", month: "short" });
}

/** "04 sep, 14:05". */
export function fechaHora(iso: unknown): string {
  if (typeof iso !== "string" || !iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleString("es-MX", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

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
