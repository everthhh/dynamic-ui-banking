"""Idoneidad: el cruce entre lo que se propone y para quien se propone.

Este modulo es el control que faltaba. Antes, que un conservador no recibiera
un fondo de tecnologia dependia de que la tabla `POLITICA` no le asignara
peso a ese bloque: una restriccion por omision, no una verificacion. Si el
modelo inventaba una asignacion y la mandaba directo a `simulate_portfolio` o
a `place_order`, nadie la revisaba.

Ahora toda asignacion pasa por `evaluar()` antes de simularse y antes de
ejecutarse. Dos niveles:

  * `bloqueante` -- la orden no se ejecuta. `services/orders.py` la rechaza.
  * `aviso`      -- se puede seguir, pero queda escrito y se le dice al
                    cliente.

Las reglas van de lo general a lo particular:
  1. riesgo del instrumento contra el perfil
  2. techo de renta variable por perfil
  3. concentracion efectiva por empresa y por sector, mirando DENTRO de los
     fondos (look-through)
  4. plazo forzoso contra el horizonte del cliente
  5. montos minimos
  6. origen de los fondos (credito vs recursos propios)
"""

from __future__ import annotations

from typing import Any, Mapping

from bank import carteras, emisoras
from bank.finance import origen as origen_mod
from bank.instrumentos import BY_ID, CLASES_RV

ORDEN_PERFILES = ("conservador", "moderado", "balanceado", "crecimiento", "agresivo")

# Riesgo maximo por instrumento que admite cada perfil.
# Sube un escalon a la vez y se queda corto a proposito: el control fuerte de
# exposicion son los topes de cartera de abajo, no este. Este solo impide que
# un instrumento entre a un portafolio donde no tiene nada que hacer -- un bono
# a 10 anios con duracion 7.2 en manos de un conservador, por ejemplo.
RIESGO_MAX_POR_PERFIL: dict[str, int] = {
    "conservador": 2,
    "moderado": 4,
    "balanceado": 4,
    "crecimiento": 5,
    "agresivo": 5,
}

# Techo de renta variable total (fondos RV + ETFs + FIBRAs + acciones).
TOPE_RV_POR_PERFIL: dict[str, float] = {
    "conservador": 0.00,
    "moderado": 0.20,
    "balanceado": 0.45,
    "crecimiento": 0.75,
    "agresivo": 1.00,
}

# Peso maximo EFECTIVO en una sola empresa, mirando a traves de los fondos.
#
# El cliente nunca compra una accion, pero termina expuesto a empresas
# concretas por lo que los fondos traen dentro. Alguien con 40% de un indice
# y 20% de un fondo activo puede acabar con 10% en un solo banco sin haberlo
# elegido. Este es el unico control que ve eso; sin el, "diversificado"
# significa "tiene varios fondos", que no es lo mismo.
TOPE_LOOKTHROUGH_EMISORA: dict[str, float] = {
    "conservador": 0.02,
    "moderado": 0.04,
    "balanceado": 0.07,
    "crecimiento": 0.10,
    "agresivo": 0.14,
}

# Lo mismo por sector: cinco emisoras del mismo giro no son cinco apuestas.
TOPE_LOOKTHROUGH_SECTOR: dict[str, float] = {
    "conservador": 0.05,
    "moderado": 0.10,
    "balanceado": 0.18,
    "crecimiento": 0.25,
    "agresivo": 0.32,
}

# Holgura por redondeo: los pesos vienen redondeados a 4 decimales y no tiene
# caso rechazar una orden por 0.3 puntos base.
TOLERANCIA = 0.005


class IdoneidadInvalida(ValueError):
    pass


def _perfil_valido(perfil: str) -> str:
    if perfil not in RIESGO_MAX_POR_PERFIL:
        raise IdoneidadInvalida(
            f"perfil desconocido: {perfil!r}. Opciones: {', '.join(ORDEN_PERFILES)}."
        )
    return perfil


def _normalizar(asignacion: Mapping[str, float]) -> dict[str, float]:
    fuera = sorted(k for k in asignacion if k not in BY_ID)
    if fuera:
        raise IdoneidadInvalida(
            f"instrumentos fuera del catálogo: {', '.join(fuera)}."
        )
    total = float(sum(asignacion.values()))
    if total <= 0:
        raise IdoneidadInvalida("los pesos de la asignación suman cero.")
    return {k: float(v) / total for k, v in asignacion.items() if v > 0}


def perfil_efectivo(perfil: str, origen_clave: str | None = None) -> dict[str, Any]:
    """El perfil que de verdad aplica, ya considerando de donde sale el dinero.

    Con dinero prestado el perfil se topa en conservador: la capacidad de
    aguantar una caida no la define la tolerancia declarada, la define que la
    mensualidad del credito sigue llegando.
    """
    _perfil_valido(perfil)
    fuente = origen_mod.resolver(origen_clave)
    if not fuente.apalancado:
        return {"perfil": perfil, "perfil_declarado": perfil, "topado_por_origen": False}
    tope = origen_mod.TOPE_PERFIL_APALANCADO
    if ORDEN_PERFILES.index(perfil) <= ORDEN_PERFILES.index(tope):
        return {"perfil": perfil, "perfil_declarado": perfil, "topado_por_origen": False}
    return {
        "perfil": tope,
        "perfil_declarado": perfil,
        "topado_por_origen": True,
        "motivo": (
            f"El dinero sale de {fuente.etiqueta.lower()}. Con deuda de por medio "
            f"el perfil aplicable baja de {perfil} a {tope}."
        ),
    }


def rendimiento_esperado_neto(asignacion: Mapping[str, float]) -> float:
    """Rendimiento anual esperado del portafolio, ya descontada la comisión."""
    pesos = _normalizar(asignacion)
    return sum(
        w * (BY_ID[iid].rend_esperado_anual - BY_ID[iid].comision_anual)
        for iid, w in pesos.items()
    )


def exposicion(asignacion: Mapping[str, float]) -> dict[str, Any]:
    """Renta variable total y exposicion EFECTIVA a cada empresa y sector.

    `por_emisora` no es lo que el cliente compro --el cliente compra fondos--
    sino a que empresas quedo expuesto a traves de ellos. `cobertura` dice
    que proporcion del portafolio se pudo mirar por dentro, para no dar una
    falsa sensacion de transparencia cuando la mitad esta en fondos
    internacionales sin desglose.
    """
    pesos = _normalizar(asignacion)
    rv = sum(w for iid, w in pesos.items() if BY_ID[iid].clase in CLASES_RV)
    por_emisora = carteras.exposicion_por_emisora(pesos)
    por_sector = carteras.exposicion_por_sector(pesos)
    riesgo_max = max(BY_ID[iid].riesgo_1a5 for iid in pesos)
    return {
        "rv": round(rv, 6),
        "por_emisora": por_emisora,
        "por_sector": por_sector,
        "cobertura_desglose": carteras.cobertura_desglose(pesos),
        "riesgo_max_instrumento": riesgo_max,
        "riesgo_ponderado": round(
            sum(w * BY_ID[iid].riesgo_1a5 for iid, w in pesos.items()), 3),
    }


def _v(codigo: str, severidad: str, mensaje: str, **extra: Any) -> dict[str, Any]:
    return {"codigo": codigo, "severidad": severidad, "mensaje": mensaje, **extra}


def evaluar(
    asignacion: Mapping[str, float],
    perfil: str,
    horizonte_anios: float,
    *,
    monto: float | None = None,
    origen: str | None = None,
) -> dict[str, Any]:
    """Verifica una asignacion contra el perfil, el horizonte y el origen."""
    pesos = _normalizar(asignacion)
    _perfil_valido(perfil)
    fuente = origen_mod.resolver(origen)
    efectivo = perfil_efectivo(perfil, origen)
    aplicable = efectivo["perfil"]

    hallazgos: list[dict[str, Any]] = []
    exp = exposicion(pesos)

    # ------------------------------------------------- 1. riesgo por instrumento
    tope_riesgo = min(RIESGO_MAX_POR_PERFIL[aplicable], fuente.tope_riesgo_1a5)
    for iid, w in sorted(pesos.items(), key=lambda kv: -kv[1]):
        inst = BY_ID[iid]
        if inst.riesgo_1a5 > tope_riesgo:
            hallazgos.append(_v(
                "instrumento_sobre_perfil", "bloqueante",
                f"{inst.nombre} es riesgo {inst.riesgo_1a5} y un perfil {aplicable} "
                f"admite hasta {tope_riesgo}.",
                instrument_id=iid, peso=round(w, 6),
                riesgo_instrumento=inst.riesgo_1a5, riesgo_maximo=tope_riesgo))

    # ------------------------------------------------ 2. techos de renta variable
    tope_rv = TOPE_RV_POR_PERFIL[aplicable]
    if exp["rv"] > tope_rv + TOLERANCIA:
        hallazgos.append(_v(
            "rv_excedida", "bloqueante",
            f"La propuesta lleva {exp['rv']:.0%} en renta variable y un perfil "
            f"{aplicable} admite hasta {tope_rv:.0%}.",
            observado=exp["rv"], maximo=tope_rv))

    # ------------------------------- 3. concentracion efectiva (look-through)
    tope_emisora = TOPE_LOOKTHROUGH_EMISORA[aplicable]
    for ticker, w in exp["por_emisora"].items():
        if w > tope_emisora + TOLERANCIA:
            emisora = emisoras.POR_TICKER[ticker]
            hallazgos.append(_v(
                "concentracion_emisora", "bloqueante",
                f"A través de los fondos, {w:.1%} del portafolio termina en "
                f"{emisora.nombre}. El máximo por empresa para un perfil "
                f"{aplicable} es {tope_emisora:.0%}. No la compraste directamente, "
                "pero la traes.",
                ticker=ticker, emisora=emisora.nombre,
                observado=round(w, 6), maximo=tope_emisora))

    tope_sector = TOPE_LOOKTHROUGH_SECTOR[aplicable]
    for sector, w in exp["por_sector"].items():
        if w > tope_sector + TOLERANCIA:
            hallazgos.append(_v(
                "concentracion_sector", "aviso",
                f"{w:.1%} del portafolio queda expuesto al sector {sector} a través "
                f"de los fondos (máximo sugerido {tope_sector:.0%}). Las empresas de "
                "un mismo giro caen juntas.",
                sector=sector, observado=round(w, 6), maximo=tope_sector))

    # ------------------------------------------------------- 4. plazo vs horizonte
    horizonte_dias = horizonte_anios * 365
    for iid, w in pesos.items():
        inst = BY_ID[iid]
        if inst.plazo_dias and inst.plazo_dias > horizonte_dias:
            severidad = "bloqueante" if inst.liquidez == "al_vencimiento" else "aviso"
            hallazgos.append(_v(
                "plazo_supera_horizonte", severidad,
                f"{inst.nombre} vence a {inst.plazo_dias} días y el horizonte del "
                f"cliente es de {horizonte_dias:.0f} días"
                + (". No podría sacar el dinero cuando lo necesita."
                   if severidad == "bloqueante"
                   else ". Tendría que venderlo antes, a precio de mercado."),
                instrument_id=iid, plazo_dias=inst.plazo_dias,
                horizonte_dias=round(horizonte_dias)))

    # ------------------------------------------------------------ 5. montos minimos
    if monto is not None:
        for iid, w in pesos.items():
            inst = BY_ID[iid]
            asignado = monto * w
            if asignado + 0.01 < inst.monto_minimo:
                hallazgos.append(_v(
                    "monto_bajo_minimo", "bloqueante",
                    f"A {inst.nombre} le tocan ${asignado:,.2f} y su mínimo es "
                    f"${inst.monto_minimo:,.2f}.",
                    instrument_id=iid, asignado=round(asignado, 2),
                    minimo=inst.monto_minimo))

    # --------------------------------------------------------------- 6. origen
    rend = rendimiento_esperado_neto(pesos)
    umbral = origen_mod.umbral_rentabilidad(fuente)
    if fuente.apalancado:
        if rend <= umbral:
            hallazgos.append(_v(
                "credito_no_rentable", "bloqueante",
                f"El portafolio espera {rend:.2%} anual y el crédito cuesta "
                f"{umbral:.2%}. Invertir con {fuente.etiqueta.lower()} tiene valor "
                f"esperado negativo: pierde {umbral - rend:.2%} al año en promedio.",
                rend_esperado=round(rend, 6), costo_financiero=round(umbral, 6),
                diferencia=round(rend - umbral, 6)))
        else:
            hallazgos.append(_v(
                "credito_apalancado", "aviso",
                f"El portafolio espera {rend:.2%} contra un costo de {umbral:.2%}. "
                "El margen es positivo en promedio, pero la deuda no baja si el "
                "portafolio cae.",
                rend_esperado=round(rend, 6), costo_financiero=round(umbral, 6)))
        if efectivo["topado_por_origen"]:
            hallazgos.append(_v(
                "perfil_topado_por_origen", "aviso", efectivo["motivo"],
                perfil_declarado=perfil, perfil_aplicable=aplicable))
    elif rend <= umbral:
        hallazgos.append(_v(
            "no_supera_referencia", "aviso",
            f"El portafolio espera {rend:.2%} y el dinero ya gana {umbral:.2%} donde "
            "está. Moverlo agrega riesgo sin agregar rendimiento esperado.",
            rend_esperado=round(rend, 6), referencia=round(umbral, 6)))

    bloqueantes = [h for h in hallazgos if h["severidad"] == "bloqueante"]
    avisos = [h for h in hallazgos if h["severidad"] == "aviso"]

    return {
        "apto": not bloqueantes,
        "perfil_declarado": perfil,
        "perfil_aplicable": aplicable,
        "topado_por_origen": efectivo["topado_por_origen"],
        "origen": origen_mod.ficha(fuente),
        "limites": {
            "riesgo_max_instrumento": tope_riesgo,
            "rv_max": tope_rv,
            "max_por_emisora_lookthrough": tope_emisora,
            "max_por_sector_lookthrough": tope_sector,
        },
        "exposicion": exp,
        "rend_esperado_neto": round(rend, 6),
        "umbral_rentabilidad": round(umbral, 6),
        "bloqueantes": bloqueantes,
        "avisos": avisos,
        "resumen": (
            "Asignación apta para el perfil." if not bloqueantes
            else f"{len(bloqueantes)} motivo(s) impiden ejecutar esta asignación."
        ),
    }


def exigir(
    asignacion: Mapping[str, float],
    perfil: str,
    horizonte_anios: float,
    *,
    monto: float | None = None,
    origen: str | None = None,
) -> dict[str, Any]:
    """Como `evaluar`, pero revienta si hay bloqueantes. Lo usa `place_order`."""
    veredicto = evaluar(asignacion, perfil, horizonte_anios,
                        monto=monto, origen=origen)
    if not veredicto["apto"]:
        motivos = "; ".join(h["mensaje"] for h in veredicto["bloqueantes"])
        raise IdoneidadInvalida(
            f"La asignación no es apta para un perfil {veredicto['perfil_aplicable']}: "
            f"{motivos}"
        )
    return veredicto
