"""Perfil financiero y recomendaciones del cliente.

Aqui vive la lectura; el calculo esta en `bank/finance/perfil.py` y
`bank/finance/recomendaciones.py`. Este modulo junta lo que el banco tiene del
cliente -- 12 meses de movimientos, estados de cuenta de tarjeta, creditos,
saldos, posiciones y perfil de riesgo -- y se lo pasa al motor.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from bank import db
from bank.finance import perfil as perfil_mod
from bank.finance import recomendaciones as recomendaciones_mod
from services.accounts import _exigir_cliente, _fecha_valuacion
from services.errors import ServiceError

DISCLAIMER = (
    "Perfil y recomendaciones calculados por reglas sobre datos sintéticos. "
    "No constituyen asesoría financiera ni de inversión."
)

# Que tools de servicio resuelven cada herramienta del catalogo. Una
# herramienta sin tools es una que el banco todavia no construye.
TOOLS_POR_HERRAMIENTA: dict[str, tuple[str, ...]] = {
    "perfilador_inversion": ("get_risk_questions", "score_risk_profile"),
    "propuesta_inversion": ("propose_allocation", "simulate_portfolio", "check_suitability"),
    "simulador_aportaciones": ("propose_allocation", "simulate_portfolio"),
    "comparador_portafolios": ("propose_allocation", "compare_allocations"),
    "presupuestos": ("get_spending_alerts", "set_budget"),
    "analisis_gasto": ("get_spending_summary", "search_transactions"),
    "buscador_movimientos": ("search_transactions",),
    "control_tarjetas": ("get_accounts", "set_card_limit", "block_card"),
    "plan_pago_tarjeta": ("simulate_debt_payoff", "get_credit_overview", "get_funding_sources"),
    "domiciliacion_pago": (),
    "refinanciamiento": (),
}


def _datos_del_cliente(client_id: str) -> dict[str, Any]:
    with db.session(readonly=True) as conn:
        cliente = _exigir_cliente(conn, client_id)
        hoy = _fecha_valuacion(conn)
        desde = perfil_mod.meses_de_ventana(hoy)[0] + "-01"
        cuentas = db.query(
            conn, "SELECT account_id, tipo, alias, saldo_disponible FROM accounts"
                  " WHERE client_id = ? ORDER BY account_id", (client_id,))
        tarjetas = db.query(
            conn, "SELECT card_id, tipo, alias, last4, estado, limite_credito, saldo_utilizado,"
                  " tasa_anual FROM cards WHERE client_id = ? ORDER BY card_id", (client_id,))
        prestamos = db.query(
            conn, "SELECT loan_id, producto, saldo_insoluto, tasa_anual, plazo_meses,"
                  " pago_mensual, mensualidades_pagadas FROM loans WHERE client_id = ?",
            (client_id,))
        movimientos = db.query(
            conn, "SELECT t.fecha, t.tipo, t.monto, t.categoria, t.descripcion, t.comercio,"
                  " t.card_id FROM transactions t JOIN accounts a USING (account_id)"
                  " WHERE a.client_id = ? AND t.fecha >= ? AND t.fecha < ? ORDER BY t.fecha",
            (client_id, desde, hoy.isoformat()))
        estados = db.query(
            conn, "SELECT card_id, fecha_corte, fecha_limite_pago, saldo_al_corte, pago_minimo,"
                  " pagado, fecha_pago, dias_atraso, intereses, comisiones"
                  " FROM card_statements WHERE client_id = ? AND fecha_corte >= ?"
                  " ORDER BY fecha_corte", (client_id, desde))
        presupuestos = db.query(
            conn, "SELECT categoria, monto_mensual FROM budgets WHERE client_id = ?"
                  " ORDER BY categoria", (client_id,))
        fila_perfil = db.query_one(
            conn, "SELECT score, perfil, horizonte_meses, respondido_en, vigente_hasta"
                  " FROM risk_profiles WHERE client_id = ?"
                  " ORDER BY respondido_en DESC LIMIT 1", (client_id,))
        posiciones = db.query(
            conn, "SELECT p.instrument_id, i.nombre, i.clase, i.liquidez, i.rend_esperado_anual,"
                  "       p.titulos, p.costo_promedio,"
                  "       (SELECT valor_unitario FROM instrument_series s"
                  "         WHERE s.instrument_id = p.instrument_id"
                  "         ORDER BY s.fecha DESC LIMIT 1) AS valor_actual"
                  "  FROM positions p JOIN instruments i USING (instrument_id)"
                  " WHERE p.client_id = ? ORDER BY p.instrument_id", (client_id,))

    perfil_riesgo = None
    if fila_perfil:
        perfil_riesgo = {**fila_perfil,
                         "vigente": date.fromisoformat(fila_perfil["vigente_hasta"]) >= hoy}
    return {
        "cliente": cliente,
        "cuentas": cuentas,
        "tarjetas": tarjetas,
        "prestamos": prestamos,
        "movimientos": movimientos,
        "estados_cuenta": estados,
        "presupuestos": presupuestos,
        "perfil_riesgo": perfil_riesgo,
        "posiciones": [
            {"instrument_id": p["instrument_id"], "instrumento": p["nombre"],
             "clase": p["clase"], "liquidez": p["liquidez"],
             "rend_esperado_anual": p["rend_esperado_anual"],
             "costo_total": round(p["titulos"] * p["costo_promedio"], 2),
             "valor_mercado": round(p["titulos"] * p["valor_actual"], 2)}
            for p in posiciones
        ],
        "fecha_valuacion": hoy,
    }


def _herramienta_con_tools(herramienta: dict[str, Any]) -> dict[str, Any]:
    return {**herramienta,
            "tools": list(TOOLS_POR_HERRAMIENTA.get(herramienta["herramienta_id"], ()))}


def get_financial_profile(client_id: str) -> dict[str, Any]:
    """Perfil financiero calculado: flujo, consumo, crédito, liquidez, inversión y rasgos."""
    perfil = perfil_mod.construir_perfil(**_datos_del_cliente(client_id))
    perfil["disclaimer"] = DISCLAIMER
    return perfil


def perfil_y_recomendaciones(client_id: str, limite: int = 5) -> tuple[dict[str, Any], dict[str, Any]]:
    """Las dos cosas con una sola lectura de la base. Lo usa el tablero inicial."""
    if not 1 <= limite <= 20:
        raise ServiceError("`limite` debe estar entre 1 y 20.")
    perfil = perfil_mod.construir_perfil(**_datos_del_cliente(client_id))
    perfil["disclaimer"] = DISCLAIMER
    todas = recomendaciones_mod.recomendar(perfil)
    for r in todas:
        r["herramienta"] = _herramienta_con_tools(r["herramienta"])
    return perfil, {
        "client_id": client_id,
        "fecha_valuacion": perfil["fecha_valuacion"],
        "resumen": perfil["resumen"],
        "salud_financiera": {k: perfil["salud_financiera"][k] for k in ("score", "nivel")},
        "recomendaciones": todas[:limite],
        "total_detectadas": len(todas),
        "criterio_prioridad": recomendaciones_mod.CRITERIO_PRIORIDAD,
        "disclaimer": DISCLAIMER,
    }


def get_recommendations(client_id: str, limite: int = 5) -> dict[str, Any]:
    """Recomendaciones priorizadas, cada una con evidencia, impacto y herramienta."""
    return perfil_y_recomendaciones(client_id, limite)[1]
