"""Pruebas de las acciones deterministas que resuelve el gateway sin el LLM.

Cada handler de `gateway/direct_actions.py` es una función pura sobre una
`Sesion` y un `context` — se prueban directo, sin levantar FastAPI ni el
agente. Lo que importa verificar: que arman el `updateDataModel` correcto,
que las reglas de negocio de `services/banking.py` se siguen respetando
(no se saltan por venir de un camino distinto), y que `toggle_card_block`
decide bien la dirección con el `estado` que manda el cliente.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import gateway.main as gw
from agent.loop import Sesion
from gateway.direct_actions import DIRECT_HANDLERS
from services import accounts, banking
from services.errors import ServiceError

CLIENTE = "CLI-0001"


def _sesion() -> Sesion:
    return Sesion(session_id="test-directo", client_id=CLIENTE, surface_id="bank-main")


def _tarjetas() -> list[dict]:
    return accounts.get_accounts(CLIENTE)["tarjetas"]


def _tarjeta_debito() -> dict:
    return next(t for t in _tarjetas() if t["tipo"] == "debito")


def _tarjeta_credito() -> dict:
    return next(t for t in _tarjetas() if t["tipo"] == "credito")


def _cuenta() -> dict:
    return accounts.get_accounts(CLIENTE)["cuentas"][0]


def _updateDataModel(resultado, path: str):
    return next(m["updateDataModel"] for m in resultado.mensajes
                if "updateDataModel" in m and m["updateDataModel"]["path"] == path)


def test_todas_las_acciones_deterministas_estan_registradas():
    assert set(DIRECT_HANDLERS) == {
        "set_account_alias", "set_card_alias", "toggle_card_block",
        "update_card_limit", "set_budget", "manage_card",
    }


def test_set_account_alias_patchea_cuentas_completo():
    ses = _sesion()
    cuenta = _cuenta()
    resultado = DIRECT_HANDLERS["set_account_alias"](
        ses, {"account_id": cuenta["account_id"], "alias": "Mi cuenta"})
    dm = _updateDataModel(resultado, "/cuentas")
    assert dm["surfaceId"] == "bank-main"
    actualizada = next(c for c in dm["value"] if c["account_id"] == cuenta["account_id"])
    assert actualizada["alias"] == "Mi cuenta"


def test_set_card_alias_patchea_solo_la_tarjeta():
    ses = _sesion()
    tarjeta = _tarjeta_debito()
    resultado = DIRECT_HANDLERS["set_card_alias"](
        ses, {"card_id": tarjeta["card_id"], "alias": "Diario"})
    dm = _updateDataModel(resultado, "/card")
    assert dm["value"]["alias"] == "Diario"
    assert dm["value"]["card_id"] == tarjeta["card_id"]


def test_toggle_card_block_bloquea_cuando_estado_es_activa():
    ses = _sesion()
    tarjeta = _tarjeta_debito()
    resultado = DIRECT_HANDLERS["toggle_card_block"](
        ses, {"card_id": tarjeta["card_id"], "estado": "activa"})
    dm = _updateDataModel(resultado, "/card")
    assert dm["value"]["estado"] == "bloqueada"


def test_toggle_card_block_desbloquea_cuando_estado_es_bloqueada():
    ses = _sesion()
    tarjeta = _tarjeta_debito()
    banking.block_card(CLIENTE, tarjeta["card_id"])
    resultado = DIRECT_HANDLERS["toggle_card_block"](
        ses, {"card_id": tarjeta["card_id"], "estado": "bloqueada"})
    dm = _updateDataModel(resultado, "/card")
    assert dm["value"]["estado"] == "activa"


def test_toggle_card_block_con_estado_desactualizado_sigue_siendo_idempotente():
    """El cliente manda un `estado` viejo (ej. dos clics rápidos); el handler
    llama block_card/unblock_card, que ya son idempotentes por diseño — no
    debe tronar ni desincronizarse de la base real.
    """
    ses = _sesion()
    tarjeta = _tarjeta_debito()
    banking.block_card(CLIENTE, tarjeta["card_id"])  # la base ya la tiene bloqueada

    # El cliente todavía cree que estaba "activa" (dato viejo) y pide bloquear:
    resultado = DIRECT_HANDLERS["toggle_card_block"](
        ses, {"card_id": tarjeta["card_id"], "estado": "activa"})
    dm = _updateDataModel(resultado, "/card")
    assert dm["value"]["estado"] == "bloqueada"  # sigue bloqueada, no truena

    banking.unblock_card(CLIENTE, tarjeta["card_id"])  # limpieza


def test_update_card_limit_respeta_el_tope_de_negocio():
    ses = _sesion()
    tarjeta = _tarjeta_credito()
    cliente = accounts.get_client_snapshot(CLIENTE)
    tope = cliente["ingreso_mensual"] * banking.MULTIPLO_LIMITE_MAXIMO
    with pytest.raises(ServiceError):
        DIRECT_HANDLERS["update_card_limit"](
            ses, {"card_id": tarjeta["card_id"], "nuevo_limite": tope + 1})


def test_update_card_limit_valido_patchea_la_tarjeta():
    ses = _sesion()
    tarjeta = _tarjeta_credito()
    nuevo = tarjeta["saldo_utilizado"] + 1_000
    resultado = DIRECT_HANDLERS["update_card_limit"](
        ses, {"card_id": tarjeta["card_id"], "nuevo_limite": nuevo})
    dm = _updateDataModel(resultado, "/card")
    assert dm["value"]["limite_credito"] == nuevo


def test_set_budget_patchea_alertas_recalculadas():
    ses = _sesion()
    resultado = DIRECT_HANDLERS["set_budget"](
        ses, {"categoria": "transporte", "monto_mensual": 900})
    dm = _updateDataModel(resultado, "/alertas")
    fila = next(a for a in dm["value"] if a["categoria"] == "transporte")
    assert fila["presupuesto"] == 900


def test_set_budget_categoria_invalida_propaga_service_error():
    ses = _sesion()
    with pytest.raises(ServiceError):
        DIRECT_HANDLERS["set_budget"](ses, {"categoria": "criptomonedas", "monto_mensual": 500})


def test_manage_card_monta_card_manager_con_los_datos_del_cliente():
    ses = _sesion()
    tarjeta = _tarjeta_debito()
    resultado = DIRECT_HANDLERS["manage_card"](ses, {"card_id": tarjeta["card_id"], "card": tarjeta})
    dm_card = _updateDataModel(resultado, "/card")
    assert dm_card["value"]["card_id"] == tarjeta["card_id"]
    dm_ingreso = _updateDataModel(resultado, "/ingresoMensual")
    assert dm_ingreso["value"] > 0
    update_components = next(m["updateComponents"] for m in resultado.mensajes if "updateComponents" in m)
    assert update_components["components"][0]["component"] == "bank.CardManager"


def test_manage_card_sin_objeto_card_es_rechazado():
    ses = _sesion()
    with pytest.raises(ServiceError):
        DIRECT_HANDLERS["manage_card"](ses, {"card_id": "CRD-0001"})


# --------------------------------------------------------------- ruteo en /action
async def _agen_vacio():
    if False:                                       # nunca corre; solo hace el generador async
        yield {}


def _accion_in(nombre: str, contexto: dict, session_id: str) -> "gw.AccionIn":
    return gw.AccionIn(
        session_id=session_id,
        action=gw.AccionEvento(
            name=nombre, surfaceId="bank-main", sourceComponentId="test",
            timestamp="2026-01-01T00:00:00Z", context=contexto,
        ),
    )


def test_accion_rutea_directo_para_una_accion_determinista():
    """Una acción en DIRECT_HANDLERS jamás debe pasar por el camino del LLM."""
    session_id = "ses-routing-directo"
    gw.SESIONES[session_id] = Sesion(session_id=session_id, client_id=CLIENTE, surface_id="bank-main")
    try:
        cuerpo = _accion_in("set_budget", {"categoria": "transporte", "monto_mensual": 700}, session_id)
        with patch.object(gw, "_stream_directo", return_value=_agen_vacio()) as directo_mock, \
             patch.object(gw, "_stream", return_value=_agen_vacio()) as llm_mock:
            asyncio.run(gw.accion(cuerpo))
        directo_mock.assert_called_once()
        llm_mock.assert_not_called()
    finally:
        gw.SESIONES.pop(session_id, None)


def test_accion_rutea_al_llm_para_una_accion_que_necesita_razonamiento():
    """`profile_done`, `ask`, etc. no están en DIRECT_HANDLERS: deben seguir yendo al agente."""
    session_id = "ses-routing-llm"
    gw.SESIONES[session_id] = Sesion(session_id=session_id, client_id=CLIENTE, surface_id="bank-main")
    try:
        cuerpo = _accion_in("profile_done", {"answers": []}, session_id)
        with patch.object(gw, "_stream_directo", return_value=_agen_vacio()) as directo_mock, \
             patch.object(gw, "_stream", return_value=_agen_vacio()) as llm_mock:
            asyncio.run(gw.accion(cuerpo))
        llm_mock.assert_called_once()
        directo_mock.assert_not_called()
    finally:
        gw.SESIONES.pop(session_id, None)
