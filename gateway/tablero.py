"""Tablero inicial: lo primero que ve el cliente al entrar, sin llamar al LLM.

Perfil financiero + recomendaciones priorizadas, armados de forma
determinista con los mismos servicios que usa el agente y validados con el
mismo validador A2UI. Al abrir la app todavia no hay pregunta que
interpretar, asi que pagar una llamada al modelo para pintar siempre la misma
pantalla seria gastar tokens y segundos en balde.

Lo que SI hace falta es que el agente sepa que el cliente ya vio esto: el
tablero deja un resumen en `Sesion.contexto_tablero`, que va al system prompt
del siguiente turno (despues del punto de cache, para no invalidarlo).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from a2ui.models import CATALOG_ID
from gateway.direct_actions import ResultadoDirecto
from services import profile

SURFACE_TABLERO = "inicio"
RECOMENDACIONES_EN_TABLERO = 6
RECOMENDACIONES_VISIBLES = 3


@dataclass
class ResultadoTablero(ResultadoDirecto):
    contexto_agente: str = ""


def construir_tablero(client_id: str) -> ResultadoTablero:
    perfil, recomendaciones = profile.perfil_y_recomendaciones(
        client_id, limite=RECOMENDACIONES_EN_TABLERO)
    nombre = perfil["identidad"]["nombre_corto"]
    salud = perfil["salud_financiera"]
    lista = recomendaciones["recomendaciones"]
    s = SURFACE_TABLERO

    mensajes: list[dict[str, Any]] = [
        {"createSurface": {"surfaceId": s, "catalogId": CATALOG_ID}},
        {"updateDataModel": {"surfaceId": s, "path": "/perfil_financiero", "value": perfil}},
        {"updateDataModel": {"surfaceId": s, "path": "/recomendaciones", "value": lista}},
        {"updateComponents": {"surfaceId": s, "components": [
            {"id": "root", "component": "Column", "gap": 20,
             "children": ["saludo", "perfil", "recomendaciones", "ver_catalogo", "aviso"]},
            {"id": "saludo", "component": "Text", "variant": "h2",
             "text": f"Hola {nombre}, así se ven tus finanzas"},
            {"id": "perfil", "component": "bank.FinancialProfile",
             "perfil": {"path": "/perfil_financiero"}},
            {"id": "recomendaciones", "component": "bank.Recommendations",
             "recomendaciones": {"path": "/recomendaciones"},
             "titulo": "Lo que te recomendamos hoy", "max": RECOMENDACIONES_VISIBLES},
            {"id": "ver_catalogo", "component": "Button", "variant": "ghost",
             "label": "Ver todas las funcionalidades del banco",
             "action": {"event": {"name": "ask", "context": {
                 "prompt": "Muéstrame todas las funcionalidades que ofrece el banco, "
                           "no solo las recomendadas para mí."}}}},
            {"id": "aviso", "component": "Text", "variant": "caption", "tone": "muted",
             "text": perfil["disclaimer"]},
        ]}},
    ]

    estado = f"tu salud financiera es {salud['nivel']} ({salud['score']:.0f}/100)"
    if lista:
        texto = (f"Hola {nombre}. Revisé tus últimos 12 meses: {estado}. Te dejo lo que más te "
                 "conviene atender, con los números que lo respaldan; toca una recomendación o "
                 "pregúntame lo que quieras.")
    else:
        texto = (f"Hola {nombre}. Revisé tus últimos 12 meses: {estado} y no encontré nada "
                 "urgente. Pregúntame lo que quieras.")

    return ResultadoTablero(
        mensajes=mensajes,
        resumen=f"tablero inicial · salud {salud['score']:.0f}/100 · "
                f"{recomendaciones['total_detectadas']} recomendaciones",
        texto=texto,
        contexto_agente=_contexto_para_el_agente(perfil, lista),
    )


def _contexto_para_el_agente(perfil: dict[str, Any], recomendaciones: list[dict[str, Any]]) -> str:
    salud = perfil["salud_financiera"]
    lineas = [
        "## Lo que el cliente ya tiene en pantalla (tablero inicial, armado sin ti)",
        f"- Superficie `{SURFACE_TABLERO}`: `bank.FinancialProfile` en `/perfil_financiero` y "
        "`bank.Recommendations` en `/recomendaciones`.",
        f"- Resumen: {perfil['resumen']}",
        f"- Salud financiera: {salud['score']:.0f}/100 ({salud['nivel']}).",
        "- Recomendaciones, en el orden en que las ve:",
    ]
    for r in recomendaciones:
        h = r["herramienta"]
        lineas.append(
            f"  {r['orden']}. `{r['recomendacion_id']}` · {r['titulo']} → herramienta "
            f"`{h['herramienta_id']}`" + ("" if h["disponible"] else " (aún no disponible)"))
    lineas.append(
        "Si pregunta por sus números o por qué se le recomendó algo, llama "
        "`get_recommendations` o `get_financial_profile`: no cites cifras de memoria.")
    return "\n".join(lineas)
