"""Parametros de mercado, en un solo lugar y con fuente.

Antes estos numeros estaban regados: la tasa libre de riesgo vivia en
`bank/seed.py`, la inflacion se guardaba en la base y no la leia nadie, y el
rendimiento de cada instrumento era un literal sin procedencia. Aqui cada
constante trae `FUENTES[...]`: de donde salio y cuando se tomo.

Distincion que importa para la auditoria:

  * **anclado** -- valor observado y con fecha. Se actualiza volviendo a
    consultar la fuente, no a ojo.
  * **estimado** -- valor calibrado a un rango plausible porque no se tomo
    lectura directa. Sigue siendo sintetico y esta marcado como tal.

Nada de esto se lee en vivo: el seed tiene que ser reproducible byte a byte
(ver `bank/db.py:SEED`). Se actualiza a mano, con fecha, y el `--check` del
seed avisa si la foto ya esta vieja.
"""

from __future__ import annotations

from datetime import date
from typing import Any, NamedTuple


class Fuente(NamedTuple):
    tipo: str            # anclado | estimado
    detalle: str
    tomado_en: date


FECHA_MERCADO = date(2026, 9, 11)

# --------------------------------------------------------------------- tasas
# Banxico dejo la tasa de referencia en 6.50% y el CETES 28d cerro septiembre
# subiendo de 6.13% a 6.49%. Todo el catalogo de deuda se reprecia sobre esto:
# antes el repo tenia CETES-28 a 7.45%, que era la foto de un ciclo anterior.
TASA_REFERENCIA = 0.0650
TASA_LIBRE_RIESGO = 0.0649          # CETES 28 dias
INFLACION_ANUAL = 0.0415

# Reversion a la media de la tasa corta (Vasicek mensual). `TASA_LARGA` es el
# nivel al que converge: el promedio de la parte larga de la curva, no la tasa
# de hoy. Sin esto, un CETES-28 se simularia como si su tasa de hoy durara
# diez anos, que es exactamente el error que hace ver a los CETES como un
# instrumento sin riesgo de reinversion.
TASA_LARGA = 0.0720
VELOCIDAD_REVERSION = 0.55          # kappa anual
VOLATILIDAD_TASA = 0.0115           # sigma anual de la tasa corta

# ------------------------------------------------------------------ acciones
IPC_NIVEL = 63_924.77
IPC_VARIACION_DIA = -0.0028
VOLATILIDAD_MERCADO = 0.155         # sigma anual del IPC
PRIMA_RIESGO_MERCADO = 0.055        # ERP Mexico sobre CETES

FUENTES: dict[str, Fuente] = {
    "IPC_NIVEL": Fuente(
        "anclado", "Cierre S&P/BMV IPC 11-sep-2026: 63,924.77 (-0.28%)", FECHA_MERCADO),
    "TASA_LIBRE_RIESGO": Fuente(
        "anclado", "CETES 28 dias septiembre 2026: 6.13% -> 6.49%", FECHA_MERCADO),
    "TASA_REFERENCIA": Fuente(
        "anclado", "Tasa objetivo Banco de Mexico: 6.50%", FECHA_MERCADO),
    "INFLACION_ANUAL": Fuente(
        "estimado", "INPC anual supuesto para el ejercicio", FECHA_MERCADO),
    "VOLATILIDAD_MERCADO": Fuente(
        "estimado", "Volatilidad anualizada tipica del IPC (rango 14-17%)", FECHA_MERCADO),
    "PRIMA_RIESGO_MERCADO": Fuente(
        "estimado", "Prima de riesgo de mercado Mexico sobre CETES (rango 5-6%)",
        FECHA_MERCADO),
    "TASA_LARGA": Fuente(
        "estimado", "Nivel de largo plazo de la tasa corta implicito en la curva",
        FECHA_MERCADO),
}

# ------------------------------------------------------------------- fiscal
# Ver bank/finance/fiscal.py. Se declaran aqui porque son parametros de
# ejercicio, igual que las tasas.
ISR_RETENCION_CAPITAL = 0.0090      # tasa anual sobre el capital que genera intereses
ISR_GANANCIA_CAPITAL = 0.10         # enajenacion de acciones en bolsa
ISR_DIVIDENDOS = 0.10

FUENTES["ISR_RETENCION_CAPITAL"] = Fuente(
    "estimado", "Tasa de retencion provisional sobre el capital (parametro LIF)",
    FECHA_MERCADO)
FUENTES["ISR_GANANCIA_CAPITAL"] = Fuente(
    "anclado", "ISR definitivo 10% sobre ganancia en enajenacion de acciones en bolsa "
               "(art. 129 LISR)", FECHA_MERCADO)
FUENTES["ISR_DIVIDENDOS"] = Fuente(
    "anclado", "Retencion 10% sobre dividendos (art. 140 LISR)", FECHA_MERCADO)


def ficha() -> dict[str, Any]:
    """Los parametros con su procedencia. Lo que se pinta en la UI de auditoria."""
    valores = {
        "TASA_REFERENCIA": TASA_REFERENCIA,
        "TASA_LIBRE_RIESGO": TASA_LIBRE_RIESGO,
        "INFLACION_ANUAL": INFLACION_ANUAL,
        "TASA_LARGA": TASA_LARGA,
        "IPC_NIVEL": IPC_NIVEL,
        "VOLATILIDAD_MERCADO": VOLATILIDAD_MERCADO,
        "PRIMA_RIESGO_MERCADO": PRIMA_RIESGO_MERCADO,
        "ISR_RETENCION_CAPITAL": ISR_RETENCION_CAPITAL,
        "ISR_GANANCIA_CAPITAL": ISR_GANANCIA_CAPITAL,
        "ISR_DIVIDENDOS": ISR_DIVIDENDOS,
    }
    return {
        "fecha_mercado": FECHA_MERCADO.isoformat(),
        "parametros": [
            {
                "clave": k,
                "valor": v,
                "tipo": FUENTES[k].tipo if k in FUENTES else "estimado",
                "fuente": FUENTES[k].detalle if k in FUENTES else "sin fuente declarada",
                "tomado_en": (FUENTES[k].tomado_en if k in FUENTES
                              else FECHA_MERCADO).isoformat(),
            }
            for k, v in valores.items()
        ],
    }


def capm(beta: float) -> float:
    """Rendimiento total esperado de un activo con esa beta.

    CAPM puro: el mercado NO paga por el riesgo idiosincratico. Por eso una
    emisora muy volatil pero de beta media (TLEVISA, por ejemplo) sale con un
    rendimiento esperado mediocre y un riesgo alto -- que es justo el argumento
    contra concentrarse en ella.
    """
    return TASA_LIBRE_RIESGO + beta * PRIMA_RIESGO_MERCADO
