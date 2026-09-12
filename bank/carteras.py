"""Composicion de los fondos: que empresas hay DENTRO de lo que se compra.

Este es un producto de fondos de inversion, no una casa de bolsa. El cliente
nunca compra WALMEX; compra un fondo que tiene WALMEX adentro. Entonces la
pregunta "¿que tan confiable es la empresa en la que voy a invertir?" no se
responde con el riesgo de una accion suelta, se responde **mirando a traves
del fondo** (look-through):

    peso efectivo en WALMEX = peso del fondo en el portafolio
                              x peso de WALMEX dentro del fondo

De ahi sale todo lo demas. El riesgo de un fondo de renta variable mexicana
NO esta escrito a mano: se calcula desde sus tenencias, con la matriz de
correlacion entre emisoras. Si Televisa se deteriora, el fondo que la trae
sube de riesgo solo, sin que nadie toque el catalogo.

Los fondos internacionales y sectoriales globales no tienen desglose aqui: su
subyacente no son emisoras de la BMV. Se declara explicitamente en
`SIN_DESGLOSE` en lugar de inventarles una cartera.
"""

from __future__ import annotations

import math
from typing import Any

from bank import emisoras
from bank.mercado import capm

# Tope por emisora dentro de un indice. El S&P/BMV IPC aplica topes para que
# una sola empresa no domine el indice; sin esto, America Movil pesaria 18%.
TOPE_INDICE = 0.15

# Fondos cuyo subyacente NO son emisoras de la BMV. No se les inventa cartera.
SIN_DESGLOSE: dict[str, str] = {
    "TRACK-SP500": "Índice de EE. UU.: su subyacente son emisoras estadounidenses.",
    "FND-RV-GLOBAL": "Renta variable global: cartera internacional diversificada.",
    "ETF-EM": "Mercados emergentes fuera de México.",
    "FND-RV-TEC": "Sectorial de tecnología global, sin componente local relevante.",
    "FIBRA-MIX": "Bienes raíces: su subyacente son inmuebles, no acciones.",
}


def _cartera_indice() -> dict[str, float]:
    """Réplica del IPC: capitalización flotante con tope por emisora.

    Se CALCULA desde los fundamentales, no se teclea. Si cambia el precio de
    una emisora, su peso en el índice cambia solo, que es justo lo que hace
    un índice de verdad.
    """
    crudos = {e.ticker: emisoras.capitalizacion_flotante(e) for e in emisoras.EMISORAS}
    total = sum(crudos.values())
    pesos = {k: v / total for k, v in crudos.items()}

    # Tope iterativo: se recorta al que rebasa y se reparte entre los demás,
    # que es como se construye un índice con caps en la práctica.
    for _ in range(20):
        excedidos = {k for k, w in pesos.items() if w > TOPE_INDICE + 1e-9}
        if not excedidos:
            break
        sobrante = sum(pesos[k] - TOPE_INDICE for k in excedidos)
        libres = {k: w for k, w in pesos.items() if k not in excedidos}
        base = sum(libres.values())
        for k in excedidos:
            pesos[k] = TOPE_INDICE
        for k in libres:
            pesos[k] += sobrante * libres[k] / base
    return {k: round(v, 6) for k, v in sorted(pesos.items(), key=lambda kv: -kv[1])}


# Fondo activo: el gestor concentra en sus convicciones. Por eso tiene mas
# riesgo por emisora que el indice aunque las dos sean "renta variable
# Mexico", y por eso el control de concentracion look-through existe.
CARTERA_ACTIVA: dict[str, float] = {
    "GFNORTEO": 0.22,
    "GMEXICOB": 0.18,
    "CEMEXCPO": 0.15,
    "AMXB": 0.12,
    "WALMEX": 0.10,
    "ASURB": 0.09,
    "TLEVISACPO": 0.08,
    "ORBIA": 0.06,
}

COMPOSICION: dict[str, dict[str, float]] = {
    "NAFTRAC": _cartera_indice(),
    "FND-RV-MX": CARTERA_ACTIVA,
}

ESTILO = {
    "NAFTRAC": "indexado",
    "FND-RV-MX": "activo",
}


class CarteraInvalida(ValueError):
    pass


def tiene_desglose(instrument_id: str) -> bool:
    return instrument_id in COMPOSICION


def cartera(instrument_id: str) -> dict[str, float]:
    if instrument_id not in COMPOSICION:
        raise CarteraInvalida(f"{instrument_id} no tiene desglose por emisora.")
    return dict(COMPOSICION[instrument_id])


# ---------------------------------------------------------------------------
# Estadisticas del fondo, derivadas de sus tenencias
# ---------------------------------------------------------------------------
def volatilidad(instrument_id: str) -> float:
    """sigma_p = sqrt(w' Sigma w), con la matriz de correlacion entre emisoras.

    Matematica de portafolio de verdad: la volatilidad del fondo es MENOR que
    el promedio de las volatilidades de lo que trae, porque las emisoras no
    se mueven todas juntas. Ese descuento es la diversificacion, y es la
    razon por la que un fondo es mas apto que una accion suelta.
    """
    pesos = cartera(instrument_id)
    tickers = sorted(pesos)
    total = 0.0
    for a in tickers:
        ea = emisoras.POR_TICKER[a]
        for b in tickers:
            eb = emisoras.POR_TICKER[b]
            rho = 1.0 if a == b else emisoras.correlacion_emisoras(ea, eb)
            total += (pesos[a] * pesos[b] * ea.volatilidad_anual
                      * eb.volatilidad_anual * rho)
    return math.sqrt(max(0.0, total))


def beta(instrument_id: str) -> float:
    pesos = cartera(instrument_id)
    return sum(w * emisoras.POR_TICKER[t].beta for t, w in pesos.items())


def dividend_yield(instrument_id: str) -> float:
    pesos = cartera(instrument_id)
    return sum(w * emisoras.POR_TICKER[t].dividend_yield for t, w in pesos.items())


def rendimiento_esperado(instrument_id: str) -> float:
    """CAPM sobre la beta agregada de las tenencias."""
    return capm(beta(instrument_id))


def concentracion_hhi(instrument_id: str) -> float:
    """Herfindahl: 1 = una sola emisora, 1/n = perfectamente repartido."""
    pesos = cartera(instrument_id)
    return sum(w ** 2 for w in pesos.values())


def score_emisoras(instrument_id: str) -> float:
    """Riesgo promedio ponderado de las empresas que hay dentro."""
    pesos = cartera(instrument_id)
    return sum(w * emisoras.perfil_riesgo(emisoras.POR_TICKER[t])["score"]
               for t, w in pesos.items())


def diversificacion(instrument_id: str) -> float:
    """Cuanto riesgo se quita por no tener una sola emisora.

    1 - sigma_fondo / sigma_promedio_ponderada. Si las tenencias estuvieran
    perfectamente correlacionadas esto seria 0.
    """
    pesos = cartera(instrument_id)
    promedio = sum(w * emisoras.POR_TICKER[t].volatilidad_anual
                   for t, w in pesos.items())
    if promedio <= 0:
        return 0.0
    return max(0.0, 1.0 - volatilidad(instrument_id) / promedio)


# Bandas de riesgo 1a5 para un fondo con desglose. Son mas bajas que las de
# una emisora suelta a proposito: un fondo diversificado con las MISMAS
# empresas adentro es menos riesgoso que cualquiera de ellas por separado.
BANDAS_FONDO: tuple[tuple[float, int], ...] = ((0.10, 2), (0.20, 3), (0.32, 4), (9.9, 5))


def riesgo_1a5(instrument_id: str) -> int:
    """Riesgo del fondo, derivado de su volatilidad y su concentracion.

    La volatilidad ya trae dentro la calidad de las emisoras (una cartera de
    empresas volatiles da un fondo volatil). La concentracion se cobra
    aparte: dos fondos con la misma volatilidad no son igual de seguros si
    uno depende de tres nombres.
    """
    vol = volatilidad(instrument_id)
    castigo = 1.0 + max(0.0, concentracion_hhi(instrument_id) - 0.10)
    return next(r for limite, r in BANDAS_FONDO if vol * castigo < limite)


def correlacion_fondos(a: str, b: str) -> float:
    """Correlacion entre dos fondos, calculada desde lo que tienen adentro.

    cov(A,B) = sum_i sum_j wA_i wB_j sigma_i sigma_j rho_ij
    """
    if a == b:
        return 1.0
    pa, pb = cartera(a), cartera(b)
    cov = 0.0
    for ta, wa in pa.items():
        ea = emisoras.POR_TICKER[ta]
        for tb, wb in pb.items():
            eb = emisoras.POR_TICKER[tb]
            rho = 1.0 if ta == tb else emisoras.correlacion_emisoras(ea, eb)
            cov += wa * wb * ea.volatilidad_anual * eb.volatilidad_anual * rho
    denom = volatilidad(a) * volatilidad(b)
    return float(min(0.99, max(-0.99, cov / denom))) if denom else 0.0


# ---------------------------------------------------------------------------
# Look-through de un portafolio completo
# ---------------------------------------------------------------------------
def exposicion_por_emisora(asignacion: dict[str, float]) -> dict[str, float]:
    """Peso EFECTIVO en cada empresa, mirando a traves de los fondos.

    Es el numero que importa en un producto de fondos: alguien que trae 40%
    de un indice y 30% de un fondo activo puede tener 9% en una sola empresa
    sin haberla comprado nunca, y sin este calculo nadie se entera.
    """
    total = sum(asignacion.values()) or 1.0
    efectiva: dict[str, float] = {}
    for iid, peso in asignacion.items():
        if not tiene_desglose(iid):
            continue
        w = peso / total
        for ticker, dentro in COMPOSICION[iid].items():
            efectiva[ticker] = efectiva.get(ticker, 0.0) + w * dentro
    return {k: round(v, 6) for k, v in
            sorted(efectiva.items(), key=lambda kv: -kv[1])}


def exposicion_por_sector(asignacion: dict[str, float]) -> dict[str, float]:
    por_sector: dict[str, float] = {}
    for ticker, w in exposicion_por_emisora(asignacion).items():
        sector = emisoras.POR_TICKER[ticker].sector
        por_sector[sector] = round(por_sector.get(sector, 0.0) + w, 6)
    return dict(sorted(por_sector.items(), key=lambda kv: -kv[1]))


def cobertura_desglose(asignacion: dict[str, float]) -> float:
    """Que proporcion del portafolio se puede mirar por dentro.

    Se reporta para no dar una falsa sensacion de transparencia: si el 60%
    esta en fondos internacionales, la exposicion por emisora que se muestra
    solo cubre el 40% restante.
    """
    total = sum(asignacion.values()) or 1.0
    return round(sum(p for i, p in asignacion.items() if tiene_desglose(i)) / total, 6)


def ficha(instrument_id: str) -> dict[str, Any]:
    """Desglose del fondo con todo lo derivado. Alimenta `inv.FactSheet`."""
    if not tiene_desglose(instrument_id):
        return {
            "instrument_id": instrument_id,
            "tiene_desglose": False,
            "motivo": SIN_DESGLOSE.get(
                instrument_id, "Este instrumento no invierte en acciones."),
        }
    pesos = cartera(instrument_id)
    filas = []
    for ticker, w in sorted(pesos.items(), key=lambda kv: -kv[1]):
        e = emisoras.POR_TICKER[ticker]
        perfil = emisoras.perfil_riesgo(e)
        filas.append({
            "ticker": ticker,
            "nombre": e.nombre,
            "sector": e.sector,
            "peso": w,
            "beta": e.beta,
            "volatilidad_anual": e.volatilidad_anual,
            "calificacion": e.calificacion,
            "score_riesgo": perfil["score"],
            "riesgo_1a5": perfil["riesgo_1a5"],
            "riesgo_propio_pct": perfil["riesgo_propio_pct"],
        })
    return {
        "instrument_id": instrument_id,
        "tiene_desglose": True,
        "estilo": ESTILO.get(instrument_id, "indexado"),
        "emisoras": filas,
        "n_emisoras": len(filas),
        "derivado_de_tenencias": {
            "volatilidad_anual": round(volatilidad(instrument_id), 6),
            "beta": round(beta(instrument_id), 4),
            "rend_esperado_anual": round(rendimiento_esperado(instrument_id), 6),
            "dividend_yield": round(dividend_yield(instrument_id), 6),
            "concentracion_hhi": round(concentracion_hhi(instrument_id), 4),
            "score_emisoras_ponderado": round(score_emisoras(instrument_id), 2),
            "riesgo_1a5": riesgo_1a5(instrument_id),
            "descuento_por_diversificacion": round(diversificacion(instrument_id), 4),
        },
        "nota": (
            "El riesgo de este fondo no está capturado a mano: sale de las "
            "empresas que trae y de cómo se mueven entre sí. La volatilidad del "
            "fondo es menor que el promedio de la de sus emisoras porque no "
            "caen todas al mismo tiempo."
        ),
    }


def validar() -> list[str]:
    """Invariantes de las carteras. Lo corre el `--check` del seed."""
    problemas: list[str] = []
    for iid, pesos in COMPOSICION.items():
        suma = sum(pesos.values())
        if abs(suma - 1.0) > 1e-4:
            problemas.append(f"{iid}: los pesos suman {suma:.6f}, deben sumar 1.")
        fuera = sorted(t for t in pesos if t not in emisoras.POR_TICKER)
        if fuera:
            problemas.append(f"{iid}: emisoras desconocidas: {', '.join(fuera)}.")
        if any(w < 0 for w in pesos.values()):
            problemas.append(f"{iid}: pesos negativos.")
        if len(pesos) < 5:
            problemas.append(f"{iid}: solo {len(pesos)} emisoras; no es un fondo.")
        # La diversificacion tiene que existir: si no, el fondo no aporta nada
        # sobre comprar una accion.
        if diversificacion(iid) <= 0.05:
            problemas.append(
                f"{iid}: la cartera no diversifica (descuento "
                f"{diversificacion(iid):.3f}). Revisa correlaciones o pesos.")
    solapados = set(COMPOSICION) & set(SIN_DESGLOSE)
    if solapados:
        problemas.append(
            f"instrumentos declarados con y sin desglose: {', '.join(sorted(solapados))}")
    return problemas
