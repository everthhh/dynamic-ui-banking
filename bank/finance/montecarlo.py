"""Simulacion Monte Carlo del portafolio.

Determinista por construccion: la semilla se deriva de los argumentos con
BLAKE2b, asi que la misma pregunta da la misma grafica siempre. Esto importa
en un demo en vivo: el presentador mueve un slider, lo regresa, y los numeros
vuelven a ser exactamente los de antes.

Convencion de retornos (la misma que bank/seed.py):
  `rend_esperado_anual` es el rendimiento ARITMETICO anual esperado, asi que
  la deriva logaritmica es log1p(mu) - sigma^2/2. La mediana rinde menos que
  la media -- ese arrastre por volatilidad es real y no se esconde.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

import numpy as np

from bank.instrumentos import BY_ID, correlacion

N_TRAYECTORIAS = 5000
MAX_HORIZONTE_ANIOS = 40


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
            if i == j:
                corr[i, j] = 1.0
            else:
                ca, cb = BY_ID[a].clase, BY_ID[b].clase
                base = correlacion(ca, cb)
                corr[i, j] = min(0.97, base + 0.12) if ca == cb else base
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


def simular(
    asignacion: Mapping[str, float],
    monto: float,
    horizonte_anios: float,
    aportacion_mensual: float = 0.0,
    *,
    n_trayectorias: int = N_TRAYECTORIAS,
) -> dict[str, Any]:
    """Escenarios p10/p50/p90 del valor del portafolio mes a mes."""
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

    pesos_map = _normalizar(asignacion)
    ids = sorted(pesos_map)
    w = np.array([pesos_map[i] for i in ids])
    meses = max(1, int(round(horizonte_anios * 12)))

    mu = np.array([BY_ID[i].rend_esperado_anual for i in ids])
    sigma = np.array([BY_ID[i].volatilidad_anual for i in ids])
    comision = np.array([BY_ID[i].comision_anual for i in ids])

    dt = 1 / 12
    drift = (np.log1p(mu) - np.log1p(comision) - 0.5 * sigma**2) * dt
    difusion = sigma * np.sqrt(dt)

    rng = np.random.default_rng(
        _semilla(tuple(sorted(pesos_map.items())), round(monto, 2),
                 round(horizonte_anios, 4), round(aportacion_mensual, 2), n_trayectorias)
    )
    L = _cholesky(ids)
    z = rng.standard_normal((n_trayectorias, meses, len(ids)))
    shocks = z @ L.T
    ret = np.expm1(drift + difusion * shocks)          # (trayectorias, meses, instrumentos)
    ret_portafolio = ret @ w                           # rebalanceo mensual implicito

    valores = np.empty((n_trayectorias, meses + 1))
    valores[:, 0] = monto
    for t in range(meses):
        valores[:, t + 1] = valores[:, t] * (1 + ret_portafolio[:, t]) + aportacion_mensual

    aportado = monto + aportacion_mensual * meses
    p10, p50, p90 = np.percentile(valores, [10, 50, 90], axis=0)

    # Max drawdown promedio entre trayectorias
    maximos = np.maximum.accumulate(valores, axis=1)
    drawdowns = (valores - maximos) / np.where(maximos == 0, 1, maximos)
    max_dd = float(-drawdowns.min(axis=1).mean())

    finales = valores[:, -1]
    prob_perdida = float((finales < aportado).mean())
    tir_p50 = _tir_anual(monto, aportacion_mensual, meses, float(p50[-1]))

    def serie(arr: np.ndarray) -> list[dict[str, float]]:
        return [{"mes": t, "anios": round(t / 12, 4), "valor": round(float(arr[t]), 2)}
                for t in range(meses + 1)]

    return {
        "asignacion": pesos_map,
        "monto_inicial": round(monto, 2),
        "aportacion_mensual": round(aportacion_mensual, 2),
        "horizonte_anios": horizonte_anios,
        "meses": meses,
        "total_aportado": round(aportado, 2),
        "trayectorias": n_trayectorias,
        "escenarios": {"p10": serie(p10), "p50": serie(p50), "p90": serie(p90)},
        "valor_final": {
            "p10": round(float(p10[-1]), 2),
            "p50": round(float(p50[-1]), 2),
            "p90": round(float(p90[-1]), 2),
        },
        "ganancia_p50": round(float(p50[-1]) - aportado, 2),
        "tir_anual_p50": round(tir_p50, 6),
        "volatilidad_anual": round(float(ret_portafolio.std(axis=1).mean() * np.sqrt(12)), 6),
        "max_drawdown": round(max_dd, 6),
        "prob_perdida_nominal": round(prob_perdida, 4),
        "disclaimer": (
            "Simulación sobre datos sintéticos. Los escenarios son probabilísticos "
            "y no garantizan resultados."
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
        "total_aportado": sim["total_aportado"],
    }
