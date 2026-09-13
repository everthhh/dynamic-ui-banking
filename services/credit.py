"""Planes para liquidar una tarjeta de credito.

Es la herramienta `plan_pago_tarjeta` del catalogo de recomendaciones: la que
convierte «pagas el minimo» en «pagando X al mes terminas en 12 meses y te
ahorras Y de intereses». El calculo esta en `bank/finance/deuda.py`.
"""

from __future__ import annotations

from typing import Any

from bank import db
from bank.finance import deuda
from services.accounts import _exigir_cliente
from services.banking import _exigir_tarjeta_del_cliente
from services.errors import NotFound, ServiceError

MESES_POR_DEFECTO = 12


def simulate_debt_payoff(
    client_id: str,
    card_id: str | None = None,
    pago_mensual: float | None = None,
    meses_objetivo: int | None = None,
) -> dict[str, Any]:
    """Plan de pago fijo contra pagar solo el mínimo, sobre el saldo real de la tarjeta."""
    if pago_mensual is not None and meses_objetivo is not None:
        raise ServiceError(
            "Pasa `pago_mensual` o `meses_objetivo`, no los dos.",
            sugerencia="Con `meses_objetivo` calculo el pago; con `pago_mensual`, el plazo.")
    if meses_objetivo is not None and not 1 <= meses_objetivo <= 120:
        raise ServiceError("`meses_objetivo` debe estar entre 1 y 120.")
    if pago_mensual is not None and pago_mensual <= 0:
        raise ServiceError("`pago_mensual` debe ser mayor que cero.")

    with db.session(readonly=True) as conn:
        _exigir_cliente(conn, client_id)
        if card_id is None:
            tarjeta = db.query_one(
                conn, "SELECT * FROM cards WHERE client_id = ? AND tipo = 'credito'"
                      " ORDER BY saldo_utilizado DESC LIMIT 1", (client_id,))
            if tarjeta is None:
                raise NotFound(f"{client_id} no tiene tarjeta de crédito.")
        else:
            tarjeta = _exigir_tarjeta_del_cliente(conn, client_id, card_id)
        efectivo = db.query_one(
            conn, "SELECT COALESCE(SUM(saldo_disponible), 0) s FROM accounts WHERE client_id = ?",
            (client_id,))["s"]

    if tarjeta["tipo"] != "credito":
        raise ServiceError(f"La tarjeta {tarjeta['card_id']!r} es de débito: no tiene deuda.")

    saldo = float(tarjeta["saldo_utilizado"])
    tasa = float(tarjeta["tasa_anual"] or 0)
    ficha = {"card_id": tarjeta["card_id"], "last4": tarjeta["last4"],
             "saldo": round(saldo, 2), "tasa_anual": tasa,
             "limite_credito": tarjeta["limite_credito"]}
    if saldo <= 0.5:
        return {"client_id": client_id, "tarjeta": ficha, "sin_deuda": True,
                "nota": "La tarjeta no tiene saldo: no hay nada que liquidar."}

    if pago_mensual is None:
        pago_mensual = deuda.pago_para_liquidar(saldo, tasa, meses_objetivo or MESES_POR_DEFECTO)
    try:
        plan = deuda.plan_pago_fijo(saldo, tasa, pago_mensual)
    except deuda.PlanInvalido as exc:
        raise ServiceError(
            str(exc),
            sugerencia=f"Para liquidarla en 36 meses paga "
                       f"${deuda.pago_para_liquidar(saldo, tasa, 36):,.0f} al mes.") from exc
    minimo = deuda.plan_pago_minimo(saldo, tasa)

    return {
        "client_id": client_id,
        "sin_deuda": False,
        "tarjeta": ficha,
        "plan": plan,
        "solo_minimo": {k: minimo[k] for k in ("pago_inicial", "meses", "total_intereses",
                                               "total_pagado", "liquidada")},
        "ahorro_intereses": round(max(0.0, minimo["total_intereses"] - plan["total_intereses"]), 2),
        "meses_menos": minimo["meses"] - plan["meses"],
        "efectivo_en_cuentas": round(float(efectivo), 2),
        "alcanza_con_efectivo": float(efectivo) >= saldo,
        "supuesto": ("Sin compras nuevas mientras se liquida. Mínimo = 5% del saldo más "
                     "intereses, con piso de $300."),
        "disclaimer": "Cálculo sobre datos sintéticos. No constituye asesoría financiera.",
    }
