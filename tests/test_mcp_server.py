"""Contrato del servidor MCP separado.

`tests/fake_mcp.py` prueba el loop del agente sin pagar un subproceso; este
archivo prueba lo que ese doble no puede: que `mcp_server/server.py` de verdad
hable el protocolo por stdio y que sus respuestas se decodifiquen como
`agent/mcp_client.py` espera. Es lento comparado con el resto de la suite
(levanta un proceso real) — por diseño: es la única prueba end-to-end del
"MCP separado".
"""

from __future__ import annotations

import asyncio

from agent.mcp_client import ClienteMCP
from agent.tools import NOMBRES_DATOS


async def _con_cliente(coro):
    async with ClienteMCP() as mcp:
        return await coro(mcp)


def test_list_tools_coincide_con_TOOLS_DATOS():
    async def ir(mcp: ClienteMCP):
        return await mcp.tools_para_el_modelo()

    tools = asyncio.run(_con_cliente(ir))
    nombres = {t["name"] for t in tools}
    assert nombres == NOMBRES_DATOS
    for t in tools:
        assert t["description"]
        assert t["input_schema"]["type"] == "object"


def test_llamar_una_tool_de_lectura():
    async def ir(mcp: ClienteMCP):
        return await mcp.llamar("get_client_snapshot", {"client_id": "CLI-0001"})

    ok, payload = asyncio.run(_con_cliente(ir))
    assert ok is True
    assert payload["client_id"] == "CLI-0001"


def test_tool_desconocida_no_tumba_el_servidor():
    async def ir(mcp: ClienteMCP):
        return await mcp.llamar("transferir_todo", {"a": "mi-cuenta"})

    ok, payload = asyncio.run(_con_cliente(ir))
    assert ok is False
    assert payload["error"] == "tool_desconocida"


def test_error_de_servicio_llega_estructurado():
    async def ir(mcp: ClienteMCP):
        return await mcp.llamar("get_client_snapshot", {"client_id": "CLI-9999"})

    ok, payload = asyncio.run(_con_cliente(ir))
    assert ok is False
    assert "error" in payload
    assert "CLI-0001" in payload.get("sugerencia", "")
