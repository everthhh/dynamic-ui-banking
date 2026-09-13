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
  | "ask"
  | "manage_card"
  | "set_account_alias"
  | "toggle_card_block"
  | "update_card_limit"
  | "set_card_alias"
  | "set_budget"
  | "refine_search"
  | "pay_bill"
  | "add_service"
  | "register_service"
  | "prepare_transfer"
  | "prepare_withdrawal"
  | "request_deposit_reference"
  | "confirm_payment"
  | "cancel_payment"
  | "filter_history"
  | "filter_received";

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

/** Panorama de cuentas y tarjetas: saldos, alias, estado de cada tarjeta. Sustituye cualquier lista de cuentas en texto. Tocar una tarjeta pide administrarla. */
export type PropsBankAccountsOverview = {
  id: string;
  component: "bank.AccountsOverview";
  cuentas: unknown[] | Binding;
  tarjetas: unknown[] | Binding;
};

/** Administrar UNA tarjeta: bloquear/desbloquear, ajustar límite (solo crédito) y ponerle alias. Se monta después de `manage_card` desde `bank.AccountsOverview`. */
export type PropsBankCardManager = {
  id: string;
  component: "bank.CardManager";
  card: Record<string, unknown> | Binding;
  ingresoMensual: number | Binding;
};

/** Presupuestos por categoría contra el gasto real, con aviso de excedidos. Para 'control de gasto' o '¿voy bien con mi presupuesto?'. Si `alertas` viene vacío, es que el cliente no ha configurado ninguno: ofrece ponerle uno, no inventes cifras. */
export type PropsBankSpendingBudgets = {
  id: string;
  component: "bank.SpendingBudgets";
  alertas: unknown[] | Binding;
};

/** Resultados de una búsqueda de movimientos con filtros aplicados. Nunca enlistes movimientos filtrados en texto; para 'mis últimos movimientos' sin filtro considera si de plano no hace falta filtrar. */
export type PropsBankTransactionSearch = {
  id: string;
  component: "bank.TransactionSearch";
  movimientos: unknown[] | Binding;
  filtros?: Record<string, unknown> | Binding;
  resumen?: Record<string, unknown> | Binding;
};

/** Recibos por pagar: luz, agua, internet, teléfono. Para '¿qué tengo que pagar?' o 'paga mis servicios'. Cada recibo trae su botón de pagar, que solo inicia el paso 1. Nunca enlistes recibos en texto. */
export type PropsPayBillsPanel = {
  id: string;
  component: "pay.BillsPanel";
  servicios: unknown[] | Binding;
  resumen?: Record<string, unknown> | Binding;
};

/** Dar de alta un servicio: el usuario elige la empresa y teclea la referencia de su recibo, que se revisa contra el formato del convenio antes de mandarla. */
export type PropsPayServiceForm = {
  id: string;
  component: "pay.ServiceForm";
  billers: unknown[] | Binding;
  categoria?: "luz" | "agua" | "internet" | "telefonia" | "gas" | "television";
};

/** Armar una transferencia: cuenta de origen, destino (contacto guardado, CLABE nueva o cuenta propia), monto y concepto. La CLABE se revisa en pantalla con su dígito verificador. No transfiere: manda `prepare_transfer`. */
export type PropsPayTransferForm = {
  id: string;
  component: "pay.TransferForm";
  cuentas: unknown[] | Binding;
  beneficiarios: unknown[] | Binding;
  monto?: number | Binding;
  concepto?: string | Binding;
};

/** Confirmar un pago de servicio, una transferencia o un retiro sin tarjeta, y después servir de comprobante. Es el único componente de pagos que mueve dinero y exige confirmación en dos pasos. Ya ejecutado muestra folio, clave de rastreo o el código de retiro. */
export type PropsPayPaymentTicket = {
  id: string;
  component: "pay.PaymentTicket";
  payment: Record<string, unknown> | Binding;
  action: A2UIAction;
  requiresConfirmation: boolean;
  disclaimer: string;
};

/** Historial de lo que salió: servicios pagados, transferencias y retiros, con folio y estado. Para '¿qué he pagado?' o '¿ya pagué la luz?'. */
export type PropsPayPaymentHistory = {
  id: string;
  component: "pay.PaymentHistory";
  pagos: unknown[] | Binding;
  resumen?: Record<string, unknown> | Binding;
  filtro?: string | Binding;
};

/** Historial de lo que entró y quién lo mandó: nómina, SPEI, depósitos en efectivo y traspasos. Para '¿quién me depositó?' o '¿ya me pagaron?'. */
export type PropsPayReceivedMoney = {
  id: string;
  component: "pay.ReceivedMoney";
  movimientos: unknown[] | Binding;
  resumen?: Record<string, unknown> | Binding;
  filtro?: string | Binding;
};

/** Meter o sacar dinero: retiro sin tarjeta en cajero, la CLABE para que le depositen y dónde depositar efectivo con su comisión. Para 'necesito efectivo', 'no traigo tarjeta' o '¿cómo deposito?'. */
export type PropsPayCashAccess = {
  id: string;
  component: "pay.CashAccess";
  cuentas: unknown[] | Binding;
  canales: unknown[] | Binding;
  retiro: Record<string, unknown> | Binding;
  referencia?: Record<string, unknown> | Binding;
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
  | PropsInvSpendingBreakdown
  | PropsBankAccountsOverview
  | PropsBankCardManager
  | PropsBankSpendingBudgets
  | PropsBankTransactionSearch
  | PropsPayBillsPanel
  | PropsPayServiceForm
  | PropsPayTransferForm
  | PropsPayPaymentTicket
  | PropsPayPaymentHistory
  | PropsPayReceivedMoney
  | PropsPayCashAccess;

export const COMPONENT_NAMES = [
  "Column", "Row", "Card", "Text", "Divider", "Button", "Badge", "Stat", "inv.RiskProfiler", "inv.AllocationDonut", "inv.ProjectionChart", "inv.InstrumentTable", "inv.ComparePanel", "inv.AmountSlider", "inv.OrderTicket", "inv.FactSheet", "inv.PositionsTable", "inv.SpendingBreakdown", "bank.AccountsOverview", "bank.CardManager", "bank.SpendingBudgets", "bank.TransactionSearch", "pay.BillsPanel", "pay.ServiceForm", "pay.TransferForm", "pay.PaymentTicket", "pay.PaymentHistory", "pay.ReceivedMoney", "pay.CashAccess"
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
