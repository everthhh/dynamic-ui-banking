"""Tablero inicial: se arma sin el LLM, valida contra el catalogo y le deja
contexto al agente para el siguiente turno."""

from __future__ import annotations

import asyncio
import json

import pytest

import gateway.main as gw
from a2ui.models import validate_a2ui
from agent.loop import Sesion
from agent.prompts import contexto_de_sesion
from bank import db
from gateway.direct_actions import DIRECT_HANDLERS
from gateway.tablero import SURFACE_TABLERO, construir_tablero

CLIENTES = [f"CLI-{i:04d}" for i in range(1, 9)]


def _consumir(generador) -> list[dict]:
    async def _ir():
        return [e async for e in generador]
    return asyncio.run(_ir())


@pytest.mark.parametrize("client_id", CLIENTES)
def test_el_tablero_valida_contra_el_catalogo(client_id):
    t = construir_tablero(client_id)
    res = validate_a2ui([{"version": "v0.9", **m} for m in t.mensajes])
    assert res.ok, res.errores
    assert not res.avisos
    componentes = next(m["updateComponents"]["components"] for m in t.mensajes
                       if "updateComponents" in m)
    assert {"bank.FinancialProfile", "bank.Recommendations"} <= {c["component"] for c in componentes}
    assert t.texto
    json.dumps([m for m in t.mensajes])


def test_el_agente_sabe_que_recomendaciones_hay_en_pantalla():
    t = construir_tablero("CLI-0001")
    en_pantalla = next(m["updateDataModel"]["value"] for m in t.mensajes
                       if m.get("updateDataModel", {}).get("path") == "/recomendaciones")
    assert en_pantalla
    for r in en_pantalla:
        assert r["recomendacion_id"] in t.contexto_agente
    system = contexto_de_sesion("CLI-0001", SURFACE_TABLERO, 1, tablero=t.contexto_agente)
    assert t.contexto_agente in system


def test_iniciar_sesion_pinta_el_tablero_sin_llamar_al_agente(monkeypatch):
    def sin_agente():
        raise AssertionError("el tablero inicial no debe instanciar el agente")

    monkeypatch.setattr(gw, "agente", sin_agente)
    ses = Sesion(session_id="ses-tablero", client_id="CLI-0005")
    eventos = _consumir(gw._stream_tablero(ses))
    tipos = [e["event"] for e in eventos]

    assert tipos[0] == "session" and tipos[-1] == "done"
    assert "error" not in tipos
    assert tipos.count("a2ui") == 4
    assert "text" in tipos
    assert ses.surface_id == SURFACE_TABLERO
    assert ses.contexto_tablero

    with db.session(readonly=True) as conn:
        fila = db.query_one(conn, "SELECT tools_json FROM surface_log WHERE session_id = ?",
                            ("ses-tablero",))
    assert fila is not None and "get_recommendations" in fila["tools_json"]


def test_cliente_inexistente_devuelve_error_sin_tumbar_la_sesion():
    ses = Sesion(session_id="ses-inexistente", client_id="CLI-9999")
    eventos = _consumir(gw._stream_tablero(ses))
    assert [e["event"] for e in eventos] == ["session", "error"]
    assert "CLI-0001" in json.loads(eventos[1]["data"])["mensaje"]


def test_seguir_una_recomendacion_si_pasa_por_el_agente():
    """Abrir la herramienta de una recomendación es interpretar: no es acción directa."""
    assert "follow_recommendation" not in DIRECT_HANDLERS
