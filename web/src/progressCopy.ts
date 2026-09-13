// Traductor de la traza técnica a una línea de progreso en español llano.
//
// El panel "Qué está pasando" (`App.tsx`) se queda exactamente como está —
// es a propósito crudo para un jurado técnico. Esto es un feed ADICIONAL,
// pensado para el usuario final, que lee los MISMOS eventos que ya produce
// `store.ts::manejarEvento`/`trazar()` y los convierte en algo que alguien
// sin contexto técnico pueda leer mientras espera.
//
// Contrato de retorno (las tres formas importan):
//   - `string`  -> nueva línea a mostrar
//   - `null`    -> el turno terminó, limpiar el feed
//   - `undefined` -> este evento no dice nada nuevo al usuario, deja la
//                    línea anterior tal como está (no parpadea a "nada")

import type { EntradaTraza } from "./store";

const COPY_POR_TOOL: Record<string, string> = {
  get_client_snapshot: "Revisando tu cuenta…",
  get_accounts: "Consultando tus cuentas y tarjetas…",
  get_transactions: "Buscando tus movimientos…",
  search_transactions: "Buscando tus movimientos…",
  get_spending_summary: "Sumando tus gastos del mes…",
  get_credit_overview: "Revisando tus créditos…",
  get_budgets: "Consultando tus presupuestos…",
  get_spending_alerts: "Comparando tu gasto contra tu presupuesto…",
  set_budget: "Guardando tu presupuesto…",
  block_card: "Bloqueando tu tarjeta…",
  unblock_card: "Reactivando tu tarjeta…",
  set_card_limit: "Actualizando tu límite…",
  set_card_alias: "Guardando el apodo de tu tarjeta…",
  set_account_alias: "Guardando el apodo de tu cuenta…",
  list_instruments: "Buscando opciones para ti…",
  get_instrument_factsheet: "Consultando el detalle del instrumento…",
  get_issuer_profile: "Revisando la empresa…",
  get_fund_holdings: "Viendo en qué está invertido tu dinero…",
  get_funding_sources: "Revisando de dónde puede salir el dinero…",
  check_suitability: "Verificando que esto te convenga…",
  get_risk_questions: "Preparando tu perfil de inversionista…",
  score_risk_profile: "Calculando tu perfil de riesgo…",
  propose_allocation: "Armando una propuesta para ti…",
  simulate_portfolio: "Haciendo miles de simulaciones…",
  compare_allocations: "Comparando tus opciones…",
  place_order: "Procesando tu orden…",
  get_orders: "Buscando tus órdenes…",
};

const COPY_POR_A2UI: Record<string, string> = {
  createSurface: "Preparando tu pantalla…",
  updateComponents: "Armando tu pantalla…",
  updateDataModel: "Actualizando los datos en pantalla…",
  deleteSurface: "Cerrando esta pantalla…",
};

// Los tres tipos que produce un tool_call (ver store.ts::manejarEvento).
const TIPOS_TOOL_CALL = new Set(["tool", "tool (mueve dinero)", "tool directa (sin LLM)"]);

export function copiaAmigable(entrada: EntradaTraza | undefined): string | null | undefined {
  if (!entrada) return undefined;
  const { tipo, detalle } = entrada;

  if (tipo === "turno listo") return null;              // limpia el feed
  if (TIPOS_TOOL_CALL.has(tipo)) return COPY_POR_TOOL[detalle] ?? "Trabajando en tu respuesta…";
  if (tipo in COPY_POR_A2UI) return COPY_POR_A2UI[tipo];
  if (tipo === "blueprint rechazado") return "Ajustando los últimos detalles…"; // tranquilizador, no alarmante

  // Resultados de tool ("tool ok"/"tool error"/"tool directa ok"), avisos,
  // reenvíos de acción, etc.: no aportan una línea nueva — se deja la
  // anterior tal cual en vez de parpadear a un texto crudo.
  return undefined;
}
