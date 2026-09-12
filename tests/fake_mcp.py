"""Doble de prueba del cliente MCP.

Implementa la misma interfaz que `agent.mcp_client.ClienteMCP`
(`tools_para_el_modelo`, `llamar`) pero llama `services.REGISTRO` en el mismo
proceso: los tests del loop no pagan el costo de levantar un subproceso MCP
real por cada turno. El contrato real (schemas, (de)serialización JSON sobre
stdio) lo cubre `scripts/smoke.py`, que sí habla con `mcp_server/` de verdad.
"""

from __future__ import annotations

from typing import Any

from agent.tools import TOOLS_DATOS
from services import REGISTRO, ServiceError


class FakeClienteMCP:
    async def tools_para_el_modelo(self) -> list[dict[str, Any]]:
        return [dict(t) for t in TOOLS_DATOS]

    async def llamar(self, nombre: str, argumentos: dict[str, Any]) -> tuple[bool, Any]:
        fn = REGISTRO.get(nombre)
        if fn is None:
            return False, {
                "error": "tool_desconocida",
                "mensaje": f"No existe la tool {nombre!r}.",
                "sugerencia": f"Tools disponibles: {', '.join(sorted(REGISTRO))}.",
            }
        try:
            return True, fn(**argumentos)
        except ServiceError as exc:
            return False, exc.to_dict()
        except TypeError as exc:
            return False, {
                "error": "argumentos_invalidos",
                "mensaje": f"{nombre}: {exc}",
                "sugerencia": "Revisa el input_schema de la tool.",
            }
        except Exception as exc:                   # noqa: BLE001 - nunca tumbar el turno
            return False, {
                "error": "falla_interna",
                "mensaje": f"{nombre} falló de forma inesperada: {type(exc).__name__}.",
                "sugerencia": "Intenta con otros argumentos o continúa sin esa información.",
            }
