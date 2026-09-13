"""Servidor MCP: envuelve `services.REGISTRO` para el agente (u otro cliente MCP).

    python -m mcp_server.server

Corre por stdio, un proceso propio. El agente le habla vía `agent/mcp_client.py`
en lugar de importar `services` directo — es lo que hace que "MCP separado" sea
arquitectura y no una etiqueta: el proceso de las tools puede vivir en otra
máquina sin tocar una línea de `agent/loop.py`.

Los schemas de las tools NO se rescriben aquí: se derivan de
`agent.tools.TOOLS_DATOS`, la misma fuente que ya validaba
`test_cada_tool_declarada_existe_como_servicio`. Un solo lugar describe cada
tool; este servidor y el prompt del agente no pueden desincronizarse.

`render_surface` NO vive aquí: no es una tool de datos, es la señal que el
agente intercepta para validar y emitir A2UI. Ver `agent/loop.py`.
"""

from __future__ import annotations

import asyncio
import json
import logging

import jsonschema
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from agent.tools import TOOLS_DATOS
from services import REGISTRO, ServiceError

log = logging.getLogger("mcp_server")

server = Server("solemn-banking-ai-services")

_SCHEMAS = {t["name"]: t["input_schema"] for t in TOOLS_DATOS}


def _error(codigo: str, mensaje: str, sugerencia: str) -> types.CallToolResult:
    payload = {"error": codigo, "mensaje": mensaje, "sugerencia": sugerencia}
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        isError=True,
    )


@server.list_tools()
async def listar_tools() -> list[types.Tool]:
    return [
        types.Tool(name=t["name"], description=t["description"], inputSchema=t["input_schema"])
        for t in TOOLS_DATOS
    ]


@server.call_tool()
async def llamar_tool(nombre: str, argumentos: dict) -> dict | types.CallToolResult:
    """Despacha a `services.REGISTRO`. Un dict de vuelta se serializa como
    `structuredContent` + texto JSON; eso lo hace el propio decorador de mcp.
    """
    fn = REGISTRO.get(nombre)
    if fn is None:
        return _error(
            "tool_desconocida", f"No existe la tool {nombre!r}.",
            f"Tools disponibles: {', '.join(sorted(REGISTRO))}.",
        )

    schema = _SCHEMAS.get(nombre)
    if schema is not None:
        try:
            jsonschema.validate(argumentos, schema)
        except jsonschema.ValidationError as exc:
            return _error(
                "argumentos_invalidos",
                f"{nombre}: {exc.message}",
                "Revisa el input_schema de la tool y corrige el argumento señalado.",
            )
    try:
        return fn(**argumentos)
    except ServiceError as exc:
        datos = exc.to_dict()
        return types.CallToolResult(
            content=[types.TextContent(type="text",
                                        text=json.dumps(datos, ensure_ascii=False, default=str))],
            structuredContent=datos,
            isError=True,
        )
    except TypeError as exc:
        return _error("argumentos_invalidos", f"{nombre}: {exc}",
                      "Revisa el input_schema de la tool.")
    except Exception as exc:                       # noqa: BLE001 - nunca tumbar el servidor
        log.exception("falla inesperada en %s", nombre)
        return _error(
            "falla_interna", f"{nombre} falló de forma inesperada: {type(exc).__name__}.",
            "Intenta con otros argumentos o continúa sin esa información.",
        )


async def _correr() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.WARNING)
    asyncio.run(_correr())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
