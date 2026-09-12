"""Propuesta de asignacion por reglas.

Dos pasos deliberadamente separados:

  1. perfil + horizonte -> pesos por BLOQUE (liquidez, deuda corta, ...)
  2. bloque + monto      -> instrumento concreto que cumple minimos y liquidez

El paso 1 es la politica de inversion; el paso 2 es ejecucion. Separarlos deja
que un analista discuta la politica sin tocar el catalogo, y que el catalogo
crezca sin tocar la politica.
"""

from __future__ import annotations

from typing import Any

from bank.instrumentos import BLOQUES, BY_ID, Instrumento

# perfil -> pesos por bloque (suman 1)
POLITICA: dict[str, dict[str, float]] = {
    "conservador": {"liquidez": 0.25, "deuda_corta": 0.45, "deuda_larga": 0.20,
                    "deuda_corp": 0.10},
    "moderado":    {"liquidez": 0.15, "deuda_corta": 0.35, "deuda_larga": 0.25,
                    "deuda_corp": 0.15, "rv_local": 0.05, "rv_global": 0.05},
    "balanceado":  {"liquidez": 0.10, "deuda_corta": 0.20, "deuda_larga": 0.25,
                    "deuda_corp": 0.15, "rv_local": 0.12, "rv_global": 0.15,
                    "rv_agresiva": 0.03},
    "crecimiento": {"liquidez": 0.07, "deuda_corta": 0.08, "deuda_larga": 0.15,
                    "deuda_corp": 0.10, "rv_local": 0.18, "rv_global": 0.32,
                    "rv_agresiva": 0.10},
    "agresivo":    {"liquidez": 0.05, "deuda_corta": 0.05, "deuda_larga": 0.05,
                    "deuda_corp": 0.05, "rv_local": 0.20, "rv_global": 0.40,
                    "rv_agresiva": 0.20},
}

BLOQUES_RV = ("rv_local", "rv_global", "rv_agresiva")
BLOQUES_DEFENSIVOS = ("liquidez", "deuda_corta")

ETIQUETA_BLOQUE = {
    "liquidez": "Liquidez",
    "deuda_corta": "Deuda de corto plazo",
    "deuda_larga": "Deuda de largo plazo",
    "deuda_corp": "Deuda corporativa",
    "rv_local": "Renta variable México",
    "rv_global": "Renta variable global",
    "rv_agresiva": "Renta variable agresiva",
}

PORQUE_BLOQUE = {
    "liquidez": "Para que puedas sacar dinero sin esperar ni vender a mal precio.",
    "deuda_corta": "Tasa conocida y plazos cortos: es el ancla del portafolio.",
    "deuda_larga": "Fija tasa más alta por más tiempo; se mueve si cambian las tasas.",
    "deuda_corp": "Sobretasa sobre gubernamental a cambio de riesgo de crédito.",
    "rv_local": "El motor de crecimiento en pesos, sin riesgo de tipo de cambio.",
    "rv_global": "Diversifica fuera de México; es lo que sostiene el rendimiento a 5+ años.",
    "rv_agresiva": "Porción chica y deliberadamente volátil para empujar el rendimiento.",
}


class SinPropuesta(ValueError):
    pass


def _ajustar_por_horizonte(pesos: dict[str, float], horizonte_anios: float) -> tuple[dict[str, float], list[str]]:
    """El horizonte manda sobre el perfil cuando se contradicen.

    Horizonte corto recorta renta variable hacia lo defensivo; horizonte largo
    mueve una parte de lo defensivo hacia renta variable global.
    """
    pesos = dict(pesos)
    notas: list[str] = []

    if horizonte_anios < 1:
        movido = sum(pesos.pop(b, 0.0) for b in BLOQUES_RV) + pesos.pop("deuda_larga", 0.0) \
            + pesos.pop("deuda_corp", 0.0)
        if movido:
            pesos["liquidez"] = pesos.get("liquidez", 0.0) + movido * 0.6
            pesos["deuda_corta"] = pesos.get("deuda_corta", 0.0) + movido * 0.4
            notas.append(
                f"Con menos de un año de plazo quité renta variable y deuda larga: "
                f"moví {movido:.0%} a liquidez y deuda corta."
            )
    elif horizonte_anios < 3:
        recorte = 0.0
        for b in BLOQUES_RV:
            if b in pesos:
                quita = pesos[b] * 0.6
                pesos[b] -= quita
                recorte += quita
        if recorte > 0.005:
            pesos["deuda_corta"] = pesos.get("deuda_corta", 0.0) + recorte
            notas.append(
                f"A {horizonte_anios:.0f} años recorté {recorte:.0%} de renta variable "
                "hacia deuda de corto plazo: no hay tiempo para recuperar una caída."
            )
    elif horizonte_anios >= 8:
        agrega = 0.0
        for b in BLOQUES_DEFENSIVOS:
            if pesos.get(b, 0.0) > 0.05:
                quita = min(pesos[b] - 0.05, pesos[b] * 0.35)
                pesos[b] -= quita
                agrega += quita
        if agrega > 0.005:
            pesos["rv_global"] = pesos.get("rv_global", 0.0) + agrega
            notas.append(
                f"Con {horizonte_anios:.0f} años de plazo pasé {agrega:.0%} de lo defensivo "
                "a renta variable global."
            )

    pesos = {b: w for b, w in pesos.items() if w > 0.004}
    total = sum(pesos.values())
    return {b: w / total for b, w in pesos.items()}, notas


def _elegir_instrumento(bloque: str, monto_bloque: float, liquidez_requerida: bool) -> Instrumento | None:
    """Dentro del bloque, el instrumento mas apropiado para ESTE monto.

    Criterio: cumple el minimo de inversion; si se pide liquidez, se descartan
    los de plazo forzoso; entre los que quedan gana el de mejor rendimiento
    neto de comision.
    """
    candidatos = [BY_ID[i] for i in BLOQUES[bloque]]
    viables = [c for c in candidatos if c.monto_minimo <= monto_bloque]
    if liquidez_requerida:
        viables = [c for c in viables if c.liquidez in ("diaria", "24h")] or viables
    if bloque == "liquidez":
        prioridad = {"diaria": 0, "24h": 1, "48h": 2, "al_vencimiento": 3}
        viables.sort(key=lambda c: (prioridad[c.liquidez],
                                    -(c.rend_esperado_anual - c.comision_anual)))
    else:
        viables.sort(key=lambda c: -(c.rend_esperado_anual - c.comision_anual))
    return viables[0] if viables else None


def proponer(
    perfil: str,
    horizonte_anios: float,
    monto: float,
    *,
    liquidez_requerida: bool = False,
    excluir_clases: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Devuelve la asignacion lista para pintar y para simular."""
    if perfil not in POLITICA:
        raise SinPropuesta(
            f"perfil desconocido: {perfil!r}. Opciones: {', '.join(POLITICA)}"
        )
    if monto <= 0:
        raise SinPropuesta("el monto debe ser positivo")
    if horizonte_anios <= 0:
        raise SinPropuesta("el horizonte debe ser positivo")

    pesos_bloque, notas = _ajustar_por_horizonte(POLITICA[perfil], horizonte_anios)

    seleccion: list[dict[str, Any]] = []
    descartados: list[str] = []
    for bloque, peso in sorted(pesos_bloque.items(), key=lambda kv: -kv[1]):
        inst = _elegir_instrumento(bloque, monto * peso, liquidez_requerida)
        if inst is None or inst.clase in excluir_clases:
            descartados.append(bloque)
            continue
        seleccion.append({"bloque": bloque, "peso": peso, "instrumento": inst})

    if not seleccion:
        raise SinPropuesta(
            f"Con ${monto:,.0f} no alcanza el mínimo de ningún instrumento del catálogo."
        )

    if descartados:
        faltante = sum(pesos_bloque[b] for b in descartados)
        total = sum(s["peso"] for s in seleccion)
        for s in seleccion:
            s["peso"] += faltante * s["peso"] / total
        notas.append(
            "Redistribuí " + f"{faltante:.0%} " +
            "porque el monto no alcanzaba el mínimo de: "
            + ", ".join(ETIQUETA_BLOQUE[b] for b in descartados) + "."
        )

    # Redondeo a 2 decimales cuadrando el residuo en el peso mayor, para que
    # los pesos sumen exactamente 1 y la dona no tenga un hueco de 0.01.
    for s in seleccion:
        s["peso"] = round(s["peso"], 4)
    residuo = round(1.0 - sum(s["peso"] for s in seleccion), 4)
    seleccion.sort(key=lambda s: -s["peso"])
    seleccion[0]["peso"] = round(seleccion[0]["peso"] + residuo, 4)

    slices = []
    rend_ponderado = 0.0
    vol_ponderada = 0.0
    comision_ponderada = 0.0
    for s in seleccion:
        inst: Instrumento = s["instrumento"]
        peso = s["peso"]
        rend_ponderado += peso * inst.rend_esperado_anual
        vol_ponderada += peso * inst.volatilidad_anual      # cota superior, sin correlacion
        comision_ponderada += peso * inst.comision_anual
        slices.append({
            "bloque": s["bloque"],
            "etiqueta": ETIQUETA_BLOQUE[s["bloque"]],
            "instrument_id": inst.instrument_id,
            "instrumento": inst.nombre,
            "clase": inst.clase,
            "peso": peso,
            "monto": round(monto * peso, 2),
            "rend_esperado_anual": inst.rend_esperado_anual,
            "volatilidad_anual": inst.volatilidad_anual,
            "comision_anual": inst.comision_anual,
            "riesgo_1a5": inst.riesgo_1a5,
            "liquidez": inst.liquidez,
            "porque": PORQUE_BLOQUE[s["bloque"]],
        })

    return {
        "perfil": perfil,
        "horizonte_anios": horizonte_anios,
        "monto": round(monto, 2),
        "slices": slices,
        "rend_esperado_anual": round(rend_ponderado, 6),
        "volatilidad_cota_anual": round(vol_ponderada, 6),
        "comision_anual_ponderada": round(comision_ponderada, 6),
        "riesgo_ponderado": round(sum(s["peso"] * s["riesgo_1a5"] for s in slices), 2),
        "notas": notas,
        "disclaimer": (
            "Propuesta generada por reglas sobre datos sintéticos. "
            "No es una recomendación de inversión."
        ),
    }


def asignacion_plana(propuesta: dict[str, Any]) -> dict[str, float]:
    """{'instrument_id': peso} — lo que consumen el Monte Carlo y las ordenes."""
    return {s["instrument_id"]: s["peso"] for s in propuesta["slices"]}
