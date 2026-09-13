"""Planes para liquidar una tarjeta: cuanto tarda y cuanto cuesta en intereses.

La pregunta que contesta es la que un cliente revolvente nunca se hace en
numeros: «si sigo pagando el minimo, ¿cuando termino y cuanto le regalo al
banco?». Se compara un pago fijo contra la regla del pago minimo que usa el
propio banco (`bank/comportamiento.py`), asi que el escenario «solo el
minimo» es el mismo que genero el historial del cliente.

Supuesto declarado: no hay compras nuevas mientras se liquida. Es el caso
optimista; con compras nuevas el plan tarda mas.
"""

from __future__ import annotations

from typing import Any

from bank.comportamiento import PAGO_MINIMO_PCT, PAGO_MINIMO_PISO

MAX_MESES = 600


class PlanInvalido(ValueError):
    pass


def pago_para_liquidar(saldo: float, tasa_anual: float, meses: int) -> float:
    """Pago fijo mensual que deja la deuda en cero en `meses`."""
    if meses <= 0:
        raise PlanInvalido("el plazo debe ser de al menos un mes")
    i = tasa_anual / 12
    if i == 0:
        return saldo / meses
    return saldo * i / (1 - (1 + i) ** -meses)


def _correr(saldo: float, tasa_anual: float, pago_del_mes) -> dict[str, Any]:
    i = tasa_anual / 12
    restante = saldo
    intereses = pagado = 0.0
    serie = [{"mes": 0, "saldo": round(saldo, 2)}]
    primer_pago: float | None = None
    mes = 0
    while restante > 0.005 and mes < MAX_MESES:
        mes += 1
        interes = restante * i
        pago = min(pago_del_mes(restante, interes), restante + interes)
        if primer_pago is None:
            primer_pago = pago
        restante = restante + interes - pago
        intereses += interes
        pagado += pago
        serie.append({"mes": mes, "saldo": round(max(0.0, restante), 2)})
    return {
        "meses": mes,
        "liquidada": restante <= 0.005,
        "pago_inicial": round(primer_pago or 0.0, 2),
        "total_intereses": round(intereses, 2),
        "total_pagado": round(pagado, 2),
        "serie": serie,
    }


def plan_pago_fijo(saldo: float, tasa_anual: float, pago_mensual: float) -> dict[str, Any]:
    if saldo <= 0:
        raise PlanInvalido("la tarjeta no tiene saldo que liquidar")
    interes_inicial = saldo * tasa_anual / 12
    if pago_mensual <= interes_inicial:
        raise PlanInvalido(
            f"con ${pago_mensual:,.0f} al mes no alcanza ni para los intereses del primer "
            f"mes (${interes_inicial:,.0f}): la deuda nunca baja")
    plan = _correr(saldo, tasa_anual, lambda _restante, _interes: pago_mensual)
    return {"pago_mensual": round(pago_mensual, 2), **plan}


def plan_pago_minimo(saldo: float, tasa_anual: float) -> dict[str, Any]:
    """Pagar exactamente el minimo cada mes: 5% del saldo mas intereses, con piso."""
    if saldo <= 0:
        raise PlanInvalido("la tarjeta no tiene saldo que liquidar")
    return _correr(saldo, tasa_anual,
                   lambda restante, interes: max(PAGO_MINIMO_PISO,
                                                 restante * PAGO_MINIMO_PCT + interes))
