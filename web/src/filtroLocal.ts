// Filtro de movimientos en el cliente, sin red y sin el agente.
//
// bank.TransactionSearch monta con TODO el histórico ya cacheado en
// `movimientosCompletos` (el agente lo escribe una sola vez, ver regla 8c
// del prompt). A partir de ahí, cada clic en un chip de categoría es
// cómputo puro — la misma cuenta de cargos/abonos que hace
// `services/accounts.py::search_transactions`, pero en TypeScript.

export type Movimiento = {
  txn_id?: string;
  fecha?: string;
  tipo?: "cargo" | "abono";
  monto?: number;
  categoria?: string;
  descripcion?: string;
  comercio?: string | null;
};

export type FiltroLocal = {
  categoria?: string | null;
};

export function filtrarMovimientos(movimientos: Movimiento[], filtro: FiltroLocal): Movimiento[] {
  if (!filtro.categoria) return movimientos;
  return movimientos.filter((m) => m.categoria === filtro.categoria);
}

export function resumenDe(movimientos: Movimiento[]): {
  total: number;
  total_cargos: number;
  total_abonos: number;
} {
  let cargos = 0;
  let abonos = 0;
  for (const m of movimientos) {
    const monto = Number(m.monto) || 0;
    if (m.tipo === "abono") abonos += monto;
    else cargos += monto;
  }
  return {
    total: movimientos.length,
    total_cargos: Math.round(cargos * 100) / 100,
    total_abonos: Math.round(abonos * 100) / 100,
  };
}
