"""Recomendaciones: que le conviene hacer a ESTE cliente, en que orden y con que.

Cada regla lee el perfil financiero (`bank/finance/perfil.py`) y, si aplica,
devuelve una recomendacion con cuatro cosas que no se negocian:

  * la EVIDENCIA: las cifras del perfil que la disparan, para poder contestar
    «¿por que me recomiendas esto?» sin inventar nada;
  * el IMPACTO en pesos, con su supuesto declarado (tasa de CETES, tasa de la
    tarjeta, recortar a la mitad...);
  * la PRIORIDAD, con una formula que se puede auditar: urgencia, mas el
    tamano del impacto frente al ingreso, menos una penalizacion si la
    herramienta todavia no existe;
  * la HERRAMIENTA del catalogo que la resuelve.

Los textos son plantillas con los numeros del perfil, no redaccion libre. El
agente puede explicar una recomendacion con sus palabras, pero las cifras y el
orden los pone el banco.

El catalogo de herramientas vive aqui como concepto de negocio: lo que el
banco ofrece. Con que tools de servicio se resuelve cada una esta en
`services/profile.py`, y con que componentes se pinta, en `agent/prompts.py`.
Cada capa sabe solo lo suyo, y un test verifica que las tres digan lo mismo.
"""

from __future__ import annotations

import math
from typing import Any, NamedTuple

from bank.finance import deuda, rules
from bank.finance.perfil import categorias_con_gasto_creciente
from bank.mercado import TASA_LIBRE_RIESGO


class Herramienta(NamedTuple):
    herramienta_id: str
    nombre: str
    descripcion: str
    dominio: str                 # inversiones | banca_personal | credito
    disponible: bool             # False: esta en el catalogo, aun no se construye


HERRAMIENTAS: tuple[Herramienta, ...] = (
    Herramienta("perfilador_inversion", "Perfil de inversionista",
                "Cuatro preguntas para saber cuánto riesgo tiene sentido para ti.",
                "inversiones", True),
    Herramienta("propuesta_inversion", "Propuesta de inversión",
                "Una asignación en fondos verificada contra tu perfil, con escenarios.",
                "inversiones", True),
    Herramienta("simulador_aportaciones", "Simulador de ahorro mensual",
                "Cuánto juntarías invirtiendo una cantidad fija cada mes.",
                "inversiones", True),
    Herramienta("comparador_portafolios", "Comparador de portafolios",
                "Tu portafolio contra el que corresponde a tu perfil, con los mismos supuestos.",
                "inversiones", True),
    Herramienta("presupuestos", "Presupuestos por categoría",
                "Un tope mensual por categoría y aviso cuando lo rebasas.",
                "banca_personal", True),
    Herramienta("analisis_gasto", "Análisis de gasto",
                "En qué se va tu dinero, categoría por categoría.",
                "banca_personal", True),
    Herramienta("buscador_movimientos", "Buscador de movimientos",
                "Encuentra cargos por comercio, monto o fecha.",
                "banca_personal", True),
    Herramienta("control_tarjetas", "Control de tarjetas",
                "Bloqueo, límite y apodo de tus tarjetas.",
                "banca_personal", True),
    Herramienta("plan_pago_tarjeta", "Plan para liquidar tu tarjeta",
                "Cuánto pagar al mes, cuánto tardas y cuánto ahorras contra pagar el mínimo.",
                "credito", True),
    Herramienta("domiciliacion_pago", "Domiciliación del pago de tarjeta",
                "Pago automático en la fecha límite para no volver a pagar tarde.",
                "credito", False),
    Herramienta("refinanciamiento", "Consolidación de deudas",
                "Juntar tus deudas caras en un solo crédito de menor tasa.",
                "credito", False),
)
POR_ID: dict[str, Herramienta] = {h.herramienta_id: h for h in HERRAMIENTAS}

# ------------------------------------------------------------------ prioridad
PUNTOS_URGENCIA = {"alta": 50, "media": 30, "baja": 15}
PUNTOS_POR_IMPACTO = 200         # 2 puntos por cada 1% del ingreso anual...
TOPE_PUNTOS_IMPACTO = 40         # ...hasta 40
PENALIZACION_NO_DISPONIBLE = 15

CRITERIO_PRIORIDAD = (
    "urgencia (alta 50, media 30, baja 15) + impacto frente al ingreso anual "
    "(2 puntos por cada 1%, hasta 40) − 15 si la herramienta aún no está disponible"
)

# ------------------------------------------------------------------- umbrales
MESES_PLAN_TARJETA = 12
MINIMO_EFECTIVO_OCIOSO = 10_000.0
TOPE_CARGA_DEUDA = 0.35
DESALINEACION_RV = 0.20
PRESUPUESTABLES = frozenset({"super", "restaurantes", "transporte", "salud", "entretenimiento"})


def prioridad(urgencia: str, impacto_relativo: float, disponible: bool) -> int:
    """0-100. «¿Por que esta va primero?» tiene respuesta con numeros."""
    puntos = PUNTOS_URGENCIA[urgencia] + min(
        TOPE_PUNTOS_IMPACTO, max(0.0, impacto_relativo) * PUNTOS_POR_IMPACTO)
    if not disponible:
        puntos -= PENALIZACION_NO_DISPONIBLE
    return int(round(min(100.0, max(0.0, puntos))))


# -------------------------------------------------------------------- formato
def _dinero(x: float) -> str:
    return f"${x:,.0f}"


def _pct(x: float, decimales: int = 0) -> str:
    return f"{x:.{decimales}%}"


def _sin_sim(nombre: str) -> str:
    return nombre.replace(" (sim)", "")


def _dato(etiqueta: str, valor: Any, formato: str = "moneda") -> dict[str, Any]:
    return {"etiqueta": etiqueta, "valor": valor, "formato": formato}


def _ingreso_anual(perfil: dict[str, Any]) -> float:
    return max(1.0, perfil["flujo"]["ingreso_mensual"] * 12)


def _recomendacion(*, recomendacion_id: str, titulo: str, descripcion: str,
                   evidencia: list[dict[str, Any]], impacto_valor: float,
                   impacto_etiqueta: str, periodo: str, supuesto: str | None,
                   impacto_relativo: float, urgencia: str, herramienta_id: str,
                   parametros: dict[str, Any], prompt: str) -> dict[str, Any]:
    h = POR_ID[herramienta_id]
    return {
        "recomendacion_id": recomendacion_id,
        "titulo": titulo,
        "descripcion": descripcion,
        "evidencia": [e for e in evidencia if e["valor"] is not None],
        "impacto": {"valor": round(impacto_valor, 2), "etiqueta": impacto_etiqueta,
                    "periodo": periodo, "supuesto": supuesto},
        "urgencia": urgencia,
        "prioridad": prioridad(urgencia, impacto_relativo, h.disponible),
        "herramienta": h._asdict(),
        "parametros": parametros,
        "prompt": prompt,
    }


def _tarjetas_con_costo(perfil: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for t in perfil["credito"]["tarjetas"]
            if t["habito"] in ("revolvente", "paga_minimo", "paga_tarde")
            and t["saldo"] > 0 and t["costo_12m"] > 0]


# ---------------------------------------------------------------------- reglas
def regla_liquidar_tarjeta(perfil: dict[str, Any]) -> list[dict[str, Any]]:
    salida = []
    ingreso_anual = _ingreso_anual(perfil)
    ocioso = perfil["liquidez"]["efectivo_ocioso"]
    for t in _tarjetas_con_costo(perfil):
        pago = deuda.pago_para_liquidar(t["saldo"], t["tasa_anual"], MESES_PLAN_TARJETA)
        plan = deuda.plan_pago_fijo(t["saldo"], t["tasa_anual"], pago)
        minimo = deuda.plan_pago_minimo(t["saldo"], t["tasa_anual"])
        ahorro = max(0.0, minimo["total_intereses"] - plan["total_intereses"])
        descripcion = (
            f"Pagaste completo {t['pagos_completos']} de tus últimos {t['cortes_evaluados']} "
            f"cortes y en 12 meses te cobraron {_dinero(t['costo_12m'])} de intereses y "
            f"comisiones. Pagando solo el mínimo tardarías {minimo['meses']} meses en "
            f"liquidar {_dinero(t['saldo'])}.")
        if ocioso >= t["saldo"]:
            descripcion += f" Tienes {_dinero(ocioso)} sin invertir: alcanza para liquidarla hoy."
        salida.append(_recomendacion(
            recomendacion_id=f"liquidar_tarjeta_{t['card_id']}",
            titulo=f"Liquida tu tarjeta •••• {t['last4']}: cobra {_pct(t['tasa_anual'])} al año",
            descripcion=descripcion,
            evidencia=[
                _dato("Saldo de la tarjeta", t["saldo"]),
                _dato("Tasa anual", t["tasa_anual"], "porcentaje"),
                _dato("Intereses y comisiones en 12 meses", t["costo_12m"]),
                _dato("Cortes pagados completos",
                      f"{t['pagos_completos']} de {t['cortes_evaluados']}", "texto"),
            ],
            impacto_valor=ahorro,
            impacto_etiqueta=f"Intereses que te ahorras liquidándola en {MESES_PLAN_TARJETA} "
                             "meses en lugar de pagar el mínimo",
            periodo="total",
            supuesto="Sin compras nuevas mientras la liquidas; mínimo = 5% del saldo más intereses.",
            impacto_relativo=t["intereses_proyectados_anual"] / ingreso_anual,
            urgencia="alta" if (t["habito"] in ("paga_minimo", "paga_tarde")
                                or t["costo_12m"] >= 0.02 * ingreso_anual) else "media",
            herramienta_id="plan_pago_tarjeta",
            parametros={"card_id": t["card_id"], "pago_mensual_sugerido": round(pago, 2),
                        "meses_objetivo": MESES_PLAN_TARJETA},
            prompt=f"Quiero un plan para liquidar mi tarjeta terminación {t['last4']}",
        ))
    return salida


def regla_pagos_tardios(perfil: dict[str, Any]) -> list[dict[str, Any]]:
    salida = []
    for t in perfil["credito"]["tarjetas"]:
        if t["pagos_tardios"] < 2:
            continue
        salida.append(_recomendacion(
            recomendacion_id=f"pagos_tardios_{t['card_id']}",
            titulo=f"Domicilia el pago de tu tarjeta •••• {t['last4']}",
            descripcion=(
                f"Pagaste tarde o por debajo del mínimo {t['pagos_tardios']} de tus últimos "
                f"{t['cortes_evaluados']} cortes. Eso te costó {_dinero(t['comisiones_12m'])} "
                "en comisiones y queda registrado en tu historial de crédito."),
            evidencia=[
                _dato("Pagos tardíos o incompletos",
                      f"{t['pagos_tardios']} de {t['cortes_evaluados']}", "texto"),
                _dato("Comisiones en 12 meses", t["comisiones_12m"]),
                _dato("Salud crediticia", perfil["credito"]["salud_crediticia"]["score"], "numero"),
            ],
            impacto_valor=t["comisiones_12m"],
            impacto_etiqueta="Comisiones que dejarías de pagar al año",
            periodo="anual",
            supuesto="Con el pago domiciliado cada mes en la fecha límite.",
            impacto_relativo=t["comisiones_12m"] / _ingreso_anual(perfil),
            urgencia="alta",
            herramienta_id="domiciliacion_pago",
            parametros={"card_id": t["card_id"]},
            prompt=f"¿Cómo evito pagar tarde mi tarjeta terminación {t['last4']}?",
        ))
    return salida


def regla_carga_deuda(perfil: dict[str, Any]) -> list[dict[str, Any]]:
    flujo = perfil["flujo"]
    if flujo["carga_deuda"] < TOPE_CARGA_DEUDA:
        return []
    return [_recomendacion(
        recomendacion_id="carga_deuda_alta",
        titulo=f"Tus pagos de deuda se llevan {_pct(flujo['carga_deuda'])} de tu ingreso",
        descripcion=(
            f"Pagas {_dinero(flujo['servicio_deuda_mensual'])} al mes entre créditos y mínimos "
            f"de tarjeta. Arriba de {_pct(TOPE_CARGA_DEUDA)} cualquier imprevisto se vuelve un "
            "atraso: no tomes deuda nueva y considera juntar la más cara en un crédito de "
            "menor tasa."),
        evidencia=[
            _dato("Pagos de deuda al mes", flujo["servicio_deuda_mensual"]),
            _dato("Parte de tu ingreso", flujo["carga_deuda"], "porcentaje"),
            _dato("Deuda total", perfil["credito"]["deuda_total"]),
        ],
        impacto_valor=flujo["servicio_deuda_mensual"],
        impacto_etiqueta="Pagos de deuda al mes",
        periodo="mensual",
        supuesto=None,
        impacto_relativo=flujo["carga_deuda"] - 0.30,
        urgencia="alta",
        herramienta_id="refinanciamiento",
        parametros={},
        prompt="¿Cómo bajo lo que pago de deudas cada mes?",
    )]


def regla_efectivo_ocioso(perfil: dict[str, Any]) -> list[dict[str, Any]]:
    liq, flujo, inv = perfil["liquidez"], perfil["flujo"], perfil["inversion"]
    ocioso = liq["efectivo_ocioso"]
    if ocioso < max(MINIMO_EFECTIVO_OCIOSO, liq["salidas_mensuales"]):
        return []
    vigente = inv["perfil_vigente"]
    deuda_tarjetas = sum(t["saldo"] for t in _tarjetas_con_costo(perfil))
    # Con deuda cara, invertir va DESPUES de liquidar. Pero si el efectivo
    # alcanza para las dos cosas, no hay conflicto: se paga y se invierte el resto.
    deuda_primero = deuda_tarjetas > 0 and ocioso < 2 * deuda_tarjetas
    monto = math.floor(ocioso / 1000) * 1000
    colchon_corto = liq["meses_de_colchon"] < liq["colchon_objetivo_meses"]

    descripcion = (
        f"Es dinero que no rinde nada: a tasa de CETES serían "
        f"{_dinero(liq['rendimiento_no_ganado_anual'])} al año, y la inflación le quita "
        f"{_dinero(liq['perdida_poder_compra_anual'])} de poder de compra.")
    if colchon_corto:
        descripcion += (" Una parte debe quedarse disponible como colchón: la propuesta puede "
                        "ir a un fondo de liquidez diaria.")
    if deuda_primero:
        descripcion += " Antes, liquida tu tarjeta: cobra más de lo que rinde cualquier inversión."
    elif deuda_tarjetas:
        descripcion += (f" Usa {_dinero(deuda_tarjetas)} para liquidar tu tarjeta —cobra más de "
                        "lo que rinde cualquier inversión— y pon el resto a trabajar.")
    if not vigente and not deuda_primero:
        anterior = inv["perfil_riesgo"]
        descripcion += (
            f" Tu perfil de inversionista venció el {anterior['vigente_hasta']}: actualízalo, "
            "son cuatro preguntas." if anterior else
            " Primero hay que conocer tu perfil de inversionista: son cuatro preguntas.")

    urgencia = "alta" if ocioso >= 3 * flujo["ingreso_mensual"] else "media"
    if deuda_primero:
        urgencia = "baja"
    return [_recomendacion(
        recomendacion_id="invertir_efectivo_ocioso",
        titulo=f"Tienes {_dinero(ocioso)} sin invertir",
        descripcion=descripcion,
        evidencia=[
            _dato("En tu cuenta de inversión, sin invertir", liq["efectivo_en_inversion"]),
            _dato("En tu cuenta, arriba de un mes de gastos",
                  round(max(0.0, ocioso - liq["efectivo_en_inversion"]), 2)),
            _dato("Equivale a meses de tus gastos",
                  round(ocioso / liq["salidas_mensuales"], 1) if liq["salidas_mensuales"] else None,
                  "numero"),
        ],
        impacto_valor=liq["rendimiento_no_ganado_anual"],
        impacto_etiqueta="Lo que dejas de ganar al año",
        periodo="anual",
        supuesto=f"Tasa de CETES 28 días ({_pct(TASA_LIBRE_RIESGO, 2)}), antes de impuestos.",
        impacto_relativo=liq["rendimiento_no_ganado_anual"] / _ingreso_anual(perfil),
        urgencia=urgencia,
        herramienta_id="propuesta_inversion" if vigente else "perfilador_inversion",
        parametros={"monto": monto, "liquidez_requerida": colchon_corto},
        prompt=(f"Quiero invertir {_dinero(monto)} que tengo sin invertir" if vigente
                else f"Tengo {_dinero(monto)} sin invertir, ¿qué hago con ellos?"),
    )]


def regla_fondo_emergencia(perfil: dict[str, Any]) -> list[dict[str, Any]]:
    liq, flujo, inv = perfil["liquidez"], perfil["flujo"], perfil["inversion"]
    objetivo = liq["colchon_objetivo_meses"]
    faltante = liq["colchon_objetivo"] - liq["disponible"]
    if liq["meses_de_colchon"] >= objetivo or faltante < 1000:
        return []
    aportacion = math.ceil(faltante / 12 / 100) * 100
    alcanza = flujo["ahorro_mensual"] >= aportacion
    descripcion = (
        f"Tu dinero disponible cubre {liq['meses_de_colchon']:.1f} meses de gastos básicos y "
        f"pagos de deuda; con ingreso {flujo['tipo_ingreso']} lo prudente son {objetivo}. ")
    if alcanza:
        descripcion += f"Apartando {_dinero(aportacion)} al mes lo completas en un año."
        herramienta = "simulador_aportaciones" if inv["perfil_vigente"] else "perfilador_inversion"
    else:
        descripcion += (f"Hoy no te sobran {_dinero(aportacion)} al mes para apartar: el primer "
                        "paso es encontrar qué gasto recortar.")
        herramienta = "analisis_gasto"
    return [_recomendacion(
        recomendacion_id="fondo_emergencia",
        titulo="Arma tu fondo de emergencia",
        descripcion=descripcion,
        evidencia=[
            _dato("Dinero disponible", liq["disponible"]),
            _dato("Gastos básicos y deuda al mes", liq["gasto_minimo_mensual"]),
            _dato("Meses cubiertos", liq["meses_de_colchon"], "numero"),
        ],
        impacto_valor=faltante,
        impacto_etiqueta="Te falta para tu colchón",
        periodo="total",
        supuesto=f"{objetivo} meses de gasto esencial más pagos de deuda.",
        impacto_relativo=faltante / _ingreso_anual(perfil),
        urgencia="alta" if liq["meses_de_colchon"] < 1 else "media",
        herramienta_id=herramienta,
        parametros={"monto_objetivo": liq["colchon_objetivo"], "aportacion_mensual": aportacion,
                    "liquidez_requerida": True},
        prompt="Quiero armar mi fondo de emergencia",
    )]


def regla_presupuestos(perfil: dict[str, Any]) -> list[dict[str, Any]]:
    consumo, flujo = perfil["consumo"], perfil["flujo"]
    ingreso_anual = _ingreso_anual(perfil)
    topes = {p["categoria"]: p["monto_mensual"] for p in consumo["presupuestos"]}
    por_categoria = {c["categoria"]: c for c in consumo["por_categoria"]}
    salida = []

    for categoria, tope in sorted(topes.items()):
        c = por_categoria.get(categoria)
        if not c or c["mediana_ultimos_3"] <= tope * 1.05:
            continue
        exceso = c["mediana_ultimos_3"] - tope
        etiqueta = c["etiqueta"].lower()
        salida.append(_recomendacion(
            recomendacion_id=f"presupuesto_rebasado_{categoria}",
            titulo=f"Tu presupuesto de {etiqueta} ya no alcanza",
            descripcion=(
                f"Pusiste un tope de {_dinero(tope)} al mes y en un mes típico de los últimos "
                f"tres gastaste {_dinero(c['mediana_ultimos_3'])}. O ajustas el tope a lo real "
                f"o recortas {_dinero(exceso)} al mes."),
            evidencia=[
                _dato("Tu presupuesto", tope),
                _dato("Mes típico de los últimos 3", c["mediana_ultimos_3"]),
                _dato("Último mes", c["ultimo_mes"]),
            ],
            impacto_valor=exceso * 12,
            impacto_etiqueta="Lo que rebasas al año",
            periodo="anual",
            supuesto="Si sigues gastando lo de un mes típico reciente.",
            impacto_relativo=exceso * 12 / ingreso_anual,
            urgencia="alta" if exceso >= 0.05 * flujo["ingreso_mensual"] else "media",
            herramienta_id="presupuestos",
            parametros={"categoria": categoria, "presupuesto_actual": tope,
                        "gasto_reciente": c["mediana_ultimos_3"]},
            prompt=f"Ayúdame a ajustar mi presupuesto de {etiqueta}",
        ))

    for c in categorias_con_gasto_creciente(consumo, flujo["ingreso_mensual"]):
        if c["categoria"] in topes or c["categoria"] not in PRESUPUESTABLES:
            continue
        diferencia = c["mediana_ultimos_3"] - c["mediana_previos_3"]
        sugerido = round(c["mediana_previos_3"] / 100) * 100
        etiqueta = c["etiqueta"].lower()
        salida.append(_recomendacion(
            recomendacion_id=f"gasto_creciente_{c['categoria']}",
            titulo=f"Tu gasto en {etiqueta} subió {_pct(c['tendencia'])}",
            descripcion=(
                f"En un mes típico de los últimos tres gastaste "
                f"{_dinero(c['mediana_ultimos_3'])} en {etiqueta}, contra "
                f"{_dinero(c['mediana_previos_3'])} en los tres anteriores. Un presupuesto de "
                f"{_dinero(sugerido)} te regresa a donde estabas."),
            evidencia=[
                _dato("Mes típico, últimos 3", c["mediana_ultimos_3"]),
                _dato("Mes típico, 3 anteriores", c["mediana_previos_3"]),
                _dato("Variación", c["tendencia"], "porcentaje"),
            ],
            impacto_valor=diferencia * 12,
            impacto_etiqueta="Lo que ahorras al año si vuelves al gasto anterior",
            periodo="anual",
            supuesto=None,
            impacto_relativo=diferencia * 12 / ingreso_anual,
            urgencia="media",
            herramienta_id="presupuestos",
            parametros={"categoria": c["categoria"], "monto_sugerido": sugerido},
            prompt=f"Quiero ponerle un presupuesto a {etiqueta}",
        ))
    return salida


def regla_gasto_hormiga(perfil: dict[str, Any]) -> list[dict[str, Any]]:
    h = perfil["consumo"]["gasto_hormiga"]
    if h["pct_ingreso"] < 0.08:
        return []
    principales = ", ".join(f"{_sin_sim(p['comercio']).lower()} ({p['compras_mes']:.0f} al mes)"
                            for p in h["principales"])
    return [_recomendacion(
        recomendacion_id="gasto_hormiga",
        titulo=f"{h['compras_mes']:.0f} compras chicas al mes suman {_dinero(h['gasto_mensual'])}",
        descripcion=(
            f"Son compras de {_dinero(h['ticket_maximo'])} o menos, sobre todo en {principales}. "
            f"Juntas se llevan {_pct(h['pct_ingreso'])} de tu ingreso."),
        evidencia=[
            _dato("Compras chicas al mes", h["compras_mes"], "numero"),
            _dato("Gasto al mes", h["gasto_mensual"]),
            _dato("Parte de tu ingreso", h["pct_ingreso"], "porcentaje"),
        ],
        impacto_valor=h["gasto_anual"] / 2,
        impacto_etiqueta="Lo que ahorras al año si las recortas a la mitad",
        periodo="anual",
        supuesto="Recortar a la mitad el gasto en compras chicas.",
        impacto_relativo=h["gasto_anual"] / 2 / _ingreso_anual(perfil),
        urgencia="media",
        herramienta_id="analisis_gasto",
        parametros={"ticket_maximo": h["ticket_maximo"]},
        prompt="¿En qué se me va el dinero en compras chicas?",
    )]


def regla_suscripciones(perfil: dict[str, Any]) -> list[dict[str, Any]]:
    subs = perfil["consumo"]["suscripciones"]
    detectadas = subs["detectadas"]
    if len(detectadas) < 4 and subs["total_mensual"] < 0.03 * perfil["flujo"]["ingreso_mensual"]:
        return []
    if not detectadas:
        return []
    nombres = ", ".join(s["descripcion"].lower() for s in detectadas[:4])
    if len(detectadas) > 4:
        nombres += "…"
    return [_recomendacion(
        recomendacion_id="revisar_suscripciones",
        titulo=f"Pagas {len(detectadas)} suscripciones: {_dinero(subs['total_anual'])} al año",
        descripcion=(f"Se cobran solas cada mes ({nombres}). Revisa cuáles sigues usando."),
        evidencia=[
            _dato("Suscripciones detectadas", len(detectadas), "numero"),
            _dato("Al mes", subs["total_mensual"]),
            _dato("Al año", subs["total_anual"]),
        ],
        impacto_valor=subs["total_anual"] / 2,
        impacto_etiqueta="Lo que ahorras al año cancelando la mitad",
        periodo="anual",
        supuesto="Cancelar suscripciones por la mitad del monto actual.",
        impacto_relativo=subs["total_anual"] / 2 / _ingreso_anual(perfil),
        urgencia="baja",
        herramienta_id="buscador_movimientos",
        parametros={"comercios": [s["comercio"] for s in detectadas],
                    "categoria": "entretenimiento"},
        prompt="Muéstrame mis suscripciones y cargos recurrentes",
    )]


def regla_portafolio_desalineado(perfil: dict[str, Any]) -> list[dict[str, Any]]:
    inv = perfil["inversion"]
    actual, objetivo = inv["renta_variable_pct"], inv["renta_variable_objetivo_pct"]
    if not inv["perfil_vigente"] or actual is None or objetivo is None:
        return []
    diferencia = actual - objetivo
    if abs(diferencia) < DESALINEACION_RV:
        return []
    nombre = inv["perfil_riesgo"]["perfil"]
    horizonte = max(1.0, inv["perfil_riesgo"]["horizonte_meses"] / 12)
    try:
        propuesta = rules.proponer(nombre, horizonte, inv["valor_mercado"])
    except rules.SinPropuesta:
        return []
    rend_perfil, rend_actual = propuesta["rend_esperado_anual"], inv["rend_esperado_actual"]
    impacto = abs(rend_perfil - rend_actual) * inv["valor_mercado"]
    if diferencia < 0:
        titulo = f"Tu portafolio es más conservador que tu perfil {nombre}"
        descripcion = (
            f"Tienes {_pct(actual)} en renta variable y a tu perfil le corresponde alrededor de "
            f"{_pct(objetivo)}. Con la mezcla de tu perfil, el rendimiento esperado pasa de "
            f"{_pct(rend_actual, 1)} a {_pct(rend_perfil, 1)} al año.")
        etiqueta, urgencia = "Rendimiento esperado adicional al año", "media"
    else:
        titulo = f"Tu portafolio arriesga más de lo que admite tu perfil {nombre}"
        descripcion = (
            f"Tienes {_pct(actual)} en renta variable y a un perfil {nombre} le corresponde "
            f"alrededor de {_pct(objetivo)}. Una caída fuerte te pegaría más de lo que dijiste "
            "que aguantas.")
        etiqueta, urgencia = "Rendimiento esperado que cambia al año", "alta"
    return [_recomendacion(
        recomendacion_id="portafolio_desalineado",
        titulo=titulo,
        descripcion=descripcion,
        evidencia=[
            _dato("Renta variable hoy", actual, "porcentaje"),
            _dato("Renta variable de tu perfil", objetivo, "porcentaje"),
            _dato("Valor de tu portafolio", inv["valor_mercado"]),
        ],
        impacto_valor=impacto,
        impacto_etiqueta=etiqueta,
        periodo="anual",
        supuesto="Rendimientos esperados del catálogo, antes de comisiones e impuestos.",
        impacto_relativo=impacto / _ingreso_anual(perfil),
        urgencia=urgencia,
        herramienta_id="comparador_portafolios",
        parametros={"asignacion_actual": inv["asignacion_actual"],
                    "monto": inv["valor_mercado"], "horizonte_anios": horizonte},
        prompt="Compara mi portafolio actual contra el que corresponde a mi perfil",
    )]


def regla_ahorro_programado(perfil: dict[str, Any]) -> list[dict[str, Any]]:
    flujo, inv = perfil["flujo"], perfil["inversion"]
    if (not inv["perfil_vigente"] or flujo["tasa_ahorro"] < 0.15
            or flujo["meses_con_deficit"] > 1 or flujo["ahorro_mensual"] < 2000):
        return []
    aportacion = math.floor(flujo["ahorro_mensual"] * 0.5 / 500) * 500
    if aportacion < 1000:
        return []
    r, meses = TASA_LIBRE_RIESGO / 12, 60
    valor = aportacion * ((1 + r) ** meses - 1) / r
    rendimiento = valor - aportacion * meses
    return [_recomendacion(
        recomendacion_id="ahorro_programado",
        titulo=f"Invierte {_dinero(aportacion)} cada mes en automático",
        descripcion=(
            f"Te quedan {_dinero(flujo['ahorro_mensual'])} al mes en promedio y en 12 meses "
            + ("no tuviste ningún mes en rojo" if flujo["meses_con_deficit"] == 0
               else "solo tuviste un mes en rojo")
            + f". Si la mitad se invierte sola cada mes, en 5 años juntas {_dinero(valor)}."),
        evidencia=[
            _dato("Ahorro mensual promedio", flujo["ahorro_mensual"]),
            _dato("Tasa de ahorro", flujo["tasa_ahorro"], "porcentaje"),
            _dato("Meses en rojo", flujo["meses_con_deficit"], "numero"),
        ],
        impacto_valor=rendimiento / 5,
        impacto_etiqueta="Rendimiento promedio al año",
        periodo="anual",
        supuesto=(f"Aportación mensual a 5 años a tasa de CETES 28 días "
                  f"({_pct(TASA_LIBRE_RIESGO, 2)}), antes de impuestos. El simulador usa los "
                  "fondos de tu perfil."),
        impacto_relativo=rendimiento / 5 / _ingreso_anual(perfil),
        urgencia="baja",
        herramienta_id="simulador_aportaciones",
        parametros={"aportacion_mensual": aportacion, "horizonte_anios": 5},
        prompt=f"Quiero simular invertir {_dinero(aportacion)} cada mes",
    )]


def regla_actualizar_perfil(perfil: dict[str, Any]) -> list[dict[str, Any]]:
    inv = perfil["inversion"]
    anterior = inv["perfil_riesgo"]
    if inv["perfil_vigente"] or not anterior or not inv["posiciones"]:
        return []
    return [_recomendacion(
        recomendacion_id="actualizar_perfil",
        titulo="Actualiza tu perfil de inversionista",
        descripcion=(
            f"Venció el {anterior['vigente_hasta']}. Mientras no lo actualices no puedes "
            f"contratar ni mover los {_dinero(inv['valor_mercado'])} que tienes en fondos."),
        evidencia=[
            _dato("Perfil anterior", anterior["perfil"], "texto"),
            _dato("Venció", anterior["vigente_hasta"], "texto"),
            _dato("Invertido en fondos", inv["valor_mercado"]),
        ],
        impacto_valor=inv["valor_mercado"],
        impacto_etiqueta="Invertido que hoy no puedes mover",
        periodo="total",
        supuesto=None,
        impacto_relativo=0.05,
        urgencia="media",
        herramienta_id="perfilador_inversion",
        parametros={},
        prompt="Quiero actualizar mi perfil de inversionista",
    )]


REGLAS = (
    regla_liquidar_tarjeta,
    regla_pagos_tardios,
    regla_carga_deuda,
    regla_efectivo_ocioso,
    regla_fondo_emergencia,
    regla_presupuestos,
    regla_gasto_hormiga,
    regla_suscripciones,
    regla_portafolio_desalineado,
    regla_ahorro_programado,
)


def recomendar(perfil: dict[str, Any]) -> list[dict[str, Any]]:
    """Todas las recomendaciones que aplican, de la mas prioritaria a la menos."""
    recomendaciones: list[dict[str, Any]] = []
    for regla in REGLAS:
        recomendaciones.extend(regla(perfil))
    # Si ya se recomienda invertir el efectivo, esa recomendacion menciona el
    # perfil vencido; otra tarjeta para lo mismo es ruido.
    if not any(r["recomendacion_id"] == "invertir_efectivo_ocioso" for r in recomendaciones):
        recomendaciones.extend(regla_actualizar_perfil(perfil))
    recomendaciones.sort(key=lambda r: (-r["prioridad"], r["recomendacion_id"]))
    for orden, r in enumerate(recomendaciones, 1):
        r["orden"] = orden
    return recomendaciones
