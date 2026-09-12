"""Ciclo completo sin tocar la API de Anthropic.

    python -m scripts.smoke

Corre los seis turnos del guion contra el SERVIDOR MCP real (subproceso propio,
igual que en producción) y el validador real, con un cliente de Anthropic
falso que representa al modelo. Sirve para contestar en diez segundos la
pregunta "¿sigue cerrando el ciclo con el MCP separado?" sin gastar un token,
y para demostrarle a un jurado el encadenado completo aunque no haya red en
la sede.

Lo que NO prueba: que el modelo de verdad elija bien las tools. Eso solo se ve
corriendo el gateway con una API key.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

GUION_PATH = Path(__file__).resolve().parent.parent / "web" / "src" / "fixtures" / "demo.json"

VERDE = "\033[32m"
ROJO = "\033[31m"
GRIS = "\033[90m"
NEGRITA = "\033[1m"
FIN = "\033[0m"


def _token_pendiente(sesion) -> str | None:
    """Recupera el `confirmation_token` del último `tool_result` del historial.

    Es exactamente lo que hace el modelo de verdad: el token solo existe en la
    respuesta del paso 1, y sin leerlo de ahí no hay forma de ejecutar. Si esta
    función devolviera None y la orden se ejecutara igual, el candado estaría
    roto.
    """
    for mensaje in reversed(sesion.historial):
        if mensaje["role"] != "user" or not isinstance(mensaje["content"], list):
            continue
        for bloque in mensaje["content"]:
            if not isinstance(bloque, dict) or bloque.get("type") != "tool_result":
                continue
            try:
                datos = json.loads(bloque["content"])
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(datos, dict) and datos.get("confirmation_token"):
                return str(datos["confirmation_token"])
    return None


def _bloques_del_turno(turno: dict, token: str | None) -> list[list]:
    """Convierte un turno del guion en turnos del modelo falso.

    El guion trae el resultado; aquí se reconstruye la secuencia de decisiones:
    una llamada por cada tool, y una final con el blueprint.
    """
    from tests.fake_anthropic import BloqueTexto, BloqueToolUse

    salida: list[list] = []
    orden = {"client_id": "CLI-0001",
             "asignacion": {"CETES-364": 0.5, "FND-GUB-CP": 0.5},
             "monto": 80000, "idempotency_key": "smoke-1"}
    if token:
        orden["confirmation_token"] = token

    argumentos = {
        "get_client_snapshot": {"client_id": "CLI-0001"},
        "get_risk_questions": {},
        "get_spending_summary": {"client_id": "CLI-0001"},
        "score_risk_profile": {"answers": [
            {"id": "horizonte", "value": 4}, {"id": "reaccion_caida", "value": 3},
            {"id": "experiencia", "value": 2}, {"id": "proposito", "value": 3}],
            "guardar": False},
        "propose_allocation": {"perfil": "balanceado", "horizonte_anios": 5, "monto": 80000},
        "simulate_portfolio": {"asignacion": {"CETES-364": 0.5, "FND-GUB-CP": 0.5},
                               "monto": 80000, "horizonte_anios": 5},
        "compare_allocations": {"izquierda": {"CETES-364": 1.0},
                                "derecha": {"NAFTRAC": 1.0},
                                "monto": 80000, "horizonte_anios": 5},
        "place_order": orden,
        "get_orders": {"client_id": "CLI-0001"},
    }

    for evento in turno["eventos"]:
        if evento["type"] == "tool_call":
            salida.append([BloqueToolUse(evento["name"], argumentos.get(evento["name"], {}))])

    mensajes = [e["message"] for e in turno["eventos"] if e["type"] == "a2ui"]
    texto = next((e["text"] for e in turno["eventos"] if e["type"] == "text"), "")
    if mensajes:
        salida.append([BloqueTexto(texto), BloqueToolUse("render_surface", {"messages": mensajes})])
    salida.append([BloqueTexto("Listo.")])
    return salida


async def correr() -> int:
    from agent.loop import AgenteUIGenerativa, Sesion
    from agent.mcp_client import ClienteMCP
    from tests.fake_anthropic import FakeAnthropic

    guion = json.loads(GUION_PATH.read_text(encoding="utf-8"))
    sesion = Sesion(session_id="smoke", client_id=guion["client_id"])
    bitacora: list[tuple] = []
    fallas = 0

    print(f"{NEGRITA}Ciclo completo, {len(guion['turnos'])} turnos, "
          f"MCP real + sin API{FIN}\n")

    # El servidor MCP corre en su propio subproceso; hereda BANK_DB_PATH para
    # que lea la base desechable que arma `main()`, no data/bank.sqlite.
    env_mcp = {"BANK_DB_PATH": os.environ["BANK_DB_PATH"]}
    async with ClienteMCP(env=env_mcp) as mcp:
        for i, turno in enumerate(guion["turnos"], 1):
            disparador = turno["disparador"]
            entrada = (disparador["texto"] if disparador["tipo"] == "chat"
                       else {"name": disparador["name"], "surfaceId": sesion.surface_id,
                             "context": {}})
            agente = AgenteUIGenerativa(
                cliente=FakeAnthropic(_bloques_del_turno(turno, _token_pendiente(sesion))),
                mcp=mcp,
                modelo="cliente-falso",
                registrar_superficie=lambda *a: bitacora.append(a),
            )

            etiqueta = (disparador.get("texto") or f"acción `{disparador.get('name')}`")[:58]
            print(f"{NEGRITA}Turno {i}{FIN} · {etiqueta}")

            tools: list[str] = []
            a2ui: list[str] = []
            rechazos = 0
            async for evento in agente.run_turn(sesion, entrada):
                if evento.tipo == "tool_call":
                    marca = f"{ROJO}${FIN}" if evento.datos.get("efecto") else "·"
                    tools.append(f"{marca} {evento.datos['name']}")
                elif evento.tipo == "tool_result" and not evento.datos["ok"]:
                    fallas += 1
                    print(f"  {ROJO}tool falló:{FIN} {evento.datos['name']} → "
                          f"{evento.datos['resumen'][:90]}")
                elif evento.tipo == "a2ui":
                    msg = evento.datos["message"]
                    a2ui.append(next(k for k in ("createSurface", "updateComponents",
                                                 "updateDataModel", "deleteSurface") if k in msg))
                elif evento.tipo == "render_rechazado":
                    rechazos += 1
                elif evento.tipo == "text" and evento.datos["text"].strip():
                    print(f"  {GRIS}«{evento.datos['text'].strip()[:80]}»{FIN}")

            print(f"  tools:  {'  '.join(tools) or '—'}")
            print(f"  a2ui:   {' → '.join(a2ui) or '—'}"
                  + (f"   {ROJO}({rechazos} rechazado/s){FIN}" if rechazos else ""))
            print()

    print(f"{NEGRITA}Resultado{FIN}")
    print(f"  superficie final: {sesion.surface_id}")
    print(f"  turnos en bitácora: {len(bitacora)}")
    print(f"  mensajes en el historial: {len(sesion.historial)}")

    if len(bitacora) != len(guion["turnos"]):
        print(f"  {ROJO}la bitácora no registró todos los turnos{FIN}")
        fallas += 1

    ordenes = _ordenes_ejecutadas(guion["client_id"])
    print(f"  órdenes ejecutadas: {ordenes}")
    if ordenes != 1:
        print(f"  {ROJO}debería haber exactamente una orden ejecutada{FIN}")
        fallas += 1

    print()
    if fallas:
        print(f"{ROJO}{NEGRITA}{fallas} problema(s).{FIN}")
        return 1
    print(f"{VERDE}{NEGRITA}El ciclo cierra: intención → tools (MCP) → UI → acción → UI nueva.{FIN}")
    return 0


def _ordenes_ejecutadas(client_id: str) -> int:
    from services import REGISTRO
    return len(REGISTRO["get_orders"](client_id, estado="ejecutada")["ordenes"])


def main() -> int:
    from bank import db, seed

    # Base desechable: el smoke ejecuta una orden de verdad.
    with tempfile.TemporaryDirectory() as tmp:
        destino = Path(tmp) / "bank.sqlite"
        original = db.DB_PATH
        os.environ["BANK_DB_PATH"] = str(destino)
        db.DB_PATH = destino
        try:
            seed.construir(destino)
            return asyncio.run(correr())
        finally:
            db.DB_PATH = original
            os.environ.pop("BANK_DB_PATH", None)


if __name__ == "__main__":
    raise SystemExit(main())
