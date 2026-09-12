"""Comparacion de dos asignaciones bajo los mismos supuestos.

Clave: las dos se simulan con los mismos parametros y con trayectorias
derivadas del mismo procedimiento, asi que la diferencia que se ve es la de
las asignaciones, no la del ruido.
"""

from __future__ import annotations

from typing import Any, Mapping

from bank.finance import montecarlo

# Vocabulario de formatos que puede llevar una fila. Tiene que coincidir con
# lo que sabe pintar `porFormato` en web/src/format.ts: si aqui aparece uno
# que alla no existe, la celda cae al formato por defecto y el numero se ve
# mal sin que nadie se entere.
FORMATOS_VALIDOS = frozenset({"moneda", "porcentaje", "numero", "anios", "texto"})

METRICAS = {
    "valor_final_p50":      {"etiqueta": "Valor esperado (mediana)", "formato": "moneda", "mejor": "alto"},
    "valor_final_p10":      {"etiqueta": "Escenario malo (p10)",     "formato": "moneda", "mejor": "alto"},
    "valor_final_p90":      {"etiqueta": "Escenario bueno (p90)",    "formato": "moneda", "mejor": "alto"},
    "ganancia_p50":         {"etiqueta": "Ganancia (mediana)",       "formato": "moneda", "mejor": "alto"},
    "tir_anual_p50":        {"etiqueta": "Rendimiento anual (TIR)",  "formato": "porcentaje", "mejor": "alto"},
    "volatilidad_anual":    {"etiqueta": "Volatilidad anual",        "formato": "porcentaje", "mejor": "bajo"},
    "max_drawdown":         {"etiqueta": "Peor caída promedio",      "formato": "porcentaje", "mejor": "bajo"},
    "prob_perdida_nominal": {"etiqueta": "Probabilidad de perder",   "formato": "porcentaje", "mejor": "bajo"},
    "prob_perdida_real":    {"etiqueta": "Prob. de perder contra la inflación",
                             "formato": "porcentaje", "mejor": "bajo"},
    "prob_perdida_vs_origen": {"etiqueta": "Prob. de perder contra el origen del dinero",
                               "formato": "porcentaje", "mejor": "bajo"},
    "perdida_esperada_pct": {"etiqueta": "Pérdida esperada",         "formato": "porcentaje", "mejor": "bajo"},
    "cvar_95_pct":          {"etiqueta": "Pérdida en el 5% peor (CVaR)",
                             "formato": "porcentaje", "mejor": "bajo"},
    "indice_riesgo":        {"etiqueta": "Índice de riesgo (0-100)", "formato": "numero", "mejor": "bajo"},
    "impuestos_p50":        {"etiqueta": "Impuestos pagados (mediana)",
                             "formato": "moneda", "mejor": "bajo"},
}

METRICAS_DEFAULT = ("valor_final_p50", "valor_final_p10", "tir_anual_p50",
                    "volatilidad_anual", "max_drawdown", "prob_perdida_nominal",
                    "prob_perdida_real", "cvar_95_pct", "indice_riesgo")


class ComparacionInvalida(ValueError):
    pass


def comparar(
    izquierda: Mapping[str, float],
    derecha: Mapping[str, float],
    monto: float,
    horizonte_anios: float,
    aportacion_mensual: float = 0.0,
    *,
    metricas: tuple[str, ...] = METRICAS_DEFAULT,
    etiqueta_izquierda: str = "Opción A",
    etiqueta_derecha: str = "Opción B",
    origen: str | None = None,
) -> dict[str, Any]:
    desconocidas = [m for m in metricas if m not in METRICAS]
    if desconocidas:
        raise ComparacionInvalida(
            f"métricas desconocidas: {', '.join(desconocidas)}. "
            f"Disponibles: {', '.join(METRICAS)}"
        )

    sim_izq = montecarlo.simular(izquierda, monto, horizonte_anios, aportacion_mensual,
                                 origen=origen)
    sim_der = montecarlo.simular(derecha, monto, horizonte_anios, aportacion_mensual,
                                 origen=origen)
    res_izq = montecarlo.metricas_resumen(sim_izq)
    res_der = montecarlo.metricas_resumen(sim_der)

    filas = []
    for m in metricas:
        meta = METRICAS[m]
        a, b = res_izq[m], res_der[m]
        if a == b:
            gana = "empate"
        elif meta["mejor"] == "alto":
            gana = "izquierda" if a > b else "derecha"
        else:
            gana = "izquierda" if a < b else "derecha"
        filas.append({
            "metrica": m,
            "etiqueta": meta["etiqueta"],
            "formato": meta["formato"],
            "izquierda": a,
            "derecha": b,
            "delta": round(b - a, 6),
            "mejor": gana,
        })

    puntos_izq = sum(1 for f in filas if f["mejor"] == "izquierda")
    puntos_der = sum(1 for f in filas if f["mejor"] == "derecha")

    return {
        "supuestos": {
            "monto": round(monto, 2),
            "horizonte_anios": horizonte_anios,
            "aportacion_mensual": round(aportacion_mensual, 2),
            "trayectorias": sim_izq["trayectorias"],
            "origen": sim_izq["origen"],
            "impuestos_aplicados": sim_izq["impuestos"]["aplicados"],
            **sim_izq["supuestos"],
        },
        "izquierda": {"etiqueta": etiqueta_izquierda, "asignacion": sim_izq["asignacion"],
                      "metricas": res_izq, "escenarios": sim_izq["escenarios"]},
        "derecha": {"etiqueta": etiqueta_derecha, "asignacion": sim_der["asignacion"],
                    "metricas": res_der, "escenarios": sim_der["escenarios"]},
        "filas": filas,
        "marcador": {"izquierda": puntos_izq, "derecha": puntos_der},
        "disclaimer": (
            "Comparación sobre datos sintéticos y mismos supuestos. "
            "Ganar en más métricas no la hace la opción correcta para ti."
        ),
    }
