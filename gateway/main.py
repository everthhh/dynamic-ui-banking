"""Gateway FastAPI.

Responsabilidades, y nada mas:
  * guardar las sesiones (el historial vive aqui, no en el navegador)
  * exponer `/chat` y `/action` como SSE
  * servir el catalogo A2UI al renderer
  * leer la bitacora

Lo que NO hace: decidir que pintar. Eso es del agente. Lo que tampoco hace:
calcular. Eso es de los servicios.

    uvicorn gateway.main:app --reload --port 8000
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from a2ui.models import CATALOG, CATALOG_PATH
from agent.loop import AgenteUIGenerativa, Sesion
from bank import db
from services.orders import registrar_superficie

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("gateway")

app = FastAPI(title="dynamic-ui-banking · gateway", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

SESIONES: dict[str, Sesion] = {}
_agente: AgenteUIGenerativa | None = None


def agente() -> AgenteUIGenerativa:
    """Instancia perezosa: importar el gateway no debe exigir una API key."""
    global _agente
    if _agente is None:
        _agente = AgenteUIGenerativa(registrar_superficie=registrar_superficie)
    return _agente


def sesion(session_id: str | None, client_id: str = "CLI-0001") -> Sesion:
    if session_id and session_id in SESIONES:
        return SESIONES[session_id]
    sid = session_id or f"ses-{uuid.uuid4().hex[:12]}"
    SESIONES[sid] = Sesion(session_id=sid, client_id=client_id)
    return SESIONES[sid]


# --------------------------------------------------------------------- contratos
class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    client_id: str = "CLI-0001"


class AccionIn(BaseModel):
    name: str
    session_id: str
    surfaceId: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


# ------------------------------------------------------------------------- stream
async def _stream(ses: Sesion, entrada: str | dict[str, Any]) -> AsyncIterator[dict[str, str]]:
    yield {"event": "session", "data": json.dumps({"session_id": ses.session_id})}
    try:
        async for evento in agente().run_turn(ses, entrada):
            yield {"event": evento.tipo, "data": evento.to_json()}
    except Exception as exc:                       # noqa: BLE001
        log.exception("el turno se cayó")
        yield {"event": "error", "data": json.dumps(
            {"type": "error", "mensaje": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)}


@app.post("/chat")
async def chat(cuerpo: ChatIn):
    ses = sesion(cuerpo.session_id, cuerpo.client_id)
    return EventSourceResponse(_stream(ses, cuerpo.message))


@app.post("/action")
async def accion(cuerpo: AccionIn):
    """La interaccion del usuario NUNCA actualiza la UI por su cuenta: vuelve aqui."""
    if cuerpo.session_id not in SESIONES:
        raise HTTPException(404, f"sesión desconocida: {cuerpo.session_id}")
    ses = SESIONES[cuerpo.session_id]
    return EventSourceResponse(_stream(ses, {
        "name": cuerpo.name,
        "surfaceId": cuerpo.surfaceId or ses.surface_id,
        "context": cuerpo.context,
    }))


# -------------------------------------------------------------------- utilitarios
@app.get("/health")
async def health():
    existe = db.DB_PATH.exists()
    return {"ok": existe, "db": str(db.DB_PATH),
            "sesiones": len(SESIONES),
            "nota": None if existe else "falta correr `make seed`"}


@app.get("/a2ui/inv/v1/catalog.json")
async def catalogo():
    """Fuente unica de verdad, servida al renderer tal cual esta en disco."""
    return JSONResponse(json.loads(CATALOG_PATH.read_text(encoding="utf-8")))


@app.get("/api/clients")
async def clientes():
    """Los 8 clientes sinteticos, para el selector del demo."""
    with db.session(readonly=True) as conn:
        filas = db.query(
            conn,
            "SELECT c.client_id, c.nombre, c.segmento, c.ingreso_mensual,"
            "  (SELECT COUNT(*) FROM risk_profiles r WHERE r.client_id = c.client_id"
            "    AND r.vigente_hasta >= (SELECT fecha_valuacion FROM market_params WHERE id=1))"
            "   AS perfiles_vigentes"
            " FROM clients c ORDER BY c.client_id")
    return {"clientes": [{**f, "perfil_vigente": bool(f.pop("perfiles_vigentes"))}
                         for f in filas]}


@app.get("/api/sessions/{session_id}/log")
async def bitacora(session_id: str):
    """Bitacora del blueprint: permite reconstruir la sesion turno por turno."""
    with db.session(readonly=True) as conn:
        filas = db.query(
            conn, "SELECT turn, surface_id, messages_json, tools_json, created_at"
                  " FROM surface_log WHERE session_id = ? ORDER BY turn", (session_id,))
    return {
        "session_id": session_id,
        "turnos": [
            {"turno": f["turn"], "surface_id": f["surface_id"],
             "created_at": f["created_at"],
             "messages": json.loads(f["messages_json"]),
             "tools": json.loads(f["tools_json"])}
            for f in filas
        ],
    }


@app.get("/api/sessions/{session_id}")
async def estado_de_sesion(session_id: str):
    if session_id not in SESIONES:
        raise HTTPException(404, "sesión desconocida")
    s = SESIONES[session_id]
    return {"session_id": s.session_id, "client_id": s.client_id,
            "surface_id": s.surface_id, "turno": s.turno,
            "mensajes_en_historial": len(s.historial), "uso": s.uso}


@app.get("/api/theme")
async def tema():
    return CATALOG["theme"]
