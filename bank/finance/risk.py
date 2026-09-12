"""Perfilamiento de riesgo: 4 preguntas -> score 0-100 -> perfil.

Las preguntas viven aqui y en ningun otro lado. El componente
`inv.RiskProfiler` las recibe como prop desde la tool `score_risk_profile`
(o desde `get_risk_questions`), para que nadie las reescriba en el front.
"""

from __future__ import annotations

from typing import Any, Iterable

# id, texto, peso, opciones [(valor, etiqueta)]
PREGUNTAS: tuple[dict[str, Any], ...] = (
    {
        "id": "horizonte",
        "texto": "¿En cuánto tiempo crees que vas a necesitar este dinero?",
        "peso": 0.35,
        "opciones": [
            {"value": 1, "label": "Menos de 1 año"},
            {"value": 2, "label": "Entre 1 y 3 años"},
            {"value": 3, "label": "Entre 3 y 5 años"},
            {"value": 4, "label": "Entre 5 y 10 años"},
            {"value": 5, "label": "Más de 10 años"},
        ],
    },
    {
        "id": "reaccion_caida",
        "texto": "Si tu inversión cayera 15% en un mes, ¿qué harías?",
        "peso": 0.30,
        "opciones": [
            {"value": 1, "label": "Sacaría todo"},
            {"value": 2, "label": "Sacaría una parte"},
            {"value": 3, "label": "Lo dejaría quieto"},
            {"value": 4, "label": "Lo dejaría y revisaría la estrategia"},
            {"value": 5, "label": "Aprovecharía para meter más"},
        ],
    },
    {
        "id": "experiencia",
        "texto": "¿Qué productos de inversión has usado antes?",
        "peso": 0.15,
        "opciones": [
            {"value": 1, "label": "Ninguno o solo pagarés"},
            {"value": 2, "label": "CETES o fondos de deuda"},
            {"value": 3, "label": "Fondos mixtos"},
            {"value": 4, "label": "Acciones o ETFs"},
            {"value": 5, "label": "Derivados o productos estructurados"},
        ],
    },
    {
        "id": "proposito",
        "texto": "¿Para qué es este dinero?",
        "peso": 0.20,
        "opciones": [
            {"value": 1, "label": "Fondo de emergencia"},
            {"value": 2, "label": "Una meta con fecha definida"},
            {"value": 3, "label": "Patrimonio, sin fecha"},
            {"value": 4, "label": "Crecer a largo plazo"},
            {"value": 5, "label": "Buscar el máximo rendimiento"},
        ],
    },
)

PREGUNTAS_POR_ID = {p["id"]: p for p in PREGUNTAS}

# score -> (perfil, descripcion corta)
BANDAS: tuple[tuple[int, int, str, str], ...] = (
    (0, 20, "conservador", "Prioridad absoluta a no perder capital."),
    (21, 40, "moderado", "Acepta movimientos pequeños a cambio de ganar algo más."),
    (41, 60, "balanceado", "Mitad estabilidad, mitad crecimiento."),
    (61, 80, "crecimiento", "Tolera caídas para capturar rendimiento de largo plazo."),
    (81, 100, "agresivo", "Busca el máximo rendimiento y aguanta volatilidad alta."),
)

# Tope duro por horizonte. Nadie sale agresivo con dinero que necesita el mes
# que entra, diga lo que diga en las otras tres preguntas.
TOPE_POR_HORIZONTE = {1: 25, 2: 45, 3: 65, 4: 85, 5: 100}

MESES_POR_HORIZONTE = {1: 9, 2: 24, 3: 48, 4: 84, 5: 150}


class RespuestaInvalida(ValueError):
    pass


def perfil_de_score(score: int) -> tuple[str, str]:
    for lo, hi, nombre, desc in BANDAS:
        if lo <= score <= hi:
            return nombre, desc
    raise RespuestaInvalida(f"score fuera de rango: {score}")


def preguntas_para_ui() -> list[dict[str, Any]]:
    """Forma que espera la prop `questions` de `inv.RiskProfiler`."""
    return [
        {"id": p["id"], "text": p["texto"], "options": p["opciones"]}
        for p in PREGUNTAS
    ]


def calificar(respuestas: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """respuestas: [{'id': 'horizonte', 'value': 3}, ...] -> score + perfil.

    Devuelve tambien el desglose por pregunta, porque la UI lo muestra y
    porque es lo que hace auditable la decision.
    """
    vistas: dict[str, int] = {}
    for r in respuestas:
        rid = r.get("id")
        if rid not in PREGUNTAS_POR_ID:
            raise RespuestaInvalida(f"pregunta desconocida: {rid!r}")
        try:
            val = int(r["value"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RespuestaInvalida(f"valor invalido en {rid!r}") from exc
        if not 1 <= val <= 5:
            raise RespuestaInvalida(f"{rid}: el valor debe estar entre 1 y 5, llego {val}")
        vistas[rid] = val

    faltantes = [p["id"] for p in PREGUNTAS if p["id"] not in vistas]
    if faltantes:
        raise RespuestaInvalida(f"faltan respuestas: {', '.join(faltantes)}")

    desglose = []
    bruto = 0.0
    for p in PREGUNTAS:
        val = vistas[p["id"]]
        aporte = p["peso"] * (val - 1) / 4 * 100
        bruto += aporte
        etiqueta = next(o["label"] for o in p["opciones"] if o["value"] == val)
        desglose.append({
            "id": p["id"],
            "pregunta": p["texto"],
            "respuesta": etiqueta,
            "valor": val,
            "peso": p["peso"],
            "aporte": round(aporte, 2),
        })

    score_bruto = int(round(bruto))
    tope = TOPE_POR_HORIZONTE[vistas["horizonte"]]
    score = min(score_bruto, tope)
    perfil, descripcion = perfil_de_score(score)

    return {
        "score": score,
        "score_bruto": score_bruto,
        "tope_por_horizonte": tope,
        "topado": score < score_bruto,
        "perfil": perfil,
        "descripcion": descripcion,
        "horizonte_meses": MESES_POR_HORIZONTE[vistas["horizonte"]],
        "desglose": desglose,
        "disclaimer": (
            "Perfilamiento de demostración con datos sintéticos. "
            "No constituye asesoría de inversión."
        ),
    }
