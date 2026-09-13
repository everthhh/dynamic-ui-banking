"""Perfil financiero del cliente: quien es, como gana, como gasta y como paga.

Es la base de todas las recomendaciones (`bank/finance/recomendaciones.py`) y
se CALCULA desde lo que el banco ya tiene: movimientos, estados de cuenta de
tarjeta, creditos, saldos, posiciones y el perfil de riesgo. Nada de aqui lo
estima un modelo de lenguaje ni lo captura una persona: si el perfil dice
«paga el minimo» es porque en tantos de sus ultimos cortes pago menos de
tanto, y el perfil trae esas dos cifras.

Funciones puras sobre datos ya leidos (el servicio hace las consultas), para
poder probar cada deduccion con datos armados a mano.

Supuestos que conviene poder discutir, todos como constantes de este modulo:
  * La ventana son los ultimos 12 meses completos antes de la valuacion.
  * Compra «hormiga»: 250 pesos o menos en super, comida, transporte o
    entretenimiento, que no sea suscripcion.
  * Suscripcion: el mismo comercio cobra casi lo mismo (variacion menor a 8%)
    una vez al mes en al menos 4 de los ultimos 6 meses.
  * Efectivo ocioso: lo que hay en la cuenta de inversion sin invertir, mas lo
    que sobra en la cuenta de uso por encima de un mes de salidas.
  * Colchon objetivo: 3 meses de gasto esencial y pagos de deuda con ingreso
    fijo; 6 con ingreso variable.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date
from typing import Any, Callable, Iterable

from bank.categorias import (
    CATEGORIAS_DISCRECIONALES,
    CATEGORIAS_ESENCIALES,
    CATEGORIAS_GASTO,
    CATEGORIAS_INGRESO,
    COSTO_FINANCIERO,
    ETIQUETA_CATEGORIA,
    PAGO_CREDITO,
)
from bank.finance import rules
from bank.instrumentos import CLASES_RV
from bank.mercado import INFLACION_ANUAL, TASA_LIBRE_RIESGO

MESES_VENTANA = 12
TICKET_HORMIGA = 250.0
CATEGORIAS_HORMIGA = frozenset({"super", "restaurantes", "transporte", "entretenimiento"})
MESES_SUSCRIPCION = 6
MIN_MESES_SUSCRIPCION = 4
VARIACION_SUSCRIPCION = 0.08
CV_INGRESO_VARIABLE = 0.12
COLCHON_MESES_FIJO = 3
COLCHON_MESES_VARIABLE = 6
LIQUIDEZ_INMEDIATA = ("diaria", "24h")

PESOS_SALUD_CREDITICIA = {
    "puntualidad": 0.35, "pago_completo": 0.25, "utilizacion": 0.20,
    "carga": 0.12, "antiguedad": 0.08,
}
PESOS_SALUD_FINANCIERA = {
    "ahorro": 0.25, "liquidez": 0.20, "endeudamiento": 0.20,
    "credito": 0.20, "patrimonio_productivo": 0.15,
}

ETIQUETA_CUENTA = {
    "cheques": "Cuenta de cheques", "ahorro": "Cuenta de ahorro",
    "nomina": "Cuenta de nómina", "inversion": "Cuenta de inversión",
}
ETIQUETA_PRESTAMO = {
    "auto": "Crédito automotriz", "hipotecario": "Crédito hipotecario",
    "personal": "Crédito personal", "nomina": "Crédito de nómina",
}
ETIQUETA_HABITO_TDC = {
    "totalero": "Paga su tarjeta completa",
    "revolvente": "Deja saldo en su tarjeta",
    "paga_minimo": "Paga el mínimo de su tarjeta",
    "paga_tarde": "Paga tarde su tarjeta",
    "sin_uso": "No usa su tarjeta de crédito",
}


# ---------------------------------------------------------------------------
# utilidades
# ---------------------------------------------------------------------------
def _r(x: float) -> float:
    return round(float(x), 2)


def _prom(valores: Iterable[float]) -> float:
    vals = list(valores)
    return sum(vals) / len(vals) if vals else 0.0


def _lineal(valor: float, peor: float, mejor: float) -> float:
    """0 en `peor`, 100 en `mejor`, lineal entre los dos (sirve en ambos sentidos)."""
    if mejor == peor:
        return 100.0
    t = (valor - peor) / (mejor - peor)
    return round(100 * min(1.0, max(0.0, t)), 1)


def _dinero(x: float) -> str:
    return f"${x:,.0f}"


def _pct(x: float) -> str:
    return f"{x:.0%}"


def meses_de_ventana(fecha_valuacion: date, meses: int = MESES_VENTANA) -> list[str]:
    """Claves 'YYYY-MM' de los `meses` meses completos antes de la valuacion."""
    y, m = fecha_valuacion.year, fecha_valuacion.month
    claves: list[str] = []
    for _ in range(meses):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        claves.append(f"{y:04d}-{m:02d}")
    return list(reversed(claves))


def _por_mes(movimientos: Iterable[dict[str, Any]], claves: list[str],
             filtro: Callable[[dict[str, Any]], bool]) -> dict[str, float]:
    serie = {k: 0.0 for k in claves}
    for mv in movimientos:
        k = mv["fecha"][:7]
        if k in serie and filtro(mv):
            serie[k] += mv["monto"]
    return serie


def variacion_robusta(valores: Iterable[float]) -> float:
    """MAD sobre mediana, escalada a desviacion estandar.

    Robusta a proposito: un aguinaldo en diciembre es un mes atipico, no un
    ingreso variable. Con la desviacion estandar clasica, cualquier asalariado
    con aguinaldo salia con ingreso «variable».
    """
    vals = list(valores)
    if not vals:
        return 0.0
    mediana = statistics.median(vals)
    if mediana <= 0:
        return 1.0
    mad = statistics.median(abs(v - mediana) for v in vals)
    return round(1.4826 * mad / mediana, 4)


# ---------------------------------------------------------------------------
# patrones de consumo
# ---------------------------------------------------------------------------
def _comercio(mv: dict[str, Any]) -> str:
    return mv.get("comercio") or mv["descripcion"]


def detectar_suscripciones(movimientos: list[dict[str, Any]],
                           claves: list[str]) -> list[dict[str, Any]]:
    """Cargos que se repiten igual cada mes en consumo discrecional.

    Se detectan por comportamiento, no por nombre: mismo comercio, un cargo al
    mes, casi el mismo monto. Renta, colegiatura y servicios tambien se
    repiten, pero no son discrecionales y no se cuentan aqui.
    """
    recientes = set(claves[-MESES_SUSCRIPCION:])
    grupos: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for mv in movimientos:
        if (mv["tipo"] == "cargo" and mv["categoria"] in CATEGORIAS_DISCRECIONALES
                and mv["fecha"][:7] in recientes):
            grupos[_comercio(mv)].append(mv)

    salida = []
    for comercio, movs in grupos.items():
        meses = {m["fecha"][:7] for m in movs}
        if len(meses) < MIN_MESES_SUSCRIPCION or len(movs) > len(meses) * 1.25:
            continue
        montos = [m["monto"] for m in movs]
        mediana = statistics.median(montos)
        if mediana <= 0 or max(abs(x - mediana) for x in montos) / mediana > VARIACION_SUSCRIPCION:
            continue
        ultimo = max(movs, key=lambda m: m["fecha"])
        salida.append({
            "comercio": comercio,
            "descripcion": ultimo["descripcion"],
            "categoria": ultimo["categoria"],
            "monto_mensual": _r(mediana),
            "meses_detectado": len(meses),
            "ultimo_cargo": ultimo["fecha"][:10],
        })
    salida.sort(key=lambda s: (-s["monto_mensual"], s["comercio"]))
    return salida


def detectar_gasto_hormiga(movimientos: list[dict[str, Any]], claves: list[str],
                           suscripciones: list[dict[str, Any]],
                           ingreso_mensual: float) -> dict[str, Any]:
    """Compras chicas y frecuentes: el cafe, la tienda de la esquina, la app."""
    excluir = {s["comercio"] for s in suscripciones}
    ventana = set(claves)
    chicas = [
        mv for mv in movimientos
        if mv["tipo"] == "cargo" and mv["categoria"] in CATEGORIAS_HORMIGA
        and mv["monto"] <= TICKET_HORMIGA and _comercio(mv) not in excluir
        and mv["fecha"][:7] in ventana
    ]
    n = len(claves) or 1
    por_comercio: dict[str, list[float]] = defaultdict(list)
    for mv in chicas:
        por_comercio[_comercio(mv)].append(mv["monto"])
    principales = sorted(
        ({"comercio": c, "compras_mes": round(len(m) / n, 1), "gasto_mensual": _r(sum(m) / n)}
         for c, m in por_comercio.items()),
        key=lambda x: -x["gasto_mensual"])[:3]
    mensual = sum(mv["monto"] for mv in chicas) / n
    return {
        "ticket_maximo": TICKET_HORMIGA,
        "compras_mes": round(len(chicas) / n, 1),
        "gasto_mensual": _r(mensual),
        "gasto_anual": _r(mensual * 12),
        "pct_ingreso": round(mensual / ingreso_mensual, 4) if ingreso_mensual else 0.0,
        "principales": principales,
    }


# ---------------------------------------------------------------------------
# credito
# ---------------------------------------------------------------------------
def comportamiento_tarjeta(tarjeta: dict[str, Any], estados: list[dict[str, Any]],
                          fecha_valuacion: date, claves: list[str]) -> dict[str, Any]:
    """Como paga una tarjeta, leido de sus estados de cuenta.

    Solo cuentan los cortes cuya fecha limite ya paso: un estado de cuenta que
    todavia se puede pagar no dice nada del habito.
    """
    ventana = set(claves)
    propios = sorted((e for e in estados
                      if e["card_id"] == tarjeta["card_id"] and e["fecha_corte"][:7] in ventana),
                     key=lambda e: e["fecha_corte"])
    vencidos = [e for e in propios
                if date.fromisoformat(e["fecha_limite_pago"]) < fecha_valuacion
                and e["saldo_al_corte"] > 0.5]
    cortes = len(vencidos)
    completos = sum(1 for e in vencidos if e["pagado"] >= e["saldo_al_corte"] - 1)
    tardios = sum(1 for e in vencidos
                  if e["fecha_pago"] is None or e["dias_atraso"] > 0
                  or e["pagado"] + 0.5 < e["pago_minimo"])
    minimos = sum(1 for e in vencidos
                  if e["pagado"] < e["saldo_al_corte"] - 1
                  and e["pago_minimo"] - 0.5 <= e["pagado"] <= e["pago_minimo"] * 1.25)

    if cortes == 0:
        habito = "sin_uso"
    elif completos / cortes >= 0.8:
        habito = "totalero"
    elif tardios / cortes >= 0.25:
        habito = "paga_tarde"
    elif minimos / cortes >= 0.5:
        habito = "paga_minimo"
    else:
        habito = "revolvente"

    saldo = float(tarjeta["saldo_utilizado"] or 0)
    limite = float(tarjeta["limite_credito"] or 0)
    tasa = float(tarjeta["tasa_anual"] or 0)
    intereses = sum(e["intereses"] for e in propios)
    comisiones = sum(e["comisiones"] for e in propios)
    return {
        "card_id": tarjeta["card_id"],
        "last4": tarjeta["last4"],
        "alias": tarjeta.get("alias"),
        "limite": _r(limite),
        "saldo": _r(saldo),
        "utilizacion": round(saldo / limite, 4) if limite else 0.0,
        "tasa_anual": tasa,
        "cortes_evaluados": cortes,
        "pagos_completos": completos,
        "pagos_minimos": minimos,
        "pagos_tardios": tardios,
        "meses_con_saldo": cortes - completos,
        "intereses_12m": _r(intereses),
        "comisiones_12m": _r(comisiones),
        "costo_12m": _r(intereses + comisiones),
        "pago_minimo_promedio": _r(_prom(e["pago_minimo"] for e in vencidos)),
        "habito": habito,
        "habito_etiqueta": ETIQUETA_HABITO_TDC[habito],
        # Si deja saldo, lo que costaria mantener el saldo de hoy un ano.
        "intereses_proyectados_anual": (
            _r(saldo * tasa) if habito not in ("totalero", "sin_uso") else 0.0),
    }


def _factor(clave: str, etiqueta: str, valor: float, peso: float, dato: str) -> dict[str, Any]:
    return {"factor": clave, "etiqueta": etiqueta, "valor": round(valor, 1), "peso": peso,
            "aporte": round(valor * peso, 2), "dato": dato}


def _nivel(score: float, cortes: tuple[tuple[float, str], ...]) -> str:
    for minimo, nombre in cortes:
        if score >= minimo:
            return nombre
    return cortes[-1][1]


# ---------------------------------------------------------------------------
# perfil completo
# ---------------------------------------------------------------------------
def construir_perfil(
    *,
    cliente: dict[str, Any],
    cuentas: list[dict[str, Any]],
    tarjetas: list[dict[str, Any]],
    prestamos: list[dict[str, Any]],
    movimientos: list[dict[str, Any]],
    estados_cuenta: list[dict[str, Any]],
    presupuestos: list[dict[str, Any]],
    perfil_riesgo: dict[str, Any] | None,
    posiciones: list[dict[str, Any]],
    fecha_valuacion: date,
    meses: int = MESES_VENTANA,
) -> dict[str, Any]:
    claves = meses_de_ventana(fecha_valuacion, meses)
    ventana = set(claves)
    n = len(claves)
    en_ventana = [mv for mv in movimientos if mv["fecha"][:7] in ventana]
    cargos = [mv for mv in en_ventana if mv["tipo"] == "cargo"]

    # ------------------------------------------------------------------ flujo
    ingreso_mes = _por_mes(en_ventana, claves,
                           lambda m: m["tipo"] == "abono" and m["categoria"] in CATEGORIAS_INGRESO)
    consumo_mes = _por_mes(cargos, claves, lambda m: m["categoria"] in CATEGORIAS_GASTO)
    esencial_mes = _por_mes(cargos, claves, lambda m: m["categoria"] in CATEGORIAS_ESENCIALES)
    credito_mes = _por_mes(cargos, claves, lambda m: m["categoria"] == PAGO_CREDITO)
    costo_mes = _por_mes(cargos, claves, lambda m: m["categoria"] == COSTO_FINANCIERO)
    ahorro_mes = {k: ingreso_mes[k] - consumo_mes[k] - credito_mes[k] - costo_mes[k]
                  for k in claves}

    ingreso = _prom(ingreso_mes.values())
    consumo = _prom(consumo_mes.values())
    esencial = _prom(esencial_mes.values())
    pagos_credito = _prom(credito_mes.values())
    costo_financiero = _prom(costo_mes.values())
    ahorro = ingreso - consumo - pagos_credito - costo_financiero
    tasa_ahorro = ahorro / ingreso if ingreso else 0.0
    variacion_ingreso = variacion_robusta(ingreso_mes.values())
    tipo_ingreso = "variable" if variacion_ingreso >= CV_INGRESO_VARIABLE else "fijo"

    fichas_tdc = [comportamiento_tarjeta(t, estados_cuenta, fecha_valuacion, claves)
                  for t in tarjetas if t["tipo"] == "credito"]
    minimos_obligados = sum(f["pago_minimo_promedio"] for f in fichas_tdc
                            if f["habito"] not in ("totalero", "sin_uso"))
    servicio_deuda = pagos_credito + minimos_obligados
    carga = servicio_deuda / ingreso if ingreso else 0.0

    flujo = {
        "ingreso_mensual_declarado": _r(cliente["ingreso_mensual"]),
        "ingreso_mensual": _r(ingreso),
        "tipo_ingreso": tipo_ingreso,
        "variacion_ingreso": variacion_ingreso,
        "consumo_mensual": _r(consumo),
        "consumo_esencial_mensual": _r(esencial),
        "consumo_discrecional_mensual": _r(consumo - esencial),
        "pagos_credito_mensual": _r(pagos_credito),
        "costo_financiero_mensual": _r(costo_financiero),
        "ahorro_mensual": _r(ahorro),
        "tasa_ahorro": round(tasa_ahorro, 4),
        "meses_con_deficit": sum(1 for v in ahorro_mes.values() if v < 0),
        "servicio_deuda_mensual": _r(servicio_deuda),
        "carga_deuda": round(carga, 4),
        "serie": [
            {"mes": k, "ingreso": _r(ingreso_mes[k]), "consumo": _r(consumo_mes[k]),
             "deuda": _r(credito_mes[k] + costo_mes[k]), "ahorro": _r(ahorro_mes[k])}
            for k in claves
        ],
    }

    # ---------------------------------------------------------------- consumo
    por_categoria = []
    for cat in sorted(CATEGORIAS_GASTO):
        serie = _por_mes(cargos, claves, lambda m, c=cat: m["categoria"] == c)
        total = sum(serie.values())
        if total <= 0:
            continue
        movs_cat = [m for m in cargos if m["categoria"] == cat]
        # La tendencia compara MEDIANAS de 3 meses, no promedios: un viaje o
        # unos boletos sueltos son un mes atipico, no un habito nuevo. Con
        # promedios, un solo pago de agencia de viajes salia como «+169%».
        ultimos = statistics.median(serie[k] for k in claves[-3:])
        previos = statistics.median(serie[k] for k in claves[-6:-3])
        por_categoria.append({
            "categoria": cat,
            "etiqueta": ETIQUETA_CATEGORIA[cat],
            "esencial": cat in CATEGORIAS_ESENCIALES,
            "promedio_mensual": _r(total / n),
            "participacion": round(total / (consumo * n), 4) if consumo else 0.0,
            "compras_mes": round(len(movs_cat) / n, 1),
            "ultimo_mes": _r(serie[claves[-1]]),
            "mediana_ultimos_3": _r(ultimos),
            "mediana_previos_3": _r(previos),
            "tendencia": round(ultimos / previos - 1, 4) if previos > 0 else None,
            "con_tarjeta_credito": round(
                sum(m["monto"] for m in movs_cat if m.get("card_id")) / total, 4),
        })
    por_categoria.sort(key=lambda c: -c["promedio_mensual"])

    suscripciones = detectar_suscripciones(en_ventana, claves)
    total_subs = sum(s["monto_mensual"] for s in suscripciones)
    hormiga = detectar_gasto_hormiga(en_ventana, claves, suscripciones, ingreso)
    consumo_tdc = sum(m["monto"] for m in cargos
                      if m.get("card_id") and m["categoria"] in CATEGORIAS_GASTO)
    consumo_info = {
        "por_categoria": por_categoria,
        "suscripciones": {
            "detectadas": suscripciones,
            "total_mensual": _r(total_subs),
            "total_anual": _r(total_subs * 12),
        },
        "gasto_hormiga": hormiga,
        "pct_con_tarjeta_credito": round(consumo_tdc / (consumo * n), 4) if consumo else 0.0,
        "presupuestos": [
            {"categoria": p["categoria"], "monto_mensual": _r(p["monto_mensual"])}
            for p in presupuestos
        ],
    }

    # --------------------------------------------------------------- credito
    deuda_prestamos = sum(p["saldo_insoluto"] for p in prestamos)
    deuda_tdc = sum(f["saldo"] for f in fichas_tdc)
    linea = sum(f["limite"] for f in fichas_tdc)
    utilizacion = deuda_tdc / linea if linea else 0.0
    cortes = sum(f["cortes_evaluados"] for f in fichas_tdc)
    tardios = sum(f["pagos_tardios"] for f in fichas_tdc)
    completos = sum(f["pagos_completos"] for f in fichas_tdc)
    alta = date.fromisoformat(cliente["fecha_alta"])
    antiguedad = (fecha_valuacion - alta).days / 365.25

    factores_credito = [
        _factor("puntualidad", "Pagos a tiempo",
                100.0 if cortes == 0 else 100 * (1 - tardios / cortes),
                PESOS_SALUD_CREDITICIA["puntualidad"],
                f"{cortes - tardios} de {cortes} cortes a tiempo" if cortes else "sin cortes"),
        _factor("pago_completo", "Pagos completos",
                100.0 if cortes == 0 else 100 * completos / cortes,
                PESOS_SALUD_CREDITICIA["pago_completo"],
                f"{completos} de {cortes} cortes liquidados" if cortes else "sin cortes"),
        _factor("utilizacion", "Uso de la línea", _lineal(utilizacion, 0.90, 0.30),
                PESOS_SALUD_CREDITICIA["utilizacion"], f"{_pct(utilizacion)} de la línea"),
        _factor("carga", "Pagos de deuda sobre ingreso", _lineal(carga, 0.50, 0.10),
                PESOS_SALUD_CREDITICIA["carga"], f"{_pct(carga)} del ingreso"),
        _factor("antiguedad", "Antigüedad como cliente", min(100.0, antiguedad * 10),
                PESOS_SALUD_CREDITICIA["antiguedad"], f"{antiguedad:.1f} años"),
    ]
    score_credito = round(sum(f["aporte"] for f in factores_credito), 1)
    credito = {
        "deuda_total": _r(deuda_prestamos + deuda_tdc),
        "deuda_tarjetas": _r(deuda_tdc),
        "deuda_prestamos": _r(deuda_prestamos),
        "uso_linea_revolvente": round(utilizacion, 4),
        "tarjetas": fichas_tdc,
        "prestamos": [
            {"loan_id": p["loan_id"], "producto": p["producto"],
             "etiqueta": ETIQUETA_PRESTAMO.get(p["producto"], p["producto"]),
             "saldo_insoluto": _r(p["saldo_insoluto"]), "tasa_anual": p["tasa_anual"],
             "pago_mensual": _r(p["pago_mensual"]),
             "mensualidades_restantes": p["plazo_meses"] - p["mensualidades_pagadas"]}
            for p in prestamos
        ],
        "salud_crediticia": {
            "score": score_credito,
            "nivel": _nivel(score_credito, ((80, "excelente"), (65, "buena"),
                                            (45, "regular"), (0, "en riesgo"))),
            "desglose": factores_credito,
        },
    }

    # -------------------------------------------------------------- liquidez
    saldo_vista = sum(c["saldo_disponible"] for c in cuentas
                      if c["tipo"] in ("cheques", "nomina", "ahorro"))
    efectivo_inversion = sum(c["saldo_disponible"] for c in cuentas if c["tipo"] == "inversion")
    invertido = sum(p["valor_mercado"] for p in posiciones)
    invertido_liquido = sum(p["valor_mercado"] for p in posiciones
                            if p.get("liquidez") in LIQUIDEZ_INMEDIATA)
    salidas = consumo + pagos_credito + costo_financiero
    disponible = saldo_vista + efectivo_inversion + invertido_liquido
    gasto_minimo = esencial + servicio_deuda
    meses_colchon = min(99.0, disponible / gasto_minimo) if gasto_minimo else 99.0
    objetivo_meses = COLCHON_MESES_VARIABLE if tipo_ingreso == "variable" else COLCHON_MESES_FIJO
    efectivo_ocioso = efectivo_inversion + max(0.0, saldo_vista - salidas)
    liquidez = {
        "saldo_cuentas": _r(saldo_vista),
        "efectivo_en_inversion": _r(efectivo_inversion),
        "invertido_liquido": _r(invertido_liquido),
        "disponible": _r(disponible),
        "gasto_minimo_mensual": _r(gasto_minimo),
        "salidas_mensuales": _r(salidas),
        "meses_de_colchon": round(meses_colchon, 1),
        "colchon_objetivo_meses": objetivo_meses,
        "colchon_objetivo": _r(objetivo_meses * gasto_minimo),
        "efectivo_ocioso": _r(efectivo_ocioso),
        "rendimiento_no_ganado_anual": _r(efectivo_ocioso * TASA_LIBRE_RIESGO),
        "perdida_poder_compra_anual": _r(efectivo_ocioso * INFLACION_ANUAL),
        "patrimonio_neto": _r(saldo_vista + efectivo_inversion + invertido
                              - deuda_prestamos - deuda_tdc),
    }

    # ------------------------------------------------------------- inversion
    vigente = bool(perfil_riesgo and perfil_riesgo.get("vigente"))
    rv = sum(p["valor_mercado"] for p in posiciones if p["clase"] in CLASES_RV)
    nombre_perfil = perfil_riesgo["perfil"] if perfil_riesgo else None
    inversion = {
        "perfil_riesgo": perfil_riesgo,
        "perfil_vigente": vigente,
        "posiciones": len(posiciones),
        "valor_mercado": _r(invertido),
        "rendimiento": _r(sum(p["valor_mercado"] - p["costo_total"] for p in posiciones)),
        "renta_variable_pct": round(rv / invertido, 4) if invertido else None,
        "renta_variable_objetivo_pct": (
            round(sum(rules.POLITICA[nombre_perfil].get(b, 0.0) for b in rules.BLOQUES_RV), 4)
            if nombre_perfil in rules.POLITICA else None),
        "rend_esperado_actual": (
            round(sum(p["valor_mercado"] * p["rend_esperado_anual"] for p in posiciones)
                  / invertido, 6) if invertido else None),
        "asignacion_actual": (
            {p["instrument_id"]: round(p["valor_mercado"] / invertido, 4) for p in posiciones}
            if invertido else {}),
    }

    # ------------------------------------------------------------- productos
    productos = [{"producto": f"cuenta_{c['tipo']}", "etiqueta": ETIQUETA_CUENTA[c["tipo"]]}
                 for c in cuentas]
    productos += [{"producto": f"tarjeta_{t['tipo']}",
                   "etiqueta": "Tarjeta de crédito" if t["tipo"] == "credito" else "Tarjeta de débito"}
                  for t in tarjetas]
    productos += [{"producto": f"credito_{p['producto']}",
                   "etiqueta": ETIQUETA_PRESTAMO.get(p["producto"], p["producto"])}
                  for p in prestamos]
    if posiciones:
        productos.append({"producto": "fondos_inversion",
                          "etiqueta": f"Fondos de inversión ({len(posiciones)})"})
    if presupuestos:
        productos.append({"producto": "presupuestos",
                          "etiqueta": f"Presupuestos ({len(presupuestos)})"})

    # ------------------------------------------------------------- identidad
    nacimiento = cliente.get("fecha_nacimiento")
    edad = None
    if nacimiento:
        nac = date.fromisoformat(nacimiento)
        edad = fecha_valuacion.year - nac.year - (
            (fecha_valuacion.month, fecha_valuacion.day) < (nac.month, nac.day))
    etapa = None
    if edad is not None:
        etapa = ("inicio de carrera" if edad < 30 else "consolidación" if edad < 45
                 else "madurez patrimonial" if edad < 60 else "pre-retiro")
    nombre_corto = cliente["nombre"].split()[0]
    identidad = {
        "nombre": cliente["nombre"],
        "nombre_corto": nombre_corto,
        "edad": edad,
        "etapa_de_vida": etapa,
        "ocupacion": cliente.get("ocupacion"),
        "dependientes": cliente.get("dependientes", 0),
        "ciudad": cliente["ciudad"],
        "segmento": cliente["segmento"],
        "cliente_desde": cliente["fecha_alta"],
        "antiguedad_anios": round(antiguedad, 1),
    }

    # ------------------------------------------------------ salud financiera
    base_productiva = invertido + efectivo_ocioso
    factores_salud = [
        _factor("ahorro", "Ahorro", _lineal(tasa_ahorro, 0.0, 0.30),
                PESOS_SALUD_FINANCIERA["ahorro"], f"{_pct(tasa_ahorro)} del ingreso"),
        _factor("liquidez", "Colchón para emergencias",
                min(100.0, 100 * meses_colchon / objetivo_meses),
                PESOS_SALUD_FINANCIERA["liquidez"],
                f"{meses_colchon:.1f} de {objetivo_meses} meses"),
        _factor("endeudamiento", "Endeudamiento", _lineal(carga, 0.50, 0.10),
                PESOS_SALUD_FINANCIERA["endeudamiento"], f"{_pct(carga)} del ingreso en deuda"),
        _factor("credito", "Comportamiento de crédito", score_credito,
                PESOS_SALUD_FINANCIERA["credito"], f"{score_credito:.0f}/100"),
        _factor("patrimonio_productivo", "Dinero trabajando",
                100 * invertido / base_productiva if base_productiva > 0 else 50.0,
                PESOS_SALUD_FINANCIERA["patrimonio_productivo"],
                f"{_pct(invertido / base_productiva)} invertido" if base_productiva > 0
                else "sin excedente que invertir"),
    ]
    score_salud = round(sum(f["aporte"] for f in factores_salud), 1)
    salud = {
        "score": score_salud,
        "nivel": _nivel(score_salud, ((75, "sólida"), (55, "estable"), (35, "frágil"),
                                      (0, "en riesgo"))),
        "desglose": factores_salud,
    }

    # ---------------------------------------------------------------- rasgos
    rasgos = _rasgos(flujo, consumo_info, credito, liquidez, inversion)

    return {
        "client_id": cliente["client_id"],
        "fecha_valuacion": fecha_valuacion.isoformat(),
        "ventana": {"meses": n, "desde": claves[0], "hasta": claves[-1]},
        "identidad": identidad,
        "resumen": _resumen(nombre_corto, flujo, len(productos)),
        "salud_financiera": salud,
        "flujo": flujo,
        "consumo": consumo_info,
        "credito": credito,
        "liquidez": liquidez,
        "inversion": inversion,
        "productos": {"total": len(productos), "lista": productos},
        "rasgos": rasgos,
    }


def categorias_con_gasto_creciente(consumo: dict[str, Any], ingreso: float) -> list[dict[str, Any]]:
    """Categorias variables cuyo gasto de los ultimos 3 meses subio de verdad.

    «De verdad» son dos condiciones sobre el mes tipico (mediana): al menos 25%
    mas que en los 3 meses previos, y una diferencia que se note en el
    bolsillo (500 pesos o 2.5% del ingreso). Un +40% sobre 200 pesos no es un
    habito nuevo.
    """
    umbral = max(500.0, 0.025 * ingreso)
    return [
        c for c in consumo["por_categoria"]
        if c["categoria"] not in ("renta", "educacion", "servicios")
        and c["tendencia"] is not None and c["tendencia"] >= 0.25
        and c["mediana_ultimos_3"] - c["mediana_previos_3"] >= umbral
    ]


def _rasgos(flujo: dict[str, Any], consumo: dict[str, Any], credito: dict[str, Any],
            liquidez: dict[str, Any], inversion: dict[str, Any]) -> list[dict[str, Any]]:
    """Etiquetas cortas, cada una con el dato que la sostiene."""
    rasgos: list[dict[str, Any]] = []

    def agrega(clave: str, etiqueta: str, tono: str, dato: str) -> None:
        rasgos.append({"rasgo": clave, "etiqueta": etiqueta, "tono": tono, "dato": dato})

    ingreso = flujo["ingreso_mensual"]
    if flujo["tipo_ingreso"] == "variable":
        agrega("ingreso_variable", "Ingreso variable", "warning",
               f"varía ±{_pct(flujo['variacion_ingreso'])} de un mes a otro")
    else:
        agrega("ingreso_fijo", "Ingreso fijo", "info", f"{_dinero(ingreso)} al mes")

    tasa = flujo["tasa_ahorro"]
    if tasa < 0:
        agrega("deficit", "Gasta más de lo que gana", "danger",
               f"le faltan {_dinero(-flujo['ahorro_mensual'])} al mes")
    elif tasa < 0.10:
        agrega("ahorro_bajo", "Ahorro bajo", "warning", f"ahorra {_pct(tasa)} de su ingreso")
    elif tasa >= 0.20:
        agrega("ahorrador", "Ahorrador", "positive", f"ahorra {_pct(tasa)} de su ingreso")

    peor = None
    orden = ("paga_tarde", "paga_minimo", "revolvente", "totalero")
    for habito in orden:
        peor = next((t for t in credito["tarjetas"] if t["habito"] == habito), None)
        if peor:
            break
    if peor:
        tono = {"totalero": "positive", "revolvente": "warning"}.get(peor["habito"], "danger")
        agrega(peor["habito"], peor["habito_etiqueta"], tono,
               f"{peor['pagos_completos']} de {peor['cortes_evaluados']} cortes liquidados")

    if flujo["carga_deuda"] >= 0.35:
        agrega("endeudamiento_alto", "Endeudamiento alto", "danger",
               f"{_pct(flujo['carga_deuda'])} del ingreso en pagos de deuda")

    if liquidez["efectivo_ocioso"] >= max(10_000.0, liquidez["salidas_mensuales"]):
        agrega("efectivo_ocioso", "Efectivo sin invertir", "warning",
               f"{_dinero(liquidez['efectivo_ocioso'])} sin rendimiento")

    if liquidez["meses_de_colchon"] < liquidez["colchon_objetivo_meses"]:
        agrega("colchon_insuficiente", "Colchón corto", "warning",
               f"{liquidez['meses_de_colchon']:.1f} meses de gastos básicos")

    for c in categorias_con_gasto_creciente(consumo, ingreso)[:2]:
        agrega(f"gasto_creciente_{c['categoria']}", f"Más gasto en {c['etiqueta'].lower()}",
               "warning", f"+{_pct(c['tendencia'])} en los últimos 3 meses")

    if consumo["gasto_hormiga"]["pct_ingreso"] >= 0.08:
        agrega("gasto_hormiga", "Gasto hormiga alto", "warning",
               f"{consumo['gasto_hormiga']['compras_mes']:.0f} compras chicas al mes")

    subs = consumo["suscripciones"]
    if len(subs["detectadas"]) >= 4:
        agrega("suscripciones", f"{len(subs['detectadas'])} suscripciones", "info",
               f"{_dinero(subs['total_mensual'])} al mes")

    perfil = inversion["perfil_riesgo"]
    if inversion["perfil_vigente"]:
        agrega("inversionista", f"Inversionista {perfil['perfil']}", "info",
               f"score {perfil['score']}")
    elif perfil:
        agrega("perfil_vencido", "Perfil de inversión vencido", "warning",
               f"venció el {perfil['vigente_hasta']}")
    else:
        agrega("sin_perfil", "Sin perfil de inversión", "neutral", "nunca lo ha contestado")
    return rasgos


def _resumen(nombre: str, flujo: dict[str, Any], productos: int) -> str:
    """Una frase con los numeros que importan. Plantilla, no redaccion libre."""
    ingreso = flujo["ingreso_mensual"]
    partes = [f"{nombre} gana {_dinero(ingreso)} al mes"
              + (" (ingreso variable)" if flujo["tipo_ingreso"] == "variable" else "")
              + f" y gasta {_dinero(flujo['consumo_mensual'])} en consumo"
              + (f" ({_pct(flujo['consumo_mensual'] / ingreso)})" if ingreso else "")]
    deuda = flujo["pagos_credito_mensual"] + flujo["costo_financiero_mensual"]
    if deuda > 0:
        partes.append(f"a créditos, intereses y comisiones se le van {_dinero(deuda)}")
    texto = "; ".join(partes) + ". "
    if flujo["ahorro_mensual"] >= 0:
        texto += (f"Le quedan {_dinero(flujo['ahorro_mensual'])} al mes "
                  f"({_pct(flujo['tasa_ahorro'])} de su ingreso). ")
    else:
        texto += f"Gasta más de lo que gana: le faltan {_dinero(-flujo['ahorro_mensual'])} al mes. "
    texto += f"Usa {productos} productos del banco."
    return texto
