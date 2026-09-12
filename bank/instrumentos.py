"""Catalogo de instrumentos sinteticos.

24 instrumentos con un perfil riesgo-rendimiento plausible para Mexico a 2026.
Todo inventado: los emisores son nombres genericos y los ISIN son *_mock.

Las cifras son las que el resto del sistema usa como verdad: el generador de
series las respeta (deriva = rend_esperado, sigma = volatilidad_anual) y el
Monte Carlo tambien. Cambiar un numero aqui cambia el demo completo.
"""

from __future__ import annotations

from typing import NamedTuple


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


INSTRUMENTOS: tuple[Instrumento, ...] = (
    # ---------------------------------------------------------- deuda gubernamental
    Instrumento("CETES-28", "CETES 28 días", "deuda_gub", "Gobierno Federal (sim)",
                0.0745, 0.006, 0.0, 28, "al_vencimiento", 100, 1,
                "Deuda gubernamental a 28 días. El piso de riesgo del catálogo."),
    Instrumento("CETES-91", "CETES 91 días", "deuda_gub", "Gobierno Federal (sim)",
                0.0760, 0.009, 0.0, 91, "al_vencimiento", 100, 1,
                "CETES a 91 días. Rendimiento ligeramente mayor, menos liquidez."),
    Instrumento("CETES-182", "CETES 182 días", "deuda_gub", "Gobierno Federal (sim)",
                0.0775, 0.012, 0.0, 182, "al_vencimiento", 100, 1,
                "CETES a medio año. Para dinero con fecha conocida."),
    Instrumento("CETES-364", "CETES 364 días", "deuda_gub", "Gobierno Federal (sim)",
                0.0790, 0.018, 0.0, 364, "al_vencimiento", 100, 1,
                "CETES a un año. Fija la tasa por 12 meses."),
    Instrumento("BONDESF-3A", "BONDES F 3 años", "deuda_gub", "Gobierno Federal (sim)",
                0.0805, 0.024, 0.0, 1095, "48h", 1_000, 2,
                "Tasa revisable. Amortigua movimientos de la tasa de referencia."),
    Instrumento("BONOSM-3A", "Bono M 3 años", "deuda_gub", "Gobierno Federal (sim)",
                0.0840, 0.045, 0.0, 1095, "48h", 1_000, 2,
                "Tasa fija a 3 años. Gana si las tasas bajan, pierde si suben."),
    Instrumento("BONOSM-10A", "Bono M 10 años", "deuda_gub", "Gobierno Federal (sim)",
                0.0895, 0.080, 0.0, 3650, "48h", 1_000, 3,
                "Tasa fija larga. Sensible a tasas; no es para plazos cortos."),
    Instrumento("UDIBONO-10A", "UDIBONO 10 años", "deuda_gub", "Gobierno Federal (sim)",
                0.0860, 0.070, 0.0, 3650, "48h", 1_000, 3,
                "Indexado a la inflación. Protege el poder de compra a largo plazo."),

    # --------------------------------------------------------------------- pagares
    Instrumento("PAGARE-28", "Pagaré 28 días", "pagare", "Banco (sim)",
                0.0610, 0.002, 0.0, 28, "al_vencimiento", 1_000, 1,
                "Pagaré bancario a 28 días. Capital garantizado, rendimiento bajo."),
    Instrumento("PAGARE-91", "Pagaré 91 días", "pagare", "Banco (sim)",
                0.0675, 0.002, 0.0, 91, "al_vencimiento", 5_000, 1,
                "Pagaré a 91 días. Sin acceso al dinero hasta el vencimiento."),
    Instrumento("PAGARE-180", "Pagaré 180 días", "pagare", "Banco (sim)",
                0.0720, 0.002, 0.0, 180, "al_vencimiento", 10_000, 1,
                "Pagaré a 6 meses. Tasa fija conocida desde el día uno."),
    Instrumento("PAGARE-360", "Pagaré 360 días", "pagare", "Banco (sim)",
                0.0760, 0.002, 0.0, 360, "al_vencimiento", 25_000, 1,
                "Pagaré a un año. El más alto de la familia, el menos líquido."),

    # --------------------------------------------------------------- fondos deuda
    Instrumento("FND-GUB-CP", "Fondo deuda gubernamental corto plazo", "fondo_deuda",
                "Operadora (sim)", 0.0730, 0.010, 0.0065, None, "diaria", 1_000, 1,
                "Liquidez diaria con rendimiento de mercado de dinero. El «cajón» del portafolio."),
    Instrumento("FND-GUB-LP", "Fondo deuda gubernamental largo plazo", "fondo_deuda",
                "Operadora (sim)", 0.0810, 0.032, 0.0085, None, "24h", 1_000, 2,
                "Duración media. Más rendimiento que el de corto plazo, con vaivenes."),
    Instrumento("FND-CORP-AAA", "Fondo deuda corporativa AAA", "fondo_deuda",
                "Operadora (sim)", 0.0860, 0.040, 0.0095, None, "48h", 5_000, 2,
                "Deuda de empresas con la mejor calificación. Sobretasa sobre gubernamental."),
    Instrumento("CORP-AAA-5A", "Bono corporativo AAA 5 años", "deuda_corp",
                "Corporativo (sim)", 0.0910, 0.055, 0.0, 1825, "48h", 100_000, 3,
                "Emisión directa. Mejor tasa, menos liquidez y riesgo de crédito."),
    Instrumento("CORP-AA-7A", "Bono corporativo AA 7 años", "deuda_corp",
                "Corporativo (sim)", 0.0980, 0.075, 0.0, 2555, "48h", 100_000, 3,
                "Un escalón abajo en calificación. La sobretasa paga ese riesgo."),

    # --------------------------------------------------------- renta variable
    Instrumento("FND-RV-MX", "Fondo renta variable México", "fondo_rv",
                "Operadora (sim)", 0.1250, 0.160, 0.0135, None, "48h", 5_000, 4,
                "Acciones mexicanas. Horizonte mínimo sugerido: 5 años."),
    Instrumento("FND-RV-GLOBAL", "Fondo renta variable global", "fondo_rv",
                "Operadora (sim)", 0.1180, 0.145, 0.0150, None, "48h", 5_000, 4,
                "Diversificación internacional. Agrega riesgo de tipo de cambio."),
    Instrumento("NAFTRAC", "ETF índice México", "etf",
                "Operadora (sim)", 0.1200, 0.175, 0.0010, None, "diaria", 100, 4,
                "Replica el índice local con comisión mínima. Liquidez diaria."),
    Instrumento("TRACK-SP500", "ETF índice EE. UU.", "etf",
                "Operadora (sim)", 0.1150, 0.150, 0.0018, None, "diaria", 100, 4,
                "Índice amplio de Estados Unidos en pesos. El bloque de crecimiento más usado."),
    Instrumento("ETF-EM", "ETF mercados emergentes", "etf",
                "Operadora (sim)", 0.1280, 0.190, 0.0030, None, "diaria", 100, 5,
                "Emergentes fuera de México. Más rendimiento esperado y más caídas."),
    Instrumento("FIBRA-MIX", "FIBRA diversificada", "renta_variable",
                "Fideicomiso (sim)", 0.1100, 0.180, 0.0, None, "diaria", 100, 4,
                "Bienes raíces que reparten renta. Se comporta como renta variable."),
    Instrumento("FND-RV-TEC", "Fondo sectorial tecnología", "fondo_rv",
                "Operadora (sim)", 0.1550, 0.260, 0.0175, None, "48h", 5_000, 5,
                "Apuesta sectorial concentrada. El más volátil del catálogo."),
)

BY_ID: dict[str, Instrumento] = {i.instrument_id: i for i in INSTRUMENTOS}

# Bloques de asignacion: el motor de reglas razona sobre bloques, no sobre
# instrumentos sueltos. Un bloque agrupa instrumentos sustituibles entre si.
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
}


def correlacion(clase_a: str, clase_b: str) -> float:
    if clase_a == clase_b:
        return 1.0
    return CORRELACION_CLASES.get((clase_a, clase_b)) or CORRELACION_CLASES[(clase_b, clase_a)]
