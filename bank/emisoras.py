"""Emisoras de la BMV: fundamentales y riesgo DERIVADO de ellos.

La diferencia con el resto del catalogo es deliberada. Un CETES tiene su
`riesgo_1a5` escrito a mano porque no hay nada que calcular. Una empresa no:
su riesgo sale de lo que se observa de ella, y aqui se calcula.

`perfil_riesgo(emisora)` combina seis factores y devuelve el desglose, no
solo el numero. Si alguien pregunta "por que TLEVISA es riesgo 5 y WALMEX 3",
la respuesta es una tabla, no una opinion.

Procedencia de los precios:
  * `anclado`  -- cotizacion consultada el 12-sep-2026 (ver `Emisora.fuente`).
  * `estimado` -- calibrado a un rango plausible; sigue siendo sintetico.
El resto de los fundamentales (beta, apalancamiento, calificacion, importe
operado) son estimados en todos los casos. Esto NO es un feed de mercado: es
una foto con fecha que se actualiza a mano para que el seed siga siendo
reproducible byte a byte.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, NamedTuple

from bank.mercado import PRIMA_RIESGO_MERCADO, VOLATILIDAD_MERCADO, capm

FECHA_PRECIOS = date(2026, 9, 12)


class Emisora(NamedTuple):
    ticker: str
    nombre: str
    sector: str
    precio: float                      # MXN por accion/CPO/unidad vinculada
    fuente: str                        # anclado | estimado
    acciones_circulacion: float        # millones de titulos
    float_pct: float                   # proporcion en manos del publico
    beta: float                        # vs S&P/BMV IPC
    volatilidad_anual: float           # desviacion estandar anualizada
    dividend_yield: float
    calificacion: str                  # escala nacional Mexico
    deuda_neta_ebitda: float | None    # None en financieras
    cobertura_intereses: float | None  # EBITDA / gasto financiero
    indice_capitalizacion: float | None  # solo financieras (ICAP %)
    importe_operado_diario: float      # millones de MXN, promedio
    descripcion: str


EMISORAS: tuple[Emisora, ...] = (
    Emisora("WALMEX", "Wal-Mart de México y Centroamérica", "consumo_basico",
            46.95, "anclado", 17_461, 0.28, 0.72, 0.185, 0.031, "mxAAA",
            0.4, 22.0, None, 900,
            "Autoservicio dominante en México. Defensiva: la gente come en crisis."),
    Emisora("FEMSAUBD", "Fomento Económico Mexicano", "consumo_basico",
            158.00, "anclado", 3_165, 0.85, 0.95, 0.225, 0.028, "mxAAA",
            1.6, 7.5, None, 700,
            "OXXO, embotellado y participaciones. Flujo estable y float amplio."),
    Emisora("GFNORTEO", "Grupo Financiero Banorte", "financiero",
            184.38, "anclado", 2_883, 0.92, 1.18, 0.265, 0.062, "mxAAA",
            None, None, 20.4, 1_100,
            "Banco mexicano de mayor capitalización. Beta alta: amplifica el ciclo."),
    Emisora("GMEXICOB", "Grupo México", "materiales",
            99.33, "anclado", 7_785, 0.36, 1.32, 0.315, 0.055, "mxAAA",
            0.9, 14.0, None, 850,
            "Cobre, ferrocarril e infraestructura. Su precio sigue al cobre."),
    Emisora("BIMBOA", "Grupo Bimbo", "consumo_basico",
            62.23, "anclado", 4_095, 0.36, 0.68, 0.205, 0.019, "mxAAA",
            2.1, 6.2, None, 380,
            "Panificadora global. La más defensiva del catálogo por beta."),
    Emisora("AMXB", "América Móvil", "telecomunicaciones",
            18.60, "estimado", 61_000, 0.45, 0.88, 0.215, 0.024, "mxAAA",
            1.5, 8.0, None, 950,
            "Telecom con operación en toda América. La emisora más líquida del IPC."),
    Emisora("CEMEXCPO", "Cemex", "materiales",
            13.20, "estimado", 14_600, 0.98, 1.45, 0.385, 0.008, "mxAA-",
            2.3, 4.1, None, 620,
            "Cementera global. La beta más alta del catálogo: puro ciclo de obra."),
    Emisora("KOFUBL", "Coca-Cola FEMSA", "consumo_basico",
            196.50, "estimado", 2_100, 0.25, 0.62, 0.195, 0.045, "mxAAA",
            1.1, 9.5, None, 180,
            "Mayor embotellador de Coca-Cola del mundo. Float bajo: se opera poco."),
    Emisora("TLEVISACPO", "Grupo Televisa", "comunicaciones",
            9.40, "estimado", 2_840, 0.75, 1.28, 0.420, 0.0, "mxAA-",
            3.6, 2.3, None, 210,
            "Medios y cable. Apalancada, sin dividendo y la más volátil del catálogo."),
    Emisora("ALFAA", "Alfa", "industrial",
            13.80, "estimado", 5_000, 0.55, 1.22, 0.330, 0.030, "mxAA",
            2.4, 4.0, None, 150,
            "Controladora industrial tras las escisiones. Holding con descuento."),
    Emisora("ORBIA", "Orbia Advance Corporation", "materiales",
            12.90, "estimado", 2_100, 0.45, 1.35, 0.355, 0.035, "mxAA-",
            3.9, 2.6, None, 90,
            "Química y soluciones de agua. El apalancamiento más alto del catálogo."),
    Emisora("ASURB", "Grupo Aeroportuario del Sureste", "industrial",
            585.00, "estimado", 300, 0.70, 1.05, 0.245, 0.048, "mxAAA",
            0.3, 25.0, None, 320,
            "Concesión aeroportuaria (Cancún). Balance casi sin deuda."),
    Emisora("GAPB", "Grupo Aeroportuario del Pacífico", "industrial",
            412.00, "estimado", 470, 0.85, 1.02, 0.240, 0.052, "mxAAA",
            1.4, 8.8, None, 380,
            "Concesión aeroportuaria (Guadalajara, Tijuana). Dividendo alto."),
    Emisora("PENOLES", "Industrias Peñoles", "materiales",
            498.00, "estimado", 397, 0.25, 1.15, 0.340, 0.025, "mxAA+",
            1.2, 7.0, None, 130,
            "Plata y oro. Cobertura natural contra el peso, con float muy bajo."),
    Emisora("LIVEPOLC1", "El Puerto de Liverpool", "consumo_discrecional",
            106.50, "estimado", 1_342, 0.30, 1.10, 0.270, 0.014, "mxAAA",
            0.6, 11.0, None, 160,
            "Tienda departamental y crédito al consumo. Sensible al ingreso disponible."),
)

POR_TICKER: dict[str, Emisora] = {e.ticker: e for e in EMISORAS}

SECTORES = tuple(sorted({e.sector for e in EMISORAS}))

# Escala nacional de Mexico -> escalon numerico. 1 es el mejor credito.
NOTCH: dict[str, int] = {
    "mxAAA": 1, "mxAA+": 2, "mxAA": 3, "mxAA-": 4, "mxA+": 5, "mxA": 6,
    "mxA-": 7, "mxBBB+": 8, "mxBBB": 9, "mxBBB-": 10, "mxBB+": 11,
}

# Correlacion residual entre dos emisoras del mismo sector, una vez quitado
# lo que ya explica el mercado. Dos mineras se mueven juntas por el cobre,
# no solo por el IPC.
CORR_RESIDUAL_SECTOR = 0.35

# Pesos del modelo de riesgo de emisora. Suman 1.
PESOS_RIESGO: dict[str, float] = {
    "volatilidad": 0.26,
    "sensibilidad_mercado": 0.10,
    "solvencia": 0.20,
    "apalancamiento": 0.18,
    "liquidez_tamano": 0.14,
    "idiosincratico": 0.12,
}

ETIQUETA_FACTOR = {
    "volatilidad": "Volatilidad del precio",
    "sensibilidad_mercado": "Sensibilidad al mercado (beta)",
    "solvencia": "Calidad crediticia",
    "apalancamiento": "Apalancamiento y cobertura",
    "liquidez_tamano": "Tamaño, bursatilidad y float",
    "idiosincratico": "Riesgo propio de la empresa",
}


def _escala(valor: float, bueno: float, malo: float) -> float:
    """Lleva `valor` a 0-100, donde 100 es el extremo malo. Acepta escalas invertidas."""
    if malo == bueno:
        return 0.0
    return float(min(100.0, max(0.0, (valor - bueno) / (malo - bueno) * 100.0)))


def _escala_log(valor: float, bueno: float, malo: float) -> float:
    """Como `_escala` pero en logaritmo.

    Para capitalizacion e importe operado la diferencia entre 25 y 50 mil
    millones pesa mucho mas que entre 500 y 525 mil millones.
    """
    v = math.log(max(valor, 1e-9))
    return _escala(v, math.log(bueno), math.log(malo))


def capitalizacion(e: Emisora) -> float:
    """Valor de mercado en millones de MXN."""
    return e.acciones_circulacion * e.precio


def capitalizacion_flotante(e: Emisora) -> float:
    return capitalizacion(e) * e.float_pct


def r_cuadrada(e: Emisora) -> float:
    """Proporcion de la varianza que explica el mercado.

    `1 - R^2` es el riesgo propio de la empresa: el que NO desaparece por
    tener un portafolio bien armado y el que el mercado tampoco te paga.
    """
    explicada = (e.beta * VOLATILIDAD_MERCADO / e.volatilidad_anual) ** 2
    return float(min(0.99, max(0.0, explicada)))


def _factor_apalancamiento(e: Emisora) -> float:
    if e.indice_capitalizacion is not None:
        # Financieras: el apalancamiento es su negocio. Lo que importa es el
        # colchon de capital contra el minimo regulatorio (10.5% con
        # suplementos).
        return _escala(e.indice_capitalizacion, 20.0, 10.5)
    partes = []
    if e.deuda_neta_ebitda is not None:
        partes.append(_escala(e.deuda_neta_ebitda, 0.0, 4.5))
    if e.cobertura_intereses is not None:
        partes.append(_escala(e.cobertura_intereses, 15.0, 2.0))
    if not partes:
        return _escala(NOTCH[e.calificacion], 1, 11)
    return sum(partes) / len(partes)


def _factor_liquidez(e: Emisora) -> float:
    f_cap = _escala_log(capitalizacion(e), 600_000, 25_000)
    f_ope = _escala_log(e.importe_operado_diario, 800, 50)
    f_flo = _escala(e.float_pct, 0.60, 0.0)
    return 0.4 * f_cap + 0.4 * f_ope + 0.2 * f_flo


def factores_riesgo(e: Emisora) -> dict[str, float]:
    """Los seis factores, cada uno 0-100 (100 = mas riesgo)."""
    return {
        "volatilidad": _escala(e.volatilidad_anual, 0.12, 0.45),
        "sensibilidad_mercado": _escala(e.beta, 0.5, 1.6),
        "solvencia": _escala(NOTCH[e.calificacion], 1, 11),
        "apalancamiento": _factor_apalancamiento(e),
        "liquidez_tamano": _factor_liquidez(e),
        "idiosincratico": (1.0 - r_cuadrada(e)) * 100.0,
    }


# Bandas del score de emisora -> riesgo 1a5 del catalogo.
# El piso es 3 a proposito: una accion individual nunca es riesgo 1 ni 2, por
# buena que sea la empresa, porque es un solo emisor. Lo que baja el riesgo es
# diversificar, no la calidad del nombre.
RIESGO_MINIMO_ACCION = 3
BANDAS_EMISORA: tuple[tuple[float, int], ...] = ((22.0, 3), (38.0, 4), (101.0, 5))


def perfil_riesgo(e: Emisora) -> dict[str, Any]:
    """Score 0-100 y riesgo 1a5 de la emisora, con el desglose que lo justifica."""
    factores = factores_riesgo(e)
    score = sum(PESOS_RIESGO[k] * v for k, v in factores.items())
    riesgo = next(r for limite, r in BANDAS_EMISORA if score < limite)
    return {
        "ticker": e.ticker,
        "score": round(score, 2),
        "riesgo_1a5": max(RIESGO_MINIMO_ACCION, riesgo),
        "calificacion": e.calificacion,
        "desglose": [
            {
                "factor": k,
                "etiqueta": ETIQUETA_FACTOR[k],
                "valor": round(factores[k], 2),
                "peso": PESOS_RIESGO[k],
                "aporte": round(PESOS_RIESGO[k] * factores[k], 2),
            }
            for k in PESOS_RIESGO
        ],
        "r_cuadrada": round(r_cuadrada(e), 4),
        "riesgo_propio_pct": round((1 - r_cuadrada(e)) * 100, 2),
        "capitalizacion_mdp": round(capitalizacion(e), 2),
    }


def rendimiento_esperado(e: Emisora) -> float:
    """CAPM. Ojo: no lleva prima por riesgo idiosincratico, y eso es correcto."""
    return round(capm(e.beta), 6)


def comision_anual(e: Emisora) -> float:
    """Custodia mas el costo implicito de entrar y salir de una emisora poco operada."""
    if e.importe_operado_diario >= 500:
        return 0.0020
    if e.importe_operado_diario >= 150:
        return 0.0040
    return 0.0070


def correlacion_emisoras(a: Emisora, b: Emisora) -> float:
    """Modelo de indice unico mas un residual por sector.

    rho = beta_a*beta_b*sigma_m^2/(sigma_a*sigma_b)  <- lo que explica el IPC
        + residual_sector * sqrt((1-Ra^2)(1-Rb^2))   <- lo que comparten por giro
    """
    if a.ticker == b.ticker:
        return 1.0
    sistematica = (a.beta * b.beta * VOLATILIDAD_MERCADO ** 2) / (
        a.volatilidad_anual * b.volatilidad_anual)
    residual = 0.0
    if a.sector == b.sector:
        residual = CORR_RESIDUAL_SECTOR * math.sqrt(
            (1 - r_cuadrada(a)) * (1 - r_cuadrada(b)))
    return float(min(0.95, max(-0.95, sistematica + residual)))


def parametros_instrumento(e: Emisora) -> dict[str, Any]:
    """Lo que `bank/instrumentos.py` necesita para construir el `Instrumento`.

    Se devuelve como dict para que este modulo no importe `instrumentos` y no
    haya ciclo: emisoras describe empresas, instrumentos arma el catalogo.
    """
    perfil = perfil_riesgo(e)
    return {
        "instrument_id": e.ticker,
        "nombre": f"Acción {e.nombre}",
        "clase": "accion",
        "emisor": e.nombre,
        "rend_esperado_anual": rendimiento_esperado(e),
        "volatilidad_anual": e.volatilidad_anual,
        "comision_anual": comision_anual(e),
        "plazo_dias": None,
        "liquidez": "diaria" if e.importe_operado_diario >= 150 else "24h",
        "monto_minimo": float(max(100, math.ceil(e.precio))),
        "riesgo_1a5": perfil["riesgo_1a5"],
        "descripcion": e.descripcion,
    }


def validar_catalogo() -> list[str]:
    """Invariantes que tienen que cumplirse para que el modelo tenga sentido.

    La importante es `beta * sigma_mercado <= sigma`: la parte del movimiento
    que explica el mercado no puede ser mayor que el movimiento total. Si se
    rompe, `r_cuadrada` sale arriba de 1 y el recorte la deja en 0.99, o sea
    que una emisora mal capturada se reporta como si no tuviera riesgo propio
    --justo al reves de lo que pasa cuando alguien se equivoca al teclear.

    Lo llama el `--check` de `bank/seed.py` y un test.
    """
    problemas: list[str] = []
    for e in EMISORAS:
        sistematica = e.beta * VOLATILIDAD_MERCADO
        if sistematica > e.volatilidad_anual:
            problemas.append(
                f"{e.ticker}: beta {e.beta} implica volatilidad sistemática de "
                f"{sistematica:.3f}, mayor que la total {e.volatilidad_anual:.3f}. "
                "Revisa beta o volatilidad."
            )
        if e.calificacion not in NOTCH:
            problemas.append(
                f"{e.ticker}: calificación {e.calificacion!r} fuera de la escala.")
        if not 0 < e.float_pct <= 1:
            problemas.append(f"{e.ticker}: float_pct fuera de (0, 1].")
        if e.precio <= 0 or e.acciones_circulacion <= 0:
            problemas.append(f"{e.ticker}: precio o títulos en circulación no positivos.")
        if e.indice_capitalizacion is None and e.deuda_neta_ebitda is None \
                and e.cobertura_intereses is None:
            problemas.append(
                f"{e.ticker}: sin ninguna medida de apalancamiento ni de capital.")
    return problemas


def ficha(ticker: str) -> dict[str, Any]:
    """Todo lo que se sabe de una emisora. Alimenta `inv.FactSheet`."""
    e = POR_TICKER[ticker]
    perfil = perfil_riesgo(e)
    return {
        "ticker": e.ticker,
        "nombre": e.nombre,
        "sector": e.sector,
        "precio": e.precio,
        "fuente_precio": e.fuente,
        "fecha_precio": FECHA_PRECIOS.isoformat(),
        "acciones_circulacion_millones": e.acciones_circulacion,
        "capitalizacion_mdp": round(capitalizacion(e), 2),
        "capitalizacion_flotante_mdp": round(capitalizacion_flotante(e), 2),
        "float_pct": e.float_pct,
        "beta": e.beta,
        "volatilidad_anual": e.volatilidad_anual,
        "dividend_yield": e.dividend_yield,
        "calificacion": e.calificacion,
        "deuda_neta_ebitda": e.deuda_neta_ebitda,
        "cobertura_intereses": e.cobertura_intereses,
        "indice_capitalizacion": e.indice_capitalizacion,
        "importe_operado_diario_mdp": e.importe_operado_diario,
        "rend_esperado_anual": rendimiento_esperado(e),
        "prima_sobre_libre_riesgo": round(e.beta * PRIMA_RIESGO_MERCADO, 6),
        "riesgo": perfil,
        "descripcion": e.descripcion,
        "disclaimer": (
            "Precio "
            + ("consultado" if e.fuente == "anclado" else "estimado")
            + f" al {FECHA_PRECIOS.isoformat()}; el resto de los fundamentales son "
              "estimaciones para el ejercicio. No es información de mercado en vivo."
        ),
    }
