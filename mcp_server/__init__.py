"""Servidor MCP standalone que expone `services/` (las tools de datos del banco).

Proceso separado del gateway y del agente: se conecta por stdio (ver
`agent/mcp_client.py`). No sabe nada de A2UI, de prompts ni de `render_surface`
— eso vive en `agent/`, del lado del cliente MCP.
"""
