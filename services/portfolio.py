"""Servicios de perfilamiento, propuesta y simulacion.

Ningun numero de aqui viene del modelo de lenguaje. El modelo decide QUE
preguntar y COMO presentarlo; los montos, escenarios y metricas salen de
bank/finance.
"""

from __future__ import annotations

import math
import json
import uuid
from datetime import date, timedelta
from typing import Any, Mapping

from bank import carteras, db, emisoras
from bank.finance import compare, idoneidad, montecarlo, risk, rules
from bank.finance import origen as origen_mod
from bank.instrumentos import BY_ID
from services.errors import NotFound, ServiceError

VIGENCIA_PERFIL_DIAS = 365


def _fecha_valuacion(conn) -> date:
    row = db.query_one(conn, "SELECT fecha_valuacion FROM market_params WHERE id = 1")
    return date.fromisoformat(row["fecha_valuacion"]) if row else date.today()


def get_risk_questions() -> dict[str, Any]:
    """Las 4 preguntas del perfilador, en la forma que espera `inv.RiskProfiler`."""
    return {
        "questions": risk.preguntas_para_ui(),
        "total": len(risk.PREGUNTAS),
        "nota": "Las cuatro son obligatorias; el horizonte topa el resultado.",
    }


def score_risk_profile(
    answers: list[dict[str, Any]],
    client_id: str | None = None,
    guardar: bool = True,
) -> dict[str, Any]:
    """Califica las respuestas y, si se pide, deja el perfil vigente en la base."""
    if not isinstance(answers, list) or not answers:
        raise ServiceError(
            "`answers` debe ser una lista de {id, value}.",
            sugerencia="Usa `get_risk_questions` para ver los ids y los valores válidos.",
        )
    try:
        resultado = risk.calificar(answers)
    except risk.RespuestaInvalida as exc:
        raise ServiceError(str(exc),
                           sugerencia="Los valores van de 1 a 5 y las cuatro preguntas "
                                      "son obligatorias.") from exc

    if client_id and guardar:
        with db.session() as conn:
            if db.query_one(conn, "SELECT 1 FROM clients WHERE client_id = ?",
                            (client_id,)) is None:
                raise NotFound(f"No existe el cliente {client_id!r}.")
            hoy = _fecha_valuacion(conn)
            conn.execute(
                "INSERT INTO risk_profiles (profile_id, client_id, score, perfil,"
                " horizonte_meses, respondido_en, vigente_hasta, answers_json)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (f"RSK-{uuid.uuid4().hex[:12]}", client_id, resultado["score"],
                 resultado["perfil"], resultado["horizonte_meses"], hoy.isoformat(),
                 (hoy + timedelta(days=VIGENCIA_PERFIL_DIAS)).isoformat(),
                 json.dumps(answers, ensure_ascii=False)),
            )
        resultado["guardado"] = True
        resultado["client_id"] = client_id
    else:
        resultado["guardado"] = False

    return resultado


def _perfil_guardado(client_id: str) -> dict[str, Any] | None:
    """El ultimo perfil del cliente, con su vigencia ya resuelta."""
    with db.session(readonly=True) as conn:
        if db.query_one(conn, "SELECT 1 FROM clients WHERE client_id = ?",
                        (client_id,)) is None:
            raise NotFound(f"No existe el cliente {client_id!r}.")
        fila = db.query_one(
            conn,
            "SELECT perfil, score, horizonte_meses, vigente_hasta FROM risk_profiles"
            " WHERE client_id = ? ORDER BY respondido_en DESC LIMIT 1", (client_id,))
        if fila is None:
            return None
        hoy = _fecha_valuacion(conn)
        return {**fila,
                "vigente": date.fromisoformat(fila["vigente_hasta"]) >= hoy}


def propose_allocation(
    perfil: str | None = None,
    horizonte_anios: float | None = None,
    monto: float = 0.0,
    liquidez_requerida: bool = False,
    excluir_clases: list[str] | None = None,
    client_id: str | None = None,
    origen: str | None = None,
) -> dict[str, Any]:
    """Asignacion por reglas. Devuelve los `slices` que pinta `inv.AllocationDonut`.

    Si viene `client_id`, el perfil que se usa es el GUARDADO, no el que
    mande el modelo. Esa era la puerta abierta: nada impedia pedir una
    propuesta agresiva para un cliente con score 18. Si el modelo manda un
    perfil distinto al vigente, gana la base y queda escrito en `notas`.
    """
    nota_perfil: str | None = None
    if client_id:
        guardado = _perfil_guardado(client_id)
        if guardado is None or not guardado["vigente"]:
            raise ServiceError(
                f"{client_id} no tiene un perfil de riesgo vigente, así que no puedo "
                "proponer una asignación.",
                sugerencia="Genera `inv.RiskProfiler` con `get_risk_questions` y "
                           "califica las respuestas con `score_risk_profile`.",
            )
        if perfil and perfil != guardado["perfil"]:
            nota_perfil = (
                f"Pediste una propuesta {perfil} pero el perfil vigente de {client_id} "
                f"es {guardado['perfil']} (score {guardado['score']}). Usé el vigente."
            )
        perfil = guardado["perfil"]
        if horizonte_anios is None:
            horizonte_anios = guardado["horizonte_meses"] / 12

    if not perfil:
        raise ServiceError(
            "Falta `perfil`.",
            sugerencia="Pasa `client_id` para tomar el perfil vigente de la base, o "
                       "`perfil` explícito si aún no está guardado.")
    if horizonte_anios is None:
        raise ServiceError("Falta `horizonte_anios`.")

    try:
        propuesta = rules.proponer(
            perfil=perfil,
            horizonte_anios=float(horizonte_anios),
            monto=float(monto),
            liquidez_requerida=bool(liquidez_requerida),
            excluir_clases=tuple(excluir_clases or ()),
            origen=origen,
        )
    except (rules.SinPropuesta, origen_mod.OrigenInvalido) as exc:
        raise ServiceError(str(exc)) from exc
    propuesta["asignacion"] = rules.asignacion_plana(propuesta)
    if nota_perfil:
        propuesta["notas"].insert(0, nota_perfil)
        propuesta["perfil_solicitado_ignorado"] = True
    return propuesta


def _asignacion_desde_entrada(asignacion: Any) -> dict[str, float]:
    """Acepta {'CETES-28': 0.4, ...} o [{'instrument_id':..., 'peso':...}, ...].

    El modelo manda una u otra forma segun de donde copio la asignacion, y
    pelearse con eso en el prompt cuesta mas que aceptar las dos aqui.
    """

    if isinstance(asignacion, Mapping):
        bruto = {str(k): float(v) for k, v in asignacion.items()}
    elif isinstance(asignacion, list):
        bruto = {}
        for item in asignacion:
            if not isinstance(item, Mapping):
                raise ServiceError(
                    "Cada elemento de la asignación debe ser {instrument_id, peso}.")
            iid = item.get("instrument_id") or item.get("id")
            peso = item.get("peso", item.get("weight"))
            if iid is None or peso is None:
                raise ServiceError(
                    "Falta `instrument_id` o `peso` en un elemento de la asignación.")
            bruto[str(iid)] = float(peso)
    else:
        raise ServiceError(
            "`asignacion` debe ser un objeto {instrument_id: peso} o una lista "
            "de {instrument_id, peso}.")

    no_finitos = [k for k, v in bruto.items() if not math.isfinite(v)]
    if no_finitos:
        raise ServiceError(
            f"Pesos no numéricos (NaN/infinito) en: {', '.join(no_finitos)}.")

    fuera = sorted(k for k in bruto if k not in BY_ID)
    if fuera:
        raise ServiceError(
            f"Instrumentos fuera del catálogo: {', '.join(fuera)}.",
            sugerencia="Usa `list_instruments` o `propose_allocation` para obtener IDs válidos.",
        )
    return bruto


def simulate_portfolio(
    asignacion: Any,
    monto: float,
    horizonte_anios: float,
    aportacion_mensual: float = 0.0,
    origen: str | None = None,
    client_id: str | None = None,
) -> dict[str, Any]:
    """Monte Carlo del portafolio. Alimenta `inv.ProjectionChart`.

    Si viene `client_id` con perfil vigente, la simulacion trae adjunto el
    veredicto de idoneidad. Simular no se bloquea nunca --ver el numero malo
    es justo lo que convence a alguien de no hacerlo-- pero el veredicto viaja
    con el resultado para que la UI lo pinte y `place_order` no sea la primera
    vez que alguien se entera.
    """
    pesos = _asignacion_desde_entrada(asignacion)
    try:
        sim = montecarlo.simular(pesos, float(monto), float(horizonte_anios),
                                 float(aportacion_mensual), origen=origen)
    except montecarlo.SimulacionInvalida as exc:
        raise ServiceError(str(exc)) from exc

    if client_id:
        guardado = _perfil_guardado(client_id)
        if guardado and guardado["vigente"]:
            sim["idoneidad"] = idoneidad.evaluar(
                pesos, guardado["perfil"], float(horizonte_anios),
                monto=float(monto), origen=origen)
        else:
            sim["idoneidad"] = {
                "apto": False,
                "resumen": f"{client_id} no tiene perfil de riesgo vigente.",
                "bloqueantes": [{
                    "codigo": "sin_perfil_vigente", "severidad": "bloqueante",
                    "mensaje": "No hay perfil vigente contra el cual verificar "
                               "esta asignación.",
                }],
                "avisos": [],
            }
    return sim


def compare_allocations(
    izquierda: Any,
    derecha: Any,
    monto: float,
    horizonte_anios: float,
    aportacion_mensual: float = 0.0,
    metricas: list[str] | None = None,
    etiqueta_izquierda: str = "Opción A",
    etiqueta_derecha: str = "Opción B",
    origen: str | None = None,
) -> dict[str, Any]:
    """Compara dos asignaciones bajo los mismos supuestos. Alimenta `inv.ComparePanel`."""
    try:
        return compare.comparar(
            _asignacion_desde_entrada(izquierda),
            _asignacion_desde_entrada(derecha),
            float(monto),
            float(horizonte_anios),
            float(aportacion_mensual),
            metricas=tuple(metricas) if metricas else compare.METRICAS_DEFAULT,
            etiqueta_izquierda=etiqueta_izquierda,
            etiqueta_derecha=etiqueta_derecha,
            origen=origen,
        )
    except (compare.ComparacionInvalida, montecarlo.SimulacionInvalida,
            origen_mod.OrigenInvalido) as exc:
        raise ServiceError(str(exc)) from exc


def check_suitability(
    asignacion: Any,
    client_id: str | None = None,
    perfil: str | None = None,
    horizonte_anios: float | None = None,
    monto: float | None = None,
    origen: str | None = None,
) -> dict[str, Any]:
    """Verifica una asignacion contra el perfil, el horizonte y el origen.

    Tool aparte a proposito: el modelo puede preguntar "¿esto es apto?" antes
    de pintar nada, y la respuesta es la MISMA que va a aplicar `place_order`.
    No hay dos criterios.
    """
    pesos = _asignacion_desde_entrada(asignacion)
    if client_id:
        guardado = _perfil_guardado(client_id)
        if guardado is None or not guardado["vigente"]:
            raise ServiceError(
                f"{client_id} no tiene perfil de riesgo vigente.",
                sugerencia="Perfílalo antes con `score_risk_profile`.")
        perfil = guardado["perfil"]
        if horizonte_anios is None:
            horizonte_anios = guardado["horizonte_meses"] / 12
    if not perfil:
        raise ServiceError("Falta `perfil` o `client_id`.")
    if horizonte_anios is None:
        raise ServiceError("Falta `horizonte_anios`.")
    try:
        return idoneidad.evaluar(pesos, perfil, float(horizonte_anios),
                                 monto=float(monto) if monto else None,
                                 origen=origen)
    except (idoneidad.IdoneidadInvalida, origen_mod.OrigenInvalido) as exc:
        raise ServiceError(str(exc)) from exc


def get_issuer_profile(ticker: str) -> dict[str, Any]:
    """Fundamentales de una emisora y el desglose de SU riesgo.

    Es la respuesta a "¿por qué esta empresa es riesgo 5?": no es una
    opinión, es una tabla de seis factores con su peso y su aporte.

    Ojo: esta emisora NO se puede contratar. Es un producto de fondos; la
    empresa aparece porque algún fondo del catálogo la trae dentro. La
    respuesta incluye en qué fondos está y con qué peso.
    """
    if ticker not in emisoras.POR_TICKER:
        raise NotFound(
            f"No existe la emisora {ticker!r}.",
            sugerencia="Emisoras disponibles: "
                       + ", ".join(sorted(emisoras.POR_TICKER)) + ".")
    ficha = emisoras.ficha(ticker)
    ficha["contratable"] = False
    ficha["como_se_invierte"] = {
        "nota": (
            "No se compra directo. Se llega a esta empresa a través de los "
            "fondos que la traen en cartera."
        ),
        "fondos_que_la_traen": [
            {
                "instrument_id": iid,
                "nombre": BY_ID[iid].nombre,
                "peso_en_el_fondo": pesos[ticker],
            }
            for iid, pesos in carteras.COMPOSICION.items() if ticker in pesos
        ],
    }
    return ficha


def get_fund_holdings(
    instrument_id: str | None = None,
    asignacion: Any = None,
) -> dict[str, Any]:
    """Qué empresas hay dentro de un fondo, o dentro de un portafolio entero.

    Con `instrument_id`: el desglose de ese fondo y las cifras que se derivan
    de sus tenencias (volatilidad, beta, concentración, riesgo).

    Con `asignacion`: el look-through del portafolio completo, o sea el peso
    EFECTIVO en cada empresa sumando lo que aporta cada fondo. Es la respuesta
    a "¿en qué empresas está mi dinero?" en un producto donde el cliente nunca
    compró una acción.
    """
    if instrument_id is None and asignacion is None:
        raise ServiceError(
            "Pasa `instrument_id` para ver un fondo o `asignacion` para ver un "
            "portafolio completo.")

    salida: dict[str, Any] = {}

    if instrument_id is not None:
        if instrument_id not in BY_ID:
            raise NotFound(
                f"No existe el instrumento {instrument_id!r}.",
                sugerencia="Usa `list_instruments` para ver los IDs válidos.")
        salida["fondo"] = carteras.ficha(instrument_id)

    if asignacion is not None:
        pesos = _asignacion_desde_entrada(asignacion)
        total = sum(pesos.values()) or 1.0
        normalizados = {k: v / total for k, v in pesos.items()}
        por_emisora = carteras.exposicion_por_emisora(normalizados)
        salida["portafolio"] = {
            "cobertura_desglose": carteras.cobertura_desglose(normalizados),
            "por_emisora": [
                {
                    "ticker": t,
                    "nombre": emisoras.POR_TICKER[t].nombre,
                    "sector": emisoras.POR_TICKER[t].sector,
                    "peso_efectivo": w,
                    "calificacion": emisoras.POR_TICKER[t].calificacion,
                    "riesgo_1a5": emisoras.perfil_riesgo(
                        emisoras.POR_TICKER[t])["riesgo_1a5"],
                }
                for t, w in por_emisora.items()
            ],
            "por_sector": carteras.exposicion_por_sector(normalizados),
            "sin_desglose": [
                {"instrument_id": i, "peso": round(w, 6),
                 "motivo": carteras.SIN_DESGLOSE.get(
                     i, "No invierte en acciones de la BMV.")}
                for i, w in normalizados.items()
                if not carteras.tiene_desglose(i)
                and BY_ID[i].clase in ("fondo_rv", "etf", "renta_variable")
            ],
            "nota": (
                "Pesos efectivos: el cliente no compró ninguna de estas empresas, "
                "quedó expuesto a ellas por lo que traen los fondos. "
                "`cobertura_desglose` dice qué parte del portafolio se pudo mirar "
                "por dentro."
            ),
        }
    return salida


def get_funding_sources(client_id: str | None = None) -> dict[str, Any]:
    """Los origenes de fondos posibles y lo que cada uno le hace al calculo.

    Con `client_id` devuelve los origenes REALES del cliente: sus cuentas con
    saldo y sus creditos con la tasa contratada, no la tasa generica.
    """
    catalogo = [origen_mod.ficha(o) for o in origen_mod.ORIGENES]
    if not client_id:
        return {"origenes": catalogo, "por_defecto": origen_mod.ORIGEN_POR_DEFECTO}

    with db.session(readonly=True) as conn:
        if db.query_one(conn, "SELECT 1 FROM clients WHERE client_id = ?",
                        (client_id,)) is None:
            raise NotFound(f"No existe el cliente {client_id!r}.")
        cuentas = db.query(
            conn, "SELECT account_id, tipo, saldo_disponible FROM accounts"
                  " WHERE client_id = ? ORDER BY saldo_disponible DESC", (client_id,))
        creditos = db.query(
            conn, "SELECT loan_id, producto, saldo_insoluto, tasa_anual FROM loans"
                  " WHERE client_id = ?", (client_id,))
        tarjetas = db.query(
            conn, "SELECT card_id, last4, limite_credito, saldo_utilizado, tasa_anual"
                  " FROM cards WHERE client_id = ? AND tipo = 'credito'", (client_id,))

    disponibles = []
    for c in cuentas:
        o = origen_mod.desde_cuenta(c["tipo"])
        disponibles.append({**origen_mod.ficha(o), "account_id": c["account_id"],
                            "disponible": round(c["saldo_disponible"], 2)})
    for prestamo in creditos:
        o = origen_mod.desde_credito(prestamo["producto"], prestamo["tasa_anual"])
        disponibles.append({**origen_mod.ficha(o), "loan_id": prestamo["loan_id"],
                            "saldo_insoluto": round(prestamo["saldo_insoluto"], 2)})
    for t in tarjetas:
        o = origen_mod.resolver("tarjeta_credito")
        if t["tasa_anual"]:
            o = o._replace(costo_anual=float(t["tasa_anual"]))
        linea = (t["limite_credito"] or 0) - (t["saldo_utilizado"] or 0)
        disponibles.append({**origen_mod.ficha(o), "card_id": t["card_id"],
                            "last4": t["last4"], "disponible": round(linea, 2)})

    return {
        "client_id": client_id,
        "origenes_del_cliente": disponibles,
        "catalogo": catalogo,
        "nota": (
            "El origen cambia el cálculo: con crédito la referencia para «no "
            "perder» es la deuda que corre, no lo que aportaste, y el perfil "
            "aplicable baja a conservador."
        ),
    }
