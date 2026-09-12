"""Cliente MCP del agente: habla con `mcp_server/` por stdio.

Antes, `agent/loop.py` importaba `services.REGISTRO` directo. Ahora el agente
no sabe cómo están implementadas las tools de datos, ni siquiera en qué
proceso corren: les habla el protocolo MCP. `tools_para_el_modelo()` viene de
`list_tools()` del servidor, no de una lista estática — si el servidor cambia
de máquina, `agent/loop.py` no se entera.
"""

from __future__ import annotations

import json
import sys
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.stdio import get_default_environment


class ClienteMCP:
    """Conecta al servidor MCP de `services/` como subproceso por stdio.

    Uso:
        async with ClienteMCP() as mcp:
            tools = await mcp.tools_para_el_modelo()
            ok, payload = await mcp.llamar("get_client_snapshot", {"client_id": "CLI-0001"})
    """

    def __init__(
        self,
        comando: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._comando = comando or sys.executable
        self._args = args if args is not None else ["-m", "mcp_server.server"]
        self._env = env
        self._stack: AsyncExitStack | None = None
        self._sesion: ClientSession | None = None

    async def conectar(self) -> None:
        self._stack = AsyncExitStack()
        try:
            params = StdioServerParameters(
                command=self._comando, args=self._args,
                env={**get_default_environment(), **self._env} if self._env else None,
            )
            lector, escritor = await self._stack.enter_async_context(stdio_client(params))
            self._sesion = await self._stack.enter_async_context(ClientSession(lector, escritor))
            await self._sesion.initialize()
        except BaseException:
            await self._stack.aclose()
            self._stack = None
            raise

    async def cerrar(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
            self._stack = None
            self._sesion = None

    async def __aenter__(self) -> "ClienteMCP":
        await self.conectar()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.cerrar()

    async def tools_para_el_modelo(self) -> list[dict[str, Any]]:
        """Schemas en el formato del parámetro `tools` de `messages.create`."""
        assert self._sesion is not None, "llama conectar() primero"
        resultado = await self._sesion.list_tools()
        return [
            {"name": t.name, "description": t.description or "", "input_schema": t.inputSchema}
            for t in resultado.tools
        ]

    async def llamar(self, nombre: str, argumentos: dict[str, Any]) -> tuple[bool, Any]:
        """Llama una tool de datos. Devuelve (ok, payload), igual que antes con REGISTRO."""
        assert self._sesion is not None, "llama conectar() primero"
        resultado = await self._sesion.call_tool(nombre, argumentos)
        return (not resultado.isError, _payload_de(resultado))


def _payload_de(resultado: Any) -> Any:
    """Prefiere `structuredContent`; si no hay, decodifica el primer bloque de texto."""
    if resultado.structuredContent is not None:
        return resultado.structuredContent
    for bloque in resultado.content:
        if getattr(bloque, "type", None) == "text":
            try:
                return json.loads(bloque.text)
            except json.JSONDecodeError:
                return bloque.text
    return None
