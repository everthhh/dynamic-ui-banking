"""Simulacion Monte Carlo del portafolio.

Determinista por construccion: la semilla se deriva de los argumentos con
BLAKE2b, asi que la misma pregunta da la misma grafica siempre. Esto importa
en un demo en vivo: el presentador mueve un slider, lo regresa, y los numeros
vuelven a ser exactamente los de antes.

Convencion de retornos (la misma que bank/seed.py):
  `rend_esperado_anual` es el rendimiento ARITMETICO anual esperado, asi que
  la deriva logaritmica es log1p(mu) - sigma^2/2. La mediana rinde menos que
  la media -- ese arrastre por volatilidad es real y no se esconde.

Lo que el modelo SI incluye, y que una proyeccion ingenua se salta:

  * **Tasa de interes estocastica** (Vasicek mensual con reversion a la
    media). Sin esto, un CETES-28 se simula como si su tasa de hoy durara
    diez anos. Cada instrumento reacciona segun dos parametros propios:
    `sensibilidad_reinversion` (cuanto de su rendimiento se renegocia a la
    tasa vigente) y `duracion_anios` (cuanto pierde de precio si la tasa
    sube). Un CETES-28 es todo reinversion y nada de duracion; un Bono M 10A
    es al reves.
  * **Impuestos** (`bank/finance/fiscal.py`): retencion mensual sobre el
    capital en la parte de intereses, 10% sobre la ganancia de capital al
    final, y el arrastre del ISR de dividendos en acciones.
  * **Costo del financiamiento** (`bank/finance/origen.py`): si el dinero es
    prestado, la deuda corre en paralelo y la referencia de "ganar" deja de
    ser lo aportado.
  * **Inflacion**: se reporta la probabilidad de perder en terminos reales,
    no solo nominales.

Lo que NO incluye, dicho de frente: colas gordas (los retornos son
lognormales), correlaciones que se van a 1 en una crisis, default como evento
discreto, spread de compraventa, y costo de rebalanceo. Todo eso subestima la
perdida. Ver `docs/trade-offs.md`.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Mapping

import numpy as np

from bank.finance import fiscal
from bank.finance import origen as origen_mod
from bank.instrumentos import (
    BY_ID,
    correlacion_instrumentos,
    duracion_anios,
    sensibilidad_reinversion,
)
from bank.mercado import (
    INFLACION_ANUAL,
    ISR_GANANCIA_CAPITAL,
    TASA_LARGA,
    TASA_LIBRE_RIESGO,
    VELOCIDAD_REVERSION,
    VOLATILIDAD_TASA,
)

N_TRAYECTORIAS = 5000
MAX_HORIZONTE_ANIOS = 40
TASA_MINIMA = 0.005


class SimulacionInvalida(ValueError):
    pass


def _semilla(*partes: Any) -> int:
    h = hashlib.blake2b(repr(partes).encode("utf-8"), digest_size=8)
    return int.from_bytes(h.digest(), "big") % (2**32)


def _cholesky(ids: list[str]) -> np.ndarray:
    n = len(ids)
    corr = np.empty((n, n))
    for i, a in enumerate(ids):
        for j, b in enumerate(ids):
            corr[i, j] = 1.0 if i == j else correlacion_instrumentos(a, b)
    corr = (corr + corr.T) / 2 + np.eye(n) * 1e-8
    try:
        return np.linalg.cholesky(corr)
    except np.linalg.LinAlgError:
        vals, vecs = np.linalg.eigh(corr)
        corr = vecs @ np.diag(np.clip(vals, 1e-8, None)) @ vecs.T
        d = np.sqrt(np.diag(corr))
        corr = corr / np.outer(d, d)
        return np.linalg.cholesky(corr + np.eye(n) * 1e-9)


def _tir_anual(monto: float, aportacion: float, meses: int, valor_final: float) -> float:
    """TIR anualizada de los flujos reales, por biseccion.

    Con aportaciones mensuales, `(final/aportado)^(1/anios)-1` miente: trata el
    dinero del mes 59 como si hubiera estado invertido los cinco anios. La TIR
    descuenta cada flujo en su fecha, que es la unica cifra honesta que se
    puede poner junto a la grafica.
    """
    if valor_final <= 0:
        return -1.0
    flujos = [-monto] + [-aportacion] * meses
    flujos[-1] += valor_final

    def vpn(r: float) -> float:
        return sum(f / (1 + r) ** t for t, f in enumerate(flujos))

    lo, hi = -0.95 / 12, 1.0          # tasa mensual
    if vpn(lo) * vpn(hi) > 0:
        return 0.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if vpn(lo) * vpn(mid) <= 0:
            hi = mid
        else:
            lo = mid
    mensual = (lo + hi) / 2
    return float((1 + mensual) ** 12 - 1)


def _normalizar(asignacion: Mapping[str, float]) -> dict[str, float]:
    if not asignacion:
        raise SimulacionInvalida("la asignación viene vacía")
    desconocidos = [k for k in asignacion if k not in BY_ID]
    if desconocidos:
        raise SimulacionInvalida(
            f"instrumentos fuera del catálogo: {', '.join(sorted(desconocidos))}"
        )
    negativos = [k for k, v in asignacion.items() if v < 0]
    if negativos:
        raise SimulacionInvalida(f"pesos negativos en: {', '.join(negativos)}")
    total = float(sum(asignacion.values()))
    if total <= 0:
        raise SimulacionInvalida("los pesos suman cero")
    return {k: float(v) / total for k, v in asignacion.items() if v > 0}


def _trayectoria_tasas(rng: np.random.Generator, n: int, meses: int) -> np.ndarray:
    """Vasicek mensual sobre la tasa corta. Devuelve (trayectorias, meses+1).

    dr = kappa*(r_largo - r)*dt + sigma*sqrt(dt)*dW

    La reversion a la media es lo que hace realista el riesgo de reinversion:
    la tasa de hoy (6.49%) no se queda ahi diez anos, tiende hacia el nivel
    de largo plazo, y por el camino se mueve.
    """
    dt = 1 / 12
    r = np.empty((n, meses + 1))
    r[:, 0] = TASA_LIBRE_RIESGO
    z = rng.standard_normal((n, meses))
    for t in range(meses):
        deriva = VELOCIDAD_REVERSION * (TASA_LARGA - r[:, t]) * dt
        r[:, t + 1] = np.maximum(
            TASA_MINIMA,
            r[:, t] + deriva + VOLATILIDAD_TASA * np.sqrt(dt) * z[:, t])
    return r


def _metricas_perdida(
    finales: np.ndarray, referencia: np.ndarray | float, aportado: float
) -> dict[str, float]:
    """Probabilidad de perder y de cuanto. Lo segundo importa mas que lo primero.

    Una probabilidad de perder del 20% no dice nada por si sola: no es lo
    mismo perder 2% que perder 40%. Por eso va acompanada de la perdida media
    condicional (cuanto pierdes EN PROMEDIO cuando pierdes) y del CVaR 95
    (el promedio del 5% de escenarios peores).
    """
    ref = np.asarray(referencia, dtype=float)
    perdida = ref - finales                      # positivo = perdiste
    pierde = perdida > 0
    prob = float(pierde.mean())
    base = aportado if aportado > 0 else 1.0
    media_cond = float(perdida[pierde].mean()) if pierde.any() else 0.0
    peor_5 = np.percentile(finales, 5)
    cola = finales[finales <= peor_5]
    cvar = float(np.asarray(ref).mean() - cola.mean()) if cola.size else 0.0
    return {
        "prob": round(prob, 4),
        "perdida_media_si_pierde": round(media_cond, 2),
        "perdida_media_si_pierde_pct": round(media_cond / base, 4),
        "var_95": round(float(np.asarray(ref).mean() - peor_5), 2),
        "var_95_pct": round(float(np.asarray(ref).mean() - peor_5) / base, 4),
        "cvar_95": round(cvar, 2),
        "cvar_95_pct": round(cvar / base, 4),
        "perdida_esperada_pct": round(prob * media_cond / base, 4),
    }


# Limite superior (exclusivo) del score de cada banda.
BANDAS_INDICE: tuple[tuple[float, str], ...] = (
    (12.0, "muy bajo"), (28.0, "bajo"), (48.0, "medio"), (70.0, "alto"),
    (math.inf, "muy alto"),
)

# Piso del score segun la probabilidad de perder. Sin esto, un portafolio 100%
# CETES financiado con tarjeta al 42% salia "muy bajo" por tener volatilidad
# casi cero, aunque pierde contra la deuda en el 100% de las trayectorias.
# Una etiqueta de riesgo no puede contradecir la probabilidad que va al lado.
PISO_POR_PROBABILIDAD: tuple[tuple[float, float], ...] = (
    (0.75, 70.0), (0.50, 48.0), (0.25, 28.0), (0.10, 12.0),
)


def _indice_riesgo(
    volatilidad: float, max_dd: float, prob_perdida: float, concentracion: float,
    referencia_perdida: str,
) -> dict[str, Any]:
    """Un solo numero 0-100 para el riesgo del portafolio, con su desglose.

    No sustituye a las metricas de abajo: las resume para poder ponerlas en
    una tarjeta. Los cortes estan calibrados al catalogo: 100% en CETES da
    cerca de 0 y 100% en el fondo de tecnologia se acerca a 100.

    `prob_perdida` es la probabilidad que importa para este dinero (ver
    `simular`): contra la deuda si es prestado, y la peor entre nominal y real
    si es propio. Si esa probabilidad es alta, el score no baja del piso de
    `PISO_POR_PROBABILIDAD`; lo que se sube aparece como su propio renglon en
    el desglose, para que los aportes sigan sumando el score.
    """
    def escala(v: float, bueno: float, malo: float) -> float:
        return float(min(100.0, max(0.0, (v - bueno) / (malo - bueno) * 100.0)))

    factores = {
        "volatilidad": escala(volatilidad, 0.005, 0.30),
        "peor_caida": escala(max_dd, 0.0, 0.45),
        "prob_perdida": escala(prob_perdida, 0.0, 0.50),
        "concentracion": escala(concentracion, 0.10, 0.60),
    }
    pesos = {"volatilidad": 0.35, "peor_caida": 0.30,
             "prob_perdida": 0.25, "concentracion": 0.10}
    desglose = [
        {"factor": k, "valor": round(factores[k], 2), "peso": pesos[k],
         "aporte": round(pesos[k] * factores[k], 2)}
        for k in pesos
    ]
    score = sum(d["aporte"] for d in desglose)

    piso = next((p for umbral, p in PISO_POR_PROBABILIDAD if prob_perdida >= umbral), 0.0)
    if score < piso:
        desglose.append({"factor": "piso_por_probabilidad", "valor": piso, "peso": None,
                         "aporte": round(piso - score, 2)})
        score = piso

    banda = next(nombre for limite, nombre in BANDAS_INDICE if score < limite)
    return {
        "score": round(score, 2),
        "banda": banda,
        "prob_perdida": round(prob_perdida, 4),
        "referencia_perdida": referencia_perdida,
        "desglose": desglose,
    }


def simular(
    asignacion: Mapping[str, float],
    monto: float,
    horizonte_anios: float,
    aportacion_mensual: float = 0.0,
    *,
    origen: str | None = None,
    con_impuestos: bool = True,
    n_trayectorias: int = N_TRAYECTORIAS,
) -> dict[str, Any]:
    """Escenarios p10/p50/p90 del valor del portafolio mes a mes, netos."""
    if monto < 0:
        raise SimulacionInvalida("el monto inicial no puede ser negativo")
    if aportacion_mensual < 0:
        raise SimulacionInvalida("la aportación mensual no puede ser negativa")
    if monto == 0 and aportacion_mensual == 0:
        raise SimulacionInvalida("no hay nada que simular: monto y aportación en cero")
    if not 0 < horizonte_anios <= MAX_HORIZONTE_ANIOS:
        raise SimulacionInvalida(
            f"el horizonte debe estar entre 0 y {MAX_HORIZONTE_ANIOS} años"
        )

    try:
        fuente = origen_mod.resolver(origen)
    except origen_mod.OrigenInvalido as exc:
        raise SimulacionInvalida(str(exc)) from exc

    pesos_map = _normalizar(asignacion)
    ids = sorted(pesos_map)
    w = np.array([pesos_map[i] for i in ids])
    meses = max(1, int(round(horizonte_anios * 12)))

    mu = np.array([BY_ID[i].rend_esperado_anual for i in ids])
    sigma = np.array([BY_ID[i].volatilidad_anual for i in ids])
    comision = np.array([BY_ID[i].comision_anual for i in ids])
    duracion = np.array([duracion_anios(i) for i in ids])
    sensibilidad = np.array([sensibilidad_reinversion(i) for i in ids])
    div_drag = np.array([fiscal.arrastre_dividendos(i) for i in ids])
    if not con_impuestos:
        div_drag = np.zeros_like(div_drag)

    peso_interes = float(sum(
        pesos_map[i] for i in ids if fiscal.regimen_de(i) == "interes"))
    peso_capital = 1.0 - peso_interes

    dt = 1 / 12
    drift = (np.log1p(mu) - np.log1p(comision) - np.log1p(div_drag)
             - 0.5 * sigma**2) * dt
    difusion = sigma * np.sqrt(dt)

    rng = np.random.default_rng(
        _semilla(tuple(sorted(pesos_map.items())), round(monto, 2),
                 round(horizonte_anios, 4), round(aportacion_mensual, 2),
                 n_trayectorias, fuente.clave, round(fuente.costo_anual, 6),
                 con_impuestos))
    L = _cholesky(ids)
    z = rng.standard_normal((n_trayectorias, meses, len(ids)))
    shocks = z @ L.T

    # --------------------------------------------------- tasa corta y su efecto
    tasas = _trayectoria_tasas(rng, n_trayectorias, meses)
    # Lo que se renegocia: si la tasa sube, un CETES-28 empieza a rendir mas.
    brecha = (tasas[:, :-1] - TASA_LIBRE_RIESGO)[:, :, None] * sensibilidad * dt
    # Lo que se reprecia: si la tasa sube, un Bono M 10A vale menos hoy.
    delta = np.diff(tasas, axis=1)[:, :, None]
    golpe_precio = -duracion * delta

    ret = np.expm1(drift + difusion * shocks + brecha) + golpe_precio
    ret_portafolio = ret @ w                           # rebalanceo mensual implicito

    # ------------------------------------------------------ trayectoria de valor
    retencion = fiscal.retencion_mensual_capital() if con_impuestos else 0.0
    valores = np.empty((n_trayectorias, meses + 1))
    valores[:, 0] = monto
    impuesto_intereses = np.zeros(n_trayectorias)
    for t in range(meses):
        bruto = valores[:, t] * (1 + ret_portafolio[:, t]) + aportacion_mensual
        # La retencion de intereses se cobra sobre el CAPITAL, no sobre la
        # ganancia: se paga aunque el mes haya sido malo.
        cobro = bruto * peso_interes * retencion
        impuesto_intereses += cobro
        valores[:, t + 1] = np.maximum(0.0, bruto - cobro)

    aportado = monto + aportacion_mensual * meses

    # ISR de ganancia de capital: 10% al vender, solo sobre la parte del
    # portafolio que tributa asi y solo si hubo utilidad.
    ganancia_bruta = valores[:, -1] - aportado
    impuesto_capital = (
        np.maximum(0.0, ganancia_bruta) * peso_capital * ISR_GANANCIA_CAPITAL
        if con_impuestos else np.zeros(n_trayectorias))
    valores[:, -1] = valores[:, -1] - impuesto_capital

    p10, p50, p90 = np.percentile(valores, [10, 50, 90], axis=0)

    # Max drawdown promedio entre trayectorias
    maximos = np.maximum.accumulate(valores, axis=1)
    drawdowns = (valores - maximos) / np.where(maximos == 0, 1, maximos)
    max_dd = float(-drawdowns.min(axis=1).mean())

    finales = valores[:, -1]

    # ------------------------------------------------------ referencias de perdida
    # 1. nominal: no recuperar lo que metiste
    # 2. real: no recuperar el poder de compra de lo que metiste
    # 3. contra el origen: la deuda que corriste, o lo que ese dinero ya ganaba
    inflacion_acumulada = (1 + INFLACION_ANUAL) ** (meses / 12)
    umbral_real = aportado * inflacion_acumulada
    if fuente.apalancado:
        deuda_final = monto * (1 + fuente.costo_anual / 12) ** meses
        umbral_origen = deuda_final + aportacion_mensual * meses
    else:
        deuda_final = 0.0
        crecido = monto * (1 + fuente.tasa_referencia_anual / 12) ** meses
        umbral_origen = crecido + aportacion_mensual * meses

    perdida_nominal = _metricas_perdida(finales, aportado, aportado)
    perdida_real = _metricas_perdida(finales, umbral_real, aportado)
    perdida_origen = _metricas_perdida(finales, umbral_origen, aportado)

    tir_p50 = _tir_anual(monto, aportacion_mensual, meses, float(p50[-1]))
    volatilidad = float(ret_portafolio.std(axis=1).mean() * np.sqrt(12))
    concentracion = float((w**2).sum())          # Herfindahl: 1 = un solo activo

    # La probabilidad que resume el indice es la honesta para este dinero:
    # con deuda, no ganarle a la deuda; con dinero propio, la peor entre no
    # recuperar lo aportado y no ganarle a la inflacion. Decision de producto:
    # la meta es que el cliente GANE, no solo que recupere. Una cartera que
    # devuelve lo aportado pero pierde poder de compra es riesgo alto, aunque
    # sea "conservadora" por volatilidad.
    if fuente.apalancado:
        prob_indice, referencia_indice = perdida_origen["prob"], "vs_origen"
    elif perdida_real["prob"] > perdida_nominal["prob"]:
        prob_indice, referencia_indice = perdida_real["prob"], "real"
    else:
        prob_indice, referencia_indice = perdida_nominal["prob"], "nominal"

    def serie(arr: np.ndarray) -> list[dict[str, float]]:
        return [{"mes": t, "anios": round(t / 12, 4), "valor": round(float(arr[t]), 2)}
                for t in range(meses + 1)]

    impuestos_total = impuesto_intereses + impuesto_capital

    return {
        "asignacion": pesos_map,
        "monto_inicial": round(monto, 2),
        "aportacion_mensual": round(aportacion_mensual, 2),
        "horizonte_anios": horizonte_anios,
        "meses": meses,
        "total_aportado": round(aportado, 2),
        "trayectorias": n_trayectorias,
        "origen": origen_mod.ficha(fuente),
        "escenarios": {"p10": serie(p10), "p50": serie(p50), "p90": serie(p90)},
        "valor_final": {
            "p10": round(float(p10[-1]), 2),
            "p50": round(float(p50[-1]), 2),
            "p90": round(float(p90[-1]), 2),
        },
        "ganancia_p50": round(float(p50[-1]) - aportado, 2),
        "tir_anual_p50": round(tir_p50, 6),
        "volatilidad_anual": round(volatilidad, 6),
        "max_drawdown": round(max_dd, 6),
        "concentracion_hhi": round(concentracion, 4),

        # --- riesgo resumido
        "indice_riesgo": _indice_riesgo(
            volatilidad, max_dd, prob_indice, concentracion, referencia_indice),

        # --- tasas de perdida, tres referencias distintas
        "prob_perdida_nominal": perdida_nominal["prob"],
        "prob_perdida_real": perdida_real["prob"],
        "prob_perdida_vs_origen": perdida_origen["prob"],
        "perdida": {
            "nominal": perdida_nominal,
            "real": perdida_real,
            "vs_origen": perdida_origen,
        },

        # --- impuestos
        "impuestos": {
            "aplicados": con_impuestos,
            "retencion_intereses_p50": round(float(np.median(impuesto_intereses)), 2),
            "isr_ganancia_capital_p50": round(float(np.median(impuesto_capital)), 2),
            "total_p50": round(float(np.median(impuestos_total)), 2),
            "carga_sobre_ganancia_p50": round(
                float(np.median(impuestos_total)) / max(1.0, float(np.median(
                    valores[:, -1] + impuestos_total - aportado))), 4),
            "desglose": fiscal.desglose(pesos_map),
        },

        # --- financiamiento
        "financiamiento": {
            "apalancado": fuente.apalancado,
            "costo_anual": round(fuente.costo_anual, 6),
            "deuda_final": round(deuda_final, 2),
            "umbral_para_no_perder": round(float(umbral_origen), 2),
            "umbral_real": round(float(umbral_real), 2),
        },

        "supuestos": {
            "tasa_inicial": TASA_LIBRE_RIESGO,
            "tasa_larga": TASA_LARGA,
            "tasa_final_p50": round(float(np.median(tasas[:, -1])), 6),
            "inflacion_anual": INFLACION_ANUAL,
            "modelo_tasas": "Vasicek mensual con reversión a la media",
        },

        "disclaimer": (
            "Simulación sobre datos sintéticos con impuestos, costo de "
            "financiamiento y tasa de interés estocástica. Los escenarios son "
            "probabilísticos y no garantizan resultados. El modelo usa retornos "
            "lognormales y correlaciones fijas: subestima las crisis."
        ),
    }


def metricas_resumen(sim: dict[str, Any]) -> dict[str, Any]:
    """Subconjunto plano que usan la tabla comparativa y las tarjetas."""
    return {
        "valor_final_p50": sim["valor_final"]["p50"],
        "valor_final_p10": sim["valor_final"]["p10"],
        "valor_final_p90": sim["valor_final"]["p90"],
        "ganancia_p50": sim["ganancia_p50"],
        "tir_anual_p50": sim["tir_anual_p50"],
        "volatilidad_anual": sim["volatilidad_anual"],
        "max_drawdown": sim["max_drawdown"],
        "prob_perdida_nominal": sim["prob_perdida_nominal"],
        "prob_perdida_real": sim["prob_perdida_real"],
        "prob_perdida_vs_origen": sim["prob_perdida_vs_origen"],
        "perdida_esperada_pct": sim["perdida"]["nominal"]["perdida_esperada_pct"],
        "cvar_95_pct": sim["perdida"]["nominal"]["cvar_95_pct"],
        "indice_riesgo": sim["indice_riesgo"]["score"],
        "impuestos_p50": sim["impuestos"]["total_p50"],
        "total_aportado": sim["total_aportado"],
    }
