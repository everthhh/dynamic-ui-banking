"""Plantilla estatica de ultimo recurso.

Si el modelo no logra producir un blueprint valido despues de los reintentos,
el usuario no se queda viendo una pantalla en blanco: se le monta esto. Es fea
a proposito y dice la verdad, porque mentir en un demo es peor que verse simple.
"""

from __future__ import annotations

from typing import Any

from a2ui.models import CATALOG_ID


def plantilla_fallback(
    surface_id: str,
    titulo: str = "No pude armar esta pantalla",
    detalle: str = "Lo intenté un par de veces y el diseño no pasó la validación.",
) -> list[dict[str, Any]]:
    return [
        {"version": "v0.9", "createSurface": {
            "surfaceId": surface_id, "catalogId": CATALOG_ID}},
        {"version": "v0.9", "updateComponents": {"surfaceId": surface_id, "components": [
            {"id": "root", "component": "Card", "title": titulo,
             "tone": "warning", "children": ["detalle", "reintentar"]},
            {"id": "detalle", "component": "Text", "text": detalle, "tone": "muted"},
            {"id": "reintentar", "component": "Button", "label": "Intentar de nuevo",
             "variant": "primary",
             "action": {"event": {"name": "ask",
                                   "context": {"prompt": "Vuelve a intentarlo"}}}},
        ]}},
    ]


def plantilla_error_de_datos(
    surface_id: str,
    mensaje: str,
    sugerencia: str | None = None,
) -> list[dict[str, Any]]:
    """Cuando una tool de datos falla por regla de negocio y no hay nada que pintar."""
    hijos = ["mensaje"]
    componentes: list[dict[str, Any]] = [
        {"id": "root", "component": "Card", "title": "No se pudo completar",
         "tone": "danger", "children": hijos},
        {"id": "mensaje", "component": "Text", "text": mensaje},
    ]
    if sugerencia:
        hijos.append("sugerencia")
        componentes.append(
            {"id": "sugerencia", "component": "Text", "text": sugerencia, "tone": "muted"})
    return [
        {"version": "v0.9", "createSurface": {
            "surfaceId": surface_id, "catalogId": CATALOG_ID}},
        {"version": "v0.9", "updateComponents": {
            "surfaceId": surface_id, "components": componentes}},
    ]
