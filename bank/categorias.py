"""Categorias de movimiento: que es consumo, que es esencial y que no es gasto.

Un solo lugar. Antes vivian en `services/accounts.py`, pero el perfil
financiero (`bank/finance/perfil.py`) las necesita y `bank/` no importa nada
de `services/`.
"""

from __future__ import annotations

# Las ocho categorias de consumo. Es la lista contra la que se valida
# `set_budget`: un presupuesto en una categoria que no existe no tiene con que
# compararse.
CATEGORIAS_GASTO = frozenset({
    "super", "restaurantes", "transporte", "servicios",
    "renta", "salud", "entretenimiento", "educacion",
})
CATEGORIAS_ESENCIALES = frozenset({"renta", "super", "servicios", "salud", "transporte", "educacion"})
CATEGORIAS_DISCRECIONALES = CATEGORIAS_GASTO - CATEGORIAS_ESENCIALES

CATEGORIAS_INGRESO = frozenset({"nomina", "honorarios"})

PAGO_CREDITO = "credito"              # mensualidad de un prestamo
PAGO_TARJETA = "pago_tarjeta"         # abono a la TDC: paga consumo que ya se conto
COSTO_FINANCIERO = "costo_financiero"  # intereses y comisiones de la TDC

# Movimientos que NO son consumo. Mover dinero propio no es gastar, y pagar la
# tarjeta tampoco: las compras ya se contaron cuando se hicieron. Los pagos de
# credito y el costo financiero si salen del bolsillo, pero se reportan aparte
# del consumo porque no se recortan con un presupuesto.
CATEGORIAS_NO_GASTO = frozenset({
    "traspaso", "inversion", PAGO_TARJETA, PAGO_CREDITO, COSTO_FINANCIERO,
})

ETIQUETA_CATEGORIA = {
    "super": "Súper",
    "restaurantes": "Restaurantes",
    "transporte": "Transporte",
    "servicios": "Servicios del hogar",
    "renta": "Renta",
    "salud": "Salud",
    "entretenimiento": "Entretenimiento",
    "educacion": "Educación",
}
