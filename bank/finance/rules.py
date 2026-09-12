"""Propuesta de asignacion por reglas.

Tres pasos deliberadamente separados:

  1. perfil + horizonte + origen -> pesos por BLOQUE (liquidez, deuda corta, ...)
  2. bloque + monto              -> instrumento(s) concreto(s)
  3. asignacion resultante       -> verificacion de idoneidad

El paso 1 es la politica de inversion; el paso 2 es ejecucion; el paso 3 es
control. Separarlos deja que un analista discuta la politica sin tocar el
catalogo, que el catalogo crezca sin tocar la politica, y que nadie --ni el
modelo de lenguaje-- se salte el control.

Es un producto de fondos: cada bloque se resuelve con UN fondo, nunca con
acciones sueltas. La exposicion a empresas concretas aparece por debajo, via
las tenencias de los fondos, y el control de concentracion la mira ahi
(`bank/carteras.py` + `bank/finance/idoneidad.py`).
"""

from __future__ import annotations

import math
from typing import Any

from bank import carteras
from bank.finance import idoneidad
from bank.finance import origen as origen_mod
from bank.instrumentos import BLOQUES, BY_ID, CLASES_RV, Instrumento
from bank.mercado import TASA_LIBRE_RIESGO

# perfil -> pesos por bloque (suman 1)
POLITICA: dict[str, dict[str, float]] = {
    "conservador": {"liquidez": 0.25, "deuda_corta": 0.45, "deuda_larga": 0.20,
                    "deuda_corp": 0.10},
    "moderado":    {"liquidez": 0.15, "deuda_corta": 0.35, "deuda_larga": 0.25,
                    "deuda_corp": 0.15, "rv_local": 0.05, "rv_global": 0.05},
    "balanceado":  {"liquidez": 0.10, "deuda_corta": 0.20, "deuda_larga": 0.22,
                    "deuda_corp": 0.13, "rv_local": 0.18, "rv_global": 0.17},
    "crecimiento": {"liquidez": 0.07, "deuda_corta": 0.08, "deuda_larga": 0.13,
                    "deuda_corp": 0.09, "rv_local": 0.24, "rv_global": 0.31,
                    "rv_agresiva": 0.08},
    "agresivo":    {"liquidez": 0.05, "deuda_corta": 0.05, "deuda_larga": 0.05,
                    "deuda_corp": 0.05, "rv_local": 0.27, "rv_global": 0.38,
                    "rv_agresiva": 0.15},
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


def _ajustar_por_horizonte(
    pesos: dict[str, float], horizonte_anios: float
) -> tuple[dict[str, float], list[str]]:
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


def _ajustar_por_limites(
    pesos: dict[str, float], perfil: str
) -> tuple[dict[str, float], list[str]]:
    """Recorta lo que el perfil no admite ANTES de elegir instrumentos.

    La politica y los limites de idoneidad son dos tablas distintas escritas
    por razones distintas; si alguien sube un peso en `POLITICA` sin mirar
    `idoneidad`, aqui se corrige en lugar de producir una propuesta que el
    control va a rechazar despues.
    """
    pesos = dict(pesos)
    notas: list[str] = []

    tope_rv = idoneidad.TOPE_RV_POR_PERFIL[perfil]
    en_rv = sum(pesos.get(b, 0.0) for b in BLOQUES_RV)
    if en_rv > tope_rv + 1e-9:
        exceso = en_rv - tope_rv
        for b in BLOQUES_RV:
            if b in pesos:
                pesos[b] -= exceso * pesos[b] / en_rv
        pesos["deuda_corta"] = pesos.get("deuda_corta", 0.0) + exceso
        notas.append(
            f"Bajé la renta variable de {en_rv:.0%} a {tope_rv:.0%}, que es el techo "
            f"de un perfil {perfil}."
        )

    pesos = {b: w for b, w in pesos.items() if w > 0.004}
    total = sum(pesos.values())
    return {b: w / total for b, w in pesos.items()}, notas


def _sharpe(inst: Instrumento) -> float:
    """Rendimiento neto por unidad de riesgo. Lo que ordena dentro de un bloque."""
    if inst.volatilidad_anual <= 0:
        return float("inf")
    return (inst.rend_esperado_anual - inst.comision_anual - TASA_LIBRE_RIESGO) \
        / inst.volatilidad_anual


def _elegir_instrumento(
    bloque: str, monto_bloque: float, liquidez_requerida: bool, riesgo_max: int
) -> Instrumento | None:
    """Dentro del bloque, el instrumento mas apropiado para ESTE monto y perfil.

    Criterio, en orden: no rebasa el riesgo que admite el perfil; cumple el
    minimo de inversion; si se pide liquidez, se descartan los de plazo
    forzoso; entre los que quedan gana el de mejor rendimiento neto de
    comision.

    El filtro de riesgo va primero y no es negociable. Antes no existia, y el
    motor producia propuestas que su propio control de idoneidad rechazaba:
    un conservador terminaba con un Bono M a 10 anios porque era el que mejor
    pagaba del bloque de deuda larga.
    """
    candidatos = [BY_ID[i] for i in BLOQUES[bloque] if BY_ID[i].riesgo_1a5 <= riesgo_max]
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


def _recortar_excesos(
    seleccion: list[dict[str, Any]], perfil: str
) -> list[str]:
    """Baja la renta variable y las acciones a su techo, sobre la seleccion final.

    Modifica `seleccion` en su lugar y devuelve las notas de lo que movio.
    Se aplica despues de elegir instrumentos porque los pasos anteriores
    razonan sobre bloques, y entre bloque e instrumento pasan cosas
    (descartes por minimos, bloques que no se pudieron armar) que cambian
    los pesos finales.
    """
    notas: list[str] = []
    grupos = (
        ("rv", lambda s: s["instrumento"].clase in CLASES_RV,
         idoneidad.TOPE_RV_POR_PERFIL[perfil], "renta variable"),
    )
    for _clave, es_del_grupo, tope, etiqueta in grupos:
        dentro = [s for s in seleccion if es_del_grupo(s)]
        fuera = [s for s in seleccion if not es_del_grupo(s)]
        actual = sum(s["peso"] for s in dentro)
        if actual <= tope + 1e-9 or not dentro:
            continue
        exceso = actual - tope
        if not fuera:
            # No hay a donde mover: se elimina el exceso y se renormaliza
            # sobre lo que queda del propio grupo.
            continue
        for s in dentro:
            s["peso"] -= exceso * s["peso"] / actual
        resto = sum(s["peso"] for s in fuera)
        for s in fuera:
            s["peso"] += exceso * s["peso"] / resto
        notas.append(
            f"Recorté {etiqueta} de {actual:.0%} a {tope:.0%}, que es el techo "
            f"de un perfil {perfil}."
        )
    seleccion[:] = [s for s in seleccion if s["peso"] > 0.0005]
    return notas


def proponer(
    perfil: str,
    horizonte_anios: float,
    monto: float,
    *,
    liquidez_requerida: bool = False,
    excluir_clases: tuple[str, ...] = (),
    origen: str | None = None,
) -> dict[str, Any]:
    """Devuelve la asignacion lista para pintar, para simular y ya verificada."""
    if perfil not in POLITICA:
        raise SinPropuesta(
            f"perfil desconocido: {perfil!r}. Opciones: {', '.join(POLITICA)}"
        )
    if monto <= 0:
        raise SinPropuesta("el monto debe ser positivo")
    if horizonte_anios <= 0:
        raise SinPropuesta("el horizonte debe ser positivo")
    try:
        fuente = origen_mod.resolver(origen)
    except origen_mod.OrigenInvalido as exc:
        raise SinPropuesta(str(exc)) from exc

    # El origen puede bajar el perfil antes de que se decida nada.
    efectivo = idoneidad.perfil_efectivo(perfil, origen)
    perfil_aplicable = efectivo["perfil"]

    notas: list[str] = []
    if efectivo["topado_por_origen"]:
        notas.append(efectivo["motivo"])

    pesos_bloque, notas_horizonte = _ajustar_por_horizonte(
        POLITICA[perfil_aplicable], horizonte_anios)
    notas += notas_horizonte
    pesos_bloque, notas_limites = _ajustar_por_limites(pesos_bloque, perfil_aplicable)
    notas += notas_limites

    # El techo de riesgo por instrumento es el mas estricto entre lo que
    # admite el perfil y lo que admite el origen del dinero.
    riesgo_max = min(idoneidad.RIESGO_MAX_POR_PERFIL[perfil_aplicable],
                     fuente.tope_riesgo_1a5)
    seleccion: list[dict[str, Any]] = []
    descartados: list[tuple[str, str]] = []      # (bloque, motivo)

    def _motivo(bloque: str) -> str:
        """Por que se cayo el bloque: el techo de riesgo o el monto.

        La diferencia importa. "No alcanza el monto" se arregla metiendo mas
        dinero; "no lo admite tu perfil" no.
        """
        hay_admisibles = any(
            BY_ID[i].riesgo_1a5 <= riesgo_max for i in BLOQUES[bloque])
        return "monto" if hay_admisibles else "riesgo"

    for bloque, peso in sorted(pesos_bloque.items(), key=lambda kv: -kv[1]):
        inst = _elegir_instrumento(bloque, monto * peso, liquidez_requerida,
                                   riesgo_max)
        if inst is None or inst.clase in excluir_clases:
            descartados.append((bloque, _motivo(bloque)))
            continue
        seleccion.append({"bloque": bloque, "peso": peso, "instrumento": inst})

    if not seleccion:
        raise SinPropuesta(
            f"Con ${monto:,.0f} no alcanza el mínimo de ningún instrumento del catálogo."
        )

    if descartados:
        faltante = sum(pesos_bloque[b] for b, _ in descartados)
        # Se redistribuye PRIMERO hacia lo defensivo. Repartir proporcional
        # entre todo lo que quedo inflaba la renta variable por encima del
        # techo del perfil: con 8 mil pesos se caian deuda larga y corporativa
        # por minimos, su 10% se repartia a prorrata y un moderado terminaba
        # con 24% en renta variable teniendo un techo de 20%.
        defensivos = [s for s in seleccion if s["bloque"] not in BLOQUES_RV]
        receptores = defensivos or seleccion
        total = sum(s["peso"] for s in receptores)
        for s in receptores:
            s["peso"] += faltante * s["peso"] / total
        por_motivo: dict[str, list[str]] = {}
        for bloque, motivo in descartados:
            por_motivo.setdefault(motivo, []).append(ETIQUETA_BLOQUE[bloque])
        if "riesgo" in por_motivo:
            notas.append(
                "Quité " + ", ".join(por_motivo["riesgo"])
                + f": ningún instrumento de esos bloques baja del riesgo {riesgo_max} "
                  f"que admite un perfil {perfil_aplicable}."
            )
        if "monto" in por_motivo:
            notas.append(
                "Quité " + ", ".join(por_motivo["monto"])
                + ": con este monto no alcanza para armar ahí una posición "
                  "que cumpla mínimos y quede diversificada."
            )
        notas.append(f"Redistribuí ese {faltante:.0%} entre lo que sí quedó.")

    # Ultimo recorte, ya con los instrumentos elegidos. Los ajustes de arriba
    # trabajan sobre BLOQUES; este trabaja sobre lo que de verdad quedo, y es
    # el que garantiza la invariante que importa: el motor nunca entrega una
    # propuesta que su propio control de idoneidad vaya a rechazar.
    notas += _recortar_excesos(seleccion, perfil_aplicable)

    # Redondeo a 4 decimales cuadrando el residuo en el peso mayor, para que
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
        fila = {
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
        }
        # Si el fondo tiene desglose, el slice dice en que empresas acaba
        # el dinero. Es lo que permite contestar "¿en que estoy invirtiendo?"
        # sin salirse del producto de fondos.
        if carteras.tiene_desglose(inst.instrument_id):
            desglose = carteras.ficha(inst.instrument_id)
            fila["principales_emisoras"] = [
                {"ticker": e["ticker"], "nombre": e["nombre"],
                 "peso_en_el_fondo": e["peso"],
                 "peso_efectivo": round(peso * e["peso"], 6),
                 "calificacion": e["calificacion"]}
                for e in desglose["emisoras"][:5]
            ]
            fila["riesgo_derivado_de_tenencias"] = True
        slices.append(fila)

    asignacion = {}
    for s in slices:
        asignacion[s["instrument_id"]] = asignacion.get(s["instrument_id"], 0.0) + s["peso"]

    veredicto = idoneidad.evaluar(
        asignacion, perfil, horizonte_anios, monto=monto, origen=origen)

    return {
        "perfil": perfil_aplicable,
        "perfil_declarado": perfil,
        "topado_por_origen": efectivo["topado_por_origen"],
        "origen": origen_mod.ficha(fuente),
        "horizonte_anios": horizonte_anios,
        "monto": round(monto, 2),
        "slices": slices,
        "asignacion": asignacion,
        "rend_esperado_anual": round(rend_ponderado, 6),
        "volatilidad_cota_anual": round(vol_ponderada, 6),
        "comision_anual_ponderada": round(comision_ponderada, 6),
        "riesgo_ponderado": round(sum(s["peso"] * s["riesgo_1a5"] for s in slices), 2),
        "idoneidad": veredicto,
        "notas": notas,
        "disclaimer": (
            "Propuesta generada por reglas sobre datos sintéticos y verificada "
            "contra el perfil del cliente. No es una recomendación de inversión."
        ),
    }


def asignacion_plana(propuesta: dict[str, Any]) -> dict[str, float]:
    """{'instrument_id': peso} — lo que consumen el Monte Carlo y las ordenes."""
    return dict(propuesta["asignacion"])
