"""Catalogo de los 24 instrumentos que el cliente puede contratar.

Esto es un producto de FONDOS. Aqui no hay acciones sueltas: el cliente no
compra WALMEX, compra un fondo que tiene WALMEX adentro. Las 15 emisoras de
la BMV viven en `bank/emisoras.py` y entran al catalogo por debajo, como
tenencias de los fondos (`bank/carteras.py`), no como algo comprable.

Los rendimientos estan repreciados sobre la curva real de septiembre 2026
(`bank/mercado.py`): CETES 28d en 6.49%, no el 7.45% de un ciclo anterior.

Dos de los instrumentos --`NAFTRAC` y `FND-RV-MX`-- NO traen su riesgo
escrito a mano: su volatilidad, su rendimiento esperado y su `riesgo_1a5`
salen de las empresas que tienen dentro y de como se mueven entre si. Si una
emisora se deteriora, el fondo que la trae sube de riesgo solo. Ver
`_derivar_de_cartera` al final del archivo.

Las cifras son las que el resto del sistema usa como verdad: el generador de
series las respeta y el Monte Carlo tambien.
"""

from __future__ import annotations

from typing import NamedTuple

from bank import carteras
from bank.mercado import TASA_LIBRE_RIESGO


class Instrumento(NamedTuple):
    instrument_id: str
    nombre: str
    clase: str
    emisor: str
    rend_esperado_anual: float
    volatilidad_anual: float
    comision_anual: float
    plazo_dias: int | None
    liquidez: str
    monto_minimo: float
    riesgo_1a5: int
    descripcion: str
    moneda: str = "MXN"


# ---------------------------------------------------------------------------
# Deuda, fondos y ETFs. Repreciados sobre CETES 28d = 6.49% (sep-2026).
# ---------------------------------------------------------------------------
INSTRUMENTOS_BASE: tuple[Instrumento, ...] = (
    # ---------------------------------------------------------- deuda gubernamental
    Instrumento("CETES-28", "CETES 28 días", "deuda_gub", "Gobierno Federal (sim)",
                0.0649, 0.006, 0.0, 28, "al_vencimiento", 100, 1,
                "Deuda gubernamental a 28 días. El piso de riesgo del catálogo. "
                "Se renueva cada mes a la tasa que haya en ese momento."),
    Instrumento("CETES-91", "CETES 91 días", "deuda_gub", "Gobierno Federal (sim)",
                0.0662, 0.009, 0.0, 91, "al_vencimiento", 100, 1,
                "CETES a 91 días. Rendimiento ligeramente mayor, menos liquidez."),
    Instrumento("CETES-182", "CETES 182 días", "deuda_gub", "Gobierno Federal (sim)",
                0.0678, 0.012, 0.0, 182, "al_vencimiento", 100, 1,
                "CETES a medio año. Para dinero con fecha conocida."),
    Instrumento("CETES-364", "CETES 364 días", "deuda_gub", "Gobierno Federal (sim)",
                0.0695, 0.018, 0.0, 364, "al_vencimiento", 100, 1,
                "CETES a un año. Fija la tasa por 12 meses."),
    Instrumento("BONDESF-3A", "BONDES F 3 años", "deuda_gub", "Gobierno Federal (sim)",
                0.0710, 0.024, 0.0, 1095, "48h", 1_000, 2,
                "Tasa revisable. Amortigua movimientos de la tasa de referencia."),
    Instrumento("BONOSM-3A", "Bono M 3 años", "deuda_gub", "Gobierno Federal (sim)",
                0.0745, 0.045, 0.0, 1095, "48h", 1_000, 2,
                "Tasa fija a 3 años. Gana si las tasas bajan, pierde si suben."),
    Instrumento("BONOSM-10A", "Bono M 10 años", "deuda_gub", "Gobierno Federal (sim)",
                0.0820, 0.080, 0.0, 3650, "48h", 1_000, 3,
                "Tasa fija larga. Sensible a tasas; no es para plazos cortos."),
    Instrumento("UDIBONO-10A", "UDIBONO 10 años", "deuda_gub", "Gobierno Federal (sim)",
                0.0785, 0.070, 0.0, 3650, "48h", 1_000, 3,
                "Indexado a la inflación. Protege el poder de compra a largo plazo."),

    # --------------------------------------------------------------------- pagares
    Instrumento("PAGARE-28", "Pagaré 28 días", "pagare", "Banco (sim)",
                0.0515, 0.002, 0.0, 28, "al_vencimiento", 1_000, 1,
                "Pagaré bancario a 28 días. Capital garantizado, rendimiento bajo."),
    Instrumento("PAGARE-91", "Pagaré 91 días", "pagare", "Banco (sim)",
                0.0580, 0.002, 0.0, 91, "al_vencimiento", 5_000, 1,
                "Pagaré a 91 días. Sin acceso al dinero hasta el vencimiento."),
    Instrumento("PAGARE-180", "Pagaré 180 días", "pagare", "Banco (sim)",
                0.0625, 0.002, 0.0, 180, "al_vencimiento", 10_000, 1,
                "Pagaré a 6 meses. Tasa fija conocida desde el día uno."),
    Instrumento("PAGARE-360", "Pagaré 360 días", "pagare", "Banco (sim)",
                0.0665, 0.002, 0.0, 360, "al_vencimiento", 25_000, 1,
                "Pagaré a un año. El más alto de la familia, el menos líquido."),

    # --------------------------------------------------------------- fondos deuda
    Instrumento("FND-GUB-CP", "Fondo deuda gubernamental corto plazo", "fondo_deuda",
                "Operadora (sim)", 0.0635, 0.010, 0.0065, None, "diaria", 1_000, 1,
                "Liquidez diaria con rendimiento de mercado de dinero. El «cajón» del portafolio."),
    Instrumento("FND-GUB-LP", "Fondo deuda gubernamental largo plazo", "fondo_deuda",
                "Operadora (sim)", 0.0715, 0.032, 0.0085, None, "24h", 1_000, 2,
                "Duración media. Más rendimiento que el de corto plazo, con vaivenes."),
    Instrumento("FND-CORP-AAA", "Fondo deuda corporativa AAA", "fondo_deuda",
                "Operadora (sim)", 0.0765, 0.040, 0.0095, None, "48h", 5_000, 2,
                "Deuda de empresas con la mejor calificación. Sobretasa sobre gubernamental."),
    Instrumento("CORP-AAA-5A", "Bono corporativo AAA 5 años", "deuda_corp",
                "Corporativo (sim)", 0.0815, 0.055, 0.0, 1825, "48h", 100_000, 3,
                "Emisión directa. Mejor tasa, menos liquidez y riesgo de crédito."),
    Instrumento("CORP-AA-7A", "Bono corporativo AA 7 años", "deuda_corp",
                "Corporativo (sim)", 0.0885, 0.075, 0.0, 2555, "48h", 100_000, 3,
                "Un escalón abajo en calificación. La sobretasa paga ese riesgo."),

    # --------------------------------------------------------- renta variable
    Instrumento("FND-RV-MX", "Fondo renta variable México", "fondo_rv",
                "Operadora (sim)", 0.1199, 0.160, 0.0135, None, "48h", 5_000, 4,
                "Acciones mexicanas. Horizonte mínimo sugerido: 5 años."),
    Instrumento("FND-RV-GLOBAL", "Fondo renta variable global", "fondo_rv",
                "Operadora (sim)", 0.1130, 0.145, 0.0150, None, "48h", 5_000, 4,
                "Diversificación internacional. Agrega riesgo de tipo de cambio."),
    Instrumento("NAFTRAC", "ETF índice México", "etf",
                "Operadora (sim)", 0.1199, 0.155, 0.0010, None, "diaria", 100, 4,
                "Replica el S&P/BMV IPC con comisión mínima. Liquidez diaria. "
                "Es la forma diversificada de tener las 15 emisoras del catálogo."),
    Instrumento("TRACK-SP500", "ETF índice EE. UU.", "etf",
                "Operadora (sim)", 0.1105, 0.150, 0.0018, None, "diaria", 100, 4,
                "Índice amplio de Estados Unidos en pesos. El bloque de crecimiento más usado."),
    Instrumento("ETF-EM", "ETF mercados emergentes", "etf",
                "Operadora (sim)", 0.1235, 0.190, 0.0030, None, "diaria", 100, 5,
                "Emergentes fuera de México. Más rendimiento esperado y más caídas."),
    Instrumento("FIBRA-MIX", "FIBRA diversificada", "renta_variable",
                "Fideicomiso (sim)", 0.1060, 0.180, 0.0, None, "diaria", 100, 4,
                "Bienes raíces que reparten renta. Se comporta como renta variable."),
    Instrumento("FND-RV-TEC", "Fondo sectorial tecnología", "fondo_rv",
                "Operadora (sim)", 0.1490, 0.260, 0.0175, None, "48h", 5_000, 5,
                "Apuesta sectorial concentrada. El más volátil de los fondos."),
)


# ---------------------------------------------------------------------------
# Los fondos con desglose no declaran su riesgo: lo heredan de sus tenencias.
# ---------------------------------------------------------------------------
def _derivar_de_cartera(inst: Instrumento) -> Instrumento:
    """Reemplaza volatilidad, rendimiento y riesgo por lo que dicen las empresas.

    El objetivo es que no existan dos verdades. Antes `NAFTRAC` decia
    volatilidad 0.155 porque alguien la tecleo; ahora dice lo que sale de
    calcular `sqrt(w' Sigma w)` sobre las 15 emisoras que replica. Si el
    numero tecleado y el calculado difieren, el tecleado esta mal.
    """
    if not carteras.tiene_desglose(inst.instrument_id):
        return inst
    return inst._replace(
        rend_esperado_anual=round(
            carteras.rendimiento_esperado(inst.instrument_id), 6),
        volatilidad_anual=round(carteras.volatilidad(inst.instrument_id), 6),
        riesgo_1a5=carteras.riesgo_1a5(inst.instrument_id),
    )


INSTRUMENTOS: tuple[Instrumento, ...] = tuple(
    _derivar_de_cartera(i) for i in INSTRUMENTOS_BASE)

BY_ID: dict[str, Instrumento] = {i.instrument_id: i for i in INSTRUMENTOS}

CLASES_RV = ("fondo_rv", "etf", "renta_variable")


# ---------------------------------------------------------------------------
# Sensibilidad a tasas: lo que hace que un CETES-28 NO sea un depósito a 10
# años disfrazado.
# ---------------------------------------------------------------------------
# Duracion efectiva en anios. Manda el golpe de precio cuando la tasa se mueve:
# un Bono M 10A pierde ~7.2% si la tasa sube 100 puntos base.
DURACION_OVERRIDE: dict[str, float] = {
    "BONDESF-3A": 0.25,     # tasa revisable: se reprecia sola, duracion corta
    "FND-GUB-CP": 0.30,
    "FND-GUB-LP": 3.20,
    "FND-CORP-AAA": 2.60,
}

# Que tanto del rendimiento se renueva a la tasa vigente. 1.0 = el instrumento
# sigue a la tasa corta mes con mes (CETES-28). 0.1 = la tasa quedo fija y el
# movimiento de mercado se siente por precio, no por reinversion.
SENSIBILIDAD_OVERRIDE: dict[str, float] = {
    "BONDESF-3A": 0.95,
    "FND-GUB-CP": 0.85,
    "FND-GUB-LP": 0.30,
    "FND-CORP-AAA": 0.35,
}


def duracion_anios(instrument_id: str) -> float:
    """Duracion efectiva. Cero para renta variable: no la mueve la curva."""
    inst = BY_ID[instrument_id]
    if inst.clase in CLASES_RV:
        return 0.0
    if instrument_id in DURACION_OVERRIDE:
        return DURACION_OVERRIDE[instrument_id]
    if inst.plazo_dias is None:
        return 1.0
    anios = inst.plazo_dias / 365
    # Hasta un anio son cupon cero: duracion = plazo. Mas alla pagan cupon,
    # asi que la duracion es menor que el plazo.
    return anios if anios <= 1.0 else anios * 0.72


def sensibilidad_reinversion(instrument_id: str) -> float:
    """Proporcion del rendimiento que se renegocia a la tasa vigente."""
    inst = BY_ID[instrument_id]
    if inst.clase in CLASES_RV:
        return 0.0
    if instrument_id in SENSIBILIDAD_OVERRIDE:
        return SENSIBILIDAD_OVERRIDE[instrument_id]
    if inst.plazo_dias is None:
        return 0.50
    if inst.plazo_dias <= 92:
        return 1.0          # se renueva cada mes o cada trimestre
    if inst.plazo_dias <= 365:
        return 0.55
    return 0.10             # tasa fija larga: casi todo el riesgo es de precio


def tasa_de_referencia_inicial() -> float:
    return TASA_LIBRE_RIESGO


# ---------------------------------------------------------------------------
# Bloques de asignacion
# ---------------------------------------------------------------------------
# El motor de reglas razona sobre bloques, no sobre instrumentos sueltos. Un
# bloque agrupa instrumentos sustituibles entre si.
#
# Los dos bloques de acciones son distintos al resto: no se elige UN
# instrumento, se arma una canasta (ver `rules._elegir_canasta`). Meter 20% de
# una sola emisora no es una asignacion, es una apuesta.
BLOQUES: dict[str, tuple[str, ...]] = {
    "liquidez":    ("FND-GUB-CP", "CETES-28", "PAGARE-28"),
    "deuda_corta": ("CETES-182", "CETES-364", "PAGARE-180", "PAGARE-360"),
    "deuda_larga": ("FND-GUB-LP", "BONOSM-3A", "BONOSM-10A", "UDIBONO-10A", "BONDESF-3A"),
    "deuda_corp":  ("FND-CORP-AAA", "CORP-AAA-5A", "CORP-AA-7A"),
    "rv_local":    ("NAFTRAC", "FND-RV-MX", "FIBRA-MIX"),
    "rv_global":   ("TRACK-SP500", "FND-RV-GLOBAL"),
    "rv_agresiva": ("ETF-EM", "FND-RV-TEC"),
}

# Correlacion entre clases de activo. Simetrica, diagonal 1.
# Deuda corta vs renta variable ~0; deuda larga vs renta variable algo positiva.
CLASES = ("deuda_gub", "pagare", "fondo_deuda", "deuda_corp",
          "fondo_rv", "etf", "renta_variable")

CORRELACION_CLASES: dict[tuple[str, str], float] = {
    ("deuda_gub", "pagare"): 0.55,
    ("deuda_gub", "fondo_deuda"): 0.80,
    ("deuda_gub", "deuda_corp"): 0.65,
    ("deuda_gub", "fondo_rv"): 0.10,
    ("deuda_gub", "etf"): 0.05,
    ("deuda_gub", "renta_variable"): 0.08,
    ("pagare", "fondo_deuda"): 0.45,
    ("pagare", "deuda_corp"): 0.30,
    ("pagare", "fondo_rv"): 0.02,
    ("pagare", "etf"): 0.02,
    ("pagare", "renta_variable"): 0.02,
    ("fondo_deuda", "deuda_corp"): 0.70,
    ("fondo_deuda", "fondo_rv"): 0.12,
    ("fondo_deuda", "etf"): 0.08,
    ("fondo_deuda", "renta_variable"): 0.10,
    ("deuda_corp", "fondo_rv"): 0.25,
    ("deuda_corp", "etf"): 0.20,
    ("deuda_corp", "renta_variable"): 0.28,
    ("fondo_rv", "etf"): 0.82,
    ("fondo_rv", "renta_variable"): 0.70,
    ("etf", "renta_variable"): 0.68,
    # NAFTRAC replica el IPC y las 15 emisoras SON el IPC: la correlacion es
    # alta a proposito. Cambiar el ETF por acciones sueltas no diversifica.
}


def correlacion(clase_a: str, clase_b: str) -> float:
    if clase_a == clase_b:
        return 1.0
    return CORRELACION_CLASES.get((clase_a, clase_b)) or CORRELACION_CLASES[(clase_b, clase_a)]


def correlacion_instrumentos(id_a: str, id_b: str) -> float:
    """Correlacion a nivel instrumento.

    Entre dos fondos con desglose se calcula desde lo que tienen adentro
    (`carteras.correlacion_fondos`), no con el promedio de su clase. El
    indice y el fondo activo son los dos "renta variable Mexico", pero la
    correlacion real depende de cuanto se traslapan sus carteras.
    """
    if id_a == id_b:
        return 1.0
    if carteras.tiene_desglose(id_a) and carteras.tiene_desglose(id_b):
        return carteras.correlacion_fondos(id_a, id_b)
    clase_a, clase_b = BY_ID[id_a].clase, BY_ID[id_b].clase
    base = correlacion(clase_a, clase_b)
    # Dentro de la misma clase, dos instrumentos se parecen mas entre si.
    return min(0.97, base + 0.12) if clase_a == clase_b else base
