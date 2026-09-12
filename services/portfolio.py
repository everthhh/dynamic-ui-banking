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

from bank import db
from bank.finance import compare, montecarlo, risk, rules
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


def propose_allocation(
    perfil: str,
    horizonte_anios: float,
    monto: float,
    liquidez_requerida: bool = False,
    excluir_clases: list[str] | None = None,
) -> dict[str, Any]:
    """Asignacion por reglas. Devuelve los `slices` que pinta `inv.AllocationDonut`."""
    try:
        propuesta = rules.proponer(
            perfil=perfil,
            horizonte_anios=float(horizonte_anios),
            monto=float(monto),
            liquidez_requerida=bool(liquidez_requerida),
            excluir_clases=tuple(excluir_clases or ()),
        )
    except rules.SinPropuesta as exc:
        raise ServiceError(str(exc)) from exc
    propuesta["asignacion"] = rules.asignacion_plana(propuesta)
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
) -> dict[str, Any]:
    """Monte Carlo del portafolio. Alimenta `inv.ProjectionChart`."""
    pesos = _asignacion_desde_entrada(asignacion)
    try:
        return montecarlo.simular(pesos, float(monto), float(horizonte_anios),
                                  float(aportacion_mensual))
    except montecarlo.SimulacionInvalida as exc:
        raise ServiceError(str(exc)) from exc


def compare_allocations(
    izquierda: Any,
    derecha: Any,
    monto: float,
    horizonte_anios: float,
    aportacion_mensual: float = 0.0,
    metricas: list[str] | None = None,
    etiqueta_izquierda: str = "Opción A",
    etiqueta_derecha: str = "Opción B",
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
        )
    except (compare.ComparacionInvalida, montecarlo.SimulacionInvalida) as exc:
        raise ServiceError(str(exc)) from exc
