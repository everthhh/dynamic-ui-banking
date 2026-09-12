// GENERADO por scripts/gen_catalog_artifacts.py desde a2ui/catalog.json. No editar a mano.

export const CATALOG_ID = "https://dynamic-ui-banking.local/a2ui/inv/v1/catalog.json";
export const A2UI_VERSION = "v0.9";

export type Binding = { path: string };

export type ActionName =
  | "profile_done"
  | "simulate"
  | "compare"
  | "select_allocation"
  | "select_instrument"
  | "place_order"
  | "cancel_order"
  | "ask";

// Spec A2UI v0.9 (common_types.json#/$defs/Action): el prop `action` de un
// componente dispara un evento de servidor. `functionCall` no aplica: este
// catálogo no declara funciones de cliente.
export type A2UIAction = {
  event: { name: ActionName; context?: Record<string, unknown> };
};

/** Apilar cosas verticalmente. Es la raíz habitual de una superficie. */
export type PropsColumn = {
  id: string;
  component: "Column";
  children?: string[];
  gap?: number;
  align?: "start" | "center" | "end" | "stretch";
};

/** Poner cosas lado a lado. Colapsa a columna en pantalla angosta. */
export type PropsRow = {
  id: string;
  component: "Row";
  children?: string[];
  gap?: number;
  align?: "start" | "center" | "end" | "baseline";
  wrap?: boolean;
};

/** Agrupar un bloque con título. No la uses para envolver un solo Text. */
export type PropsCard = {
  id: string;
  component: "Card";
  children?: string[];
  title?: string | Binding;
  subtitle?: string | Binding;
  tone?: "neutral" | "info" | "warning" | "danger";
};

/** Texto. Un párrafo corto, un encabezado, una aclaración. */
export type PropsText = {
  id: string;
  component: "Text";
  text: string | Binding;
  variant?: "h1" | "h2" | "h3" | "body" | "caption";
  tone?: "default" | "muted" | "positive" | "negative";
};

/** Separar dos bloques cuando el espacio no alcanza. */
export type PropsDivider = {
  id: string;
  component: "Divider";
};

/** Una acción que el usuario puede tomar. Siempre lleva `action`. */
export type PropsButton = {
  id: string;
  component: "Button";
  label: string;
  action: A2UIAction;
  variant?: "primary" | "secondary" | "ghost";
  disabled?: boolean | Binding;
};

/** Etiqueta corta de estado: 'Moderado', 'Ejecutada', 'Simulado'. */
export type PropsBadge = {
  id: string;
  component: "Badge";
  label: string | Binding;
  tone?: "neutral" | "info" | "positive" | "warning" | "danger";
};

/** Una cifra sola con su etiqueta. Tres o cuatro en un Row leen mejor que un párrafo. */
export type PropsStat = {
  id: string;
  component: "Stat";
  label: string;
  value: number | Binding;
  format?: "moneda" | "porcentaje" | "numero" | "texto";
  delta?: number | Binding;
  hint?: string;
};

/** Falta contexto para poder proponer: el cliente no tiene perfil vigente. Preguntar con este componente, NO con texto. */
export type PropsInvRiskProfiler = {
  id: string;
  component: "inv.RiskProfiler";
  questions: unknown[] | Binding;
  value?: Record<string, unknown> | Binding;
  action: A2UIAction;
  intro?: string;
};

/** Mostrar o ajustar una propuesta de asignación. Sustituye cualquier lista de porcentajes en texto. */
export type PropsInvAllocationDonut = {
  id: string;
  component: "inv.AllocationDonut";
  slices: unknown[] | Binding;
  total: number | Binding;
  editable?: boolean;
  action?: A2UIAction;
  subtitulo?: string | Binding;
};

/** Responder '¿cuánto voy a tener?'. Siempre con los tres escenarios, nunca con un número solo. */
export type PropsInvProjectionChart = {
  id: string;
  component: "inv.ProjectionChart";
  scenarios: Record<string, unknown> | Binding;
  horizonYears: number | Binding;
  aportado?: number | Binding;
  disclaimer: string;
  resaltar?: "p10" | "p50" | "p90";
};

/** Explorar el catálogo. Nunca enlistes instrumentos en texto. */
export type PropsInvInstrumentTable = {
  id: string;
  component: "inv.InstrumentTable";
  rows: unknown[] | Binding;
  columns: unknown[];
  selectable?: boolean;
  action?: A2UIAction;
};

/** El usuario pregunta '¿qué conviene más?' o '¿y si...?'. Dos columnas, mismas métricas. */
export type PropsInvComparePanel = {
  id: string;
  component: "inv.ComparePanel";
  left: Record<string, unknown> | Binding;
  right: Record<string, unknown> | Binding;
  metrics: unknown[] | Binding;
  action?: A2UIAction;
  disclaimer: string;
};

/** Dejar que el usuario simule variaciones. Mover el slider NO remonta componentes: dispara updateDataModel. */
export type PropsInvAmountSlider = {
  id: string;
  component: "inv.AmountSlider";
  label: string;
  value: number | Binding;
  min: number;
  max: number;
  step?: number;
  format?: "moneda" | "porcentaje" | "numero" | "anios";
  action: A2UIAction;
};

/** Ejecutar. Es el único componente que mueve dinero y exige confirmación en dos pasos. */
export type PropsInvOrderTicket = {
  id: string;
  component: "inv.OrderTicket";
  order: Record<string, unknown> | Binding;
  action: A2UIAction;
  requiresConfirmation: boolean;
  disclaimer: string;
};

/** El usuario pidió el detalle de un instrumento concreto. */
export type PropsInvFactSheet = {
  id: string;
  component: "inv.FactSheet";
  instrument: Record<string, unknown> | Binding;
  mostrarHistoria?: boolean;
};

/** Después de ejecutar, o cuando el usuario pregunta '¿cómo voy?'. Es el estado de cuenta. */
export type PropsInvPositionsTable = {
  id: string;
  component: "inv.PositionsTable";
  positions: unknown[] | Binding;
  resumen?: Record<string, unknown> | Binding;
  action?: A2UIAction;
};

/** Justificar de dónde sale la capacidad de ahorro, o responder sobre gasto. */
export type PropsInvSpendingBreakdown = {
  id: string;
  component: "inv.SpendingBreakdown";
  categorias: unknown[] | Binding;
  capacidadAhorro: number | Binding;
  ingresoMensual: number | Binding;
};

export type AnyComponent =
  | PropsColumn
  | PropsRow
  | PropsCard
  | PropsText
  | PropsDivider
  | PropsButton
  | PropsBadge
  | PropsStat
  | PropsInvRiskProfiler
  | PropsInvAllocationDonut
  | PropsInvProjectionChart
  | PropsInvInstrumentTable
  | PropsInvComparePanel
  | PropsInvAmountSlider
  | PropsInvOrderTicket
  | PropsInvFactSheet
  | PropsInvPositionsTable
  | PropsInvSpendingBreakdown;

export const COMPONENT_NAMES = [
  "Column", "Row", "Card", "Text", "Divider", "Button", "Badge", "Stat", "inv.RiskProfiler", "inv.AllocationDonut", "inv.ProjectionChart", "inv.InstrumentTable", "inv.ComparePanel", "inv.AmountSlider", "inv.OrderTicket", "inv.FactSheet", "inv.PositionsTable", "inv.SpendingBreakdown"
] as const;

export type ComponentName = (typeof COMPONENT_NAMES)[number];

export const THEME = {
  "primaryColor": "#EB0029",
  "surface": "#FFFFFF",
  "text": "#1A1A1A",
  "muted": "#6B7280",
  "positive": "#067647",
  "negative": "#B42318",
  "radius": 12,
  "fontFamily": "Inter, system-ui, sans-serif"
} as const;
