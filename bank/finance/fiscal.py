"""Regimen fiscal mexicano aplicado a la simulacion.

Antes la proyeccion era bruta: el numero que veia el cliente era el que nunca
iba a recibir. Aqui se modelan los tres impuestos que de verdad pegan a una
persona fisica:

  1. **Retencion sobre intereses.** No se cobra sobre lo que ganas, se cobra
     sobre el CAPITAL invertido (parametro anual de la LIF, prorrateado al
     mes). Por eso duele tanto en instrumentos de tasa baja: un pagare al 5.15%
     con retencion sobre capital del 0.90% pierde casi un quinto del
     rendimiento antes de contar inflacion.
  2. **ISR sobre ganancia de capital**, 10% definitivo al vender acciones o
     ETFs en bolsa (art. 129 LISR). Se cobra al final y solo si hubo ganancia.
  3. **Retencion sobre dividendos**, 10% (art. 140 LISR). Se modela como un
     arrastre continuo proporcional al dividend yield de cada emisora.

Simplificaciones declaradas: no hay deduccion de perdidas contra ganancias de
ejercicios anteriores, no se acredita el interes real negativo, y no se aplica
la exencion por enajenacion de casa habitacion ni ningun regimen especial.
"""

from __future__ import annotations

from typing import Any, Mapping

from bank.mercado import (
    ISR_DIVIDENDOS,
    ISR_GANANCIA_CAPITAL,
    ISR_RETENCION_CAPITAL,
)

# clase de activo -> regimen. `interes` retiene sobre capital mes a mes;
# `capital` paga 10% sobre la ganancia al momento de vender.
REGIMEN_POR_CLASE: dict[str, str] = {
    "deuda_gub": "interes",
    "pagare": "interes",
    "fondo_deuda": "interes",
    "deuda_corp": "interes",
    "fondo_rv": "capital",
    "etf": "capital",
    "renta_variable": "capital",
}

ETIQUETA_REGIMEN = {
    "interes": "Retención sobre el capital (intereses)",
    "capital": "ISR 10% sobre la ganancia al vender",
}


def regimen_de(instrument_id: str) -> str:
    from bank.instrumentos import BY_ID
    return REGIMEN_POR_CLASE[BY_ID[instrument_id].clase]


def retencion_mensual_capital() -> float:
    """Fraccion del capital que se retiene cada mes en la parte de intereses."""
    return ISR_RETENCION_CAPITAL / 12


def arrastre_dividendos(instrument_id: str) -> float:
    """Costo anual del ISR sobre los dividendos que cobra el fondo.

    Un fondo de renta variable recibe los dividendos de las empresas que
    tiene y sobre esos se retiene ISR antes de que lleguen al cliente. El
    dividend yield del fondo se calcula desde sus tenencias, asi que este
    arrastre tambien sale de las empresas, no de un numero tecleado.

    Los fondos sin desglose (internacionales) se modelan como de acumulacion:
    su dividendo ya viene dentro del rendimiento total declarado.
    """
    from bank import carteras
    if not carteras.tiene_desglose(instrument_id):
        return 0.0
    return carteras.dividend_yield(instrument_id) * ISR_DIVIDENDOS


def isr_ganancia_capital(ganancia: float) -> float:
    """10% definitivo, solo sobre ganancia positiva. Una perdida no da credito."""
    return max(0.0, ganancia) * ISR_GANANCIA_CAPITAL


def desglose(asignacion: Mapping[str, float]) -> dict[str, Any]:
    """Como se reparte el portafolio entre los dos regimenes y cuanto cuesta."""
    total = sum(asignacion.values()) or 1.0
    peso_interes = sum(
        w for iid, w in asignacion.items() if regimen_de(iid) == "interes") / total
    peso_capital = 1.0 - peso_interes
    drag_div = sum(
        w / total * arrastre_dividendos(iid) for iid, w in asignacion.items())
    return {
        "peso_interes": round(peso_interes, 6),
        "peso_capital": round(peso_capital, 6),
        "retencion_anual_sobre_capital": ISR_RETENCION_CAPITAL,
        "retencion_efectiva_anual": round(peso_interes * ISR_RETENCION_CAPITAL, 6),
        "isr_ganancia_capital": ISR_GANANCIA_CAPITAL,
        "arrastre_dividendos_anual": round(drag_div, 6),
        "nota": (
            "La retención de intereses se cobra sobre el capital, no sobre la "
            "ganancia: se paga aunque el instrumento pierda. El 10% de ganancia "
            "de capital solo se paga si vendes con utilidad."
        ),
    }
