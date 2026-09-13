"""Pruebas del loop del agente con el cliente de Anthropic falso.

Lo que se verifica aqui es el comportamiento que la rubrica llama "calidad de
la solucion de IA": encadenado de tools, validacion con reintento, y que el
modelo no pueda ejecutar una orden por su cuenta.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from a2ui.models import CATALOG_ID
from agent.loop import AgenteUIGenerativa, Sesion, _avisos_de_rutas_bank
from tests.fake_anthropic import BloqueTexto, BloqueToolUse, FakeAnthropic
from tests.fake_mcp import FakeClienteMCP


def payloads_de_tools(sesion: Sesion) -> list[str]:
    """Los `tool_result` completos que el loop le devolvio al modelo.

    Los eventos que van al front llevan un resumen recortado (es un panel de
    depuracion, no el dato); lo que el modelo recibe es esto.
    """
    return [
        c["content"]
        for m in sesion.historial
        if m["role"] == "user" and isinstance(m["content"], list)
        for c in m["content"]
        if isinstance(c, dict) and c.get("type") == "tool_result"
    ]


def correr(cliente: FakeAnthropic, entrada: Any, sesion: Sesion | None = None):
    sesion = sesion or Sesion(session_id="test", client_id="CLI-0001")
    agente = AgenteUIGenerativa(cliente=cliente, mcp=FakeClienteMCP(), modelo="modelo-falso")

    async def _ir():
        return [ev async for ev in agente.run_turn(sesion, entrada)]

    return asyncio.run(_ir()), sesion


def blueprint_perfilador() -> list[dict]:
    return [
        {"version": "v0.9", "createSurface": {
            "surfaceId": "inv-main", "catalogId": CATALOG_ID}},
        {"version": "v0.9", "updateDataModel": {
            "surfaceId": "inv-main", "path": "/perfilador/questions", "value": []}},
        {"version": "v0.9", "updateComponents": {"surfaceId": "inv-main", "components": [
            {"id": "root", "component": "Column", "children": ["h", "perfilador"]},
            {"id": "h", "component": "Text", "text": "Cuatro preguntas", "variant": "h2"},
            {"id": "perfilador", "component": "inv.RiskProfiler",
             "questions": {"path": "/perfilador/questions"},
             "action": {"event": {"name": "profile_done"}}},
        ]}},
    ]


# ------------------------------------------------------------------ camino feliz
def test_encadena_tools_y_emite_la_superficie():
    cliente = FakeAnthropic([
        [BloqueToolUse("get_client_snapshot", {"client_id": "CLI-0001"})],
        [BloqueToolUse("get_risk_questions", {})],
        [BloqueTexto("Antes de proponerte algo necesito cuatro datos."),
         BloqueToolUse("render_surface", {"messages": blueprint_perfilador()})],
        [BloqueTexto("Son treinta segundos.")],
    ])
    eventos, sesion = correr(cliente, "tengo 80 mil parados y los dejaría 5 años")

    tipos = [e.tipo for e in eventos]
    assert tipos.count("tool_call") == 2
    assert tipos.count("a2ui") == 3
    assert tipos[-1] == "done"
    assert eventos[-1].datos["render_ok"] is True

    llamadas = [e.datos["name"] for e in eventos if e.tipo == "tool_call"]
    assert llamadas == ["get_client_snapshot", "get_risk_questions"]

    # el snapshot real dice que CLI-0001 no trae perfil vigente: es lo que
    # justifica que el siguiente paso sea el perfilador y no una propuesta
    assert '"perfil_vigente": false' in payloads_de_tools(sesion)[0]
    assert sesion.surface_id == "inv-main"
    assert len(sesion.a2ui_del_turno) == 3


def test_el_system_prompt_va_cacheado():
    cliente = FakeAnthropic([[BloqueTexto("hola")]])
    correr(cliente, "hola")
    system = cliente.llamadas[0]["system"]
    assert isinstance(system, list)
    cacheados = [b for b in system if b.get("cache_control")]
    assert len(cacheados) == 1, "debe haber exactamente un punto de corte de cache"
    # el contexto de sesion va DESPUES del corte, para no invalidar el prefijo
    assert system.index(cacheados[0]) < len(system) - 1


def test_updateDataModel_solo_cuando_cambian_los_datos():
    """Mover un slider no debe remontar componentes."""
    solo_datos = [{"version": "v0.9", "updateDataModel": {
        "surfaceId": "inv-main", "path": "/sim", "value": {"p50": []}}}]
    cliente = FakeAnthropic([
        [BloqueToolUse("simulate_portfolio", {
            "asignacion": {"FND-GUB-CP": 0.5, "CETES-364": 0.5},
            "monto": 80000, "horizonte_anios": 5, "aportacion_mensual": 2500})],
        [BloqueToolUse("render_surface", {"messages": solo_datos})],
        [BloqueTexto("Ya actualicé la proyección.")],
    ])
    eventos, _ = correr(cliente, {"name": "simulate", "surfaceId": "inv-main",
                                  "context": {"amount": 80000, "horizon": 5, "monthly": 2500}})
    a2ui = [e.datos["message"] for e in eventos if e.tipo == "a2ui"]
    assert len(a2ui) == 1
    assert "updateDataModel" in a2ui[0]
    assert not any("updateComponents" in m for m in a2ui)


def test_la_accion_de_la_ui_llega_con_su_contexto():
    cliente = FakeAnthropic([[BloqueTexto("ok")]])
    _, sesion = correr(cliente, {"name": "profile_done", "surfaceId": "inv-main",
                                 "context": {"answers": [{"id": "horizonte", "value": 4}]}})
    primero = sesion.historial[0]["content"]
    assert "profile_done" in primero
    assert "horizonte" in primero


# --------------------------------------------------------- validacion y reintento
def test_blueprint_invalido_se_devuelve_al_modelo_y_se_corrige():
    malo = [{"version": "v0.9", "updateComponents": {"surfaceId": "inv-main", "components": [
        {"id": "root", "component": "inv.CryptoWidget"}]}}]
    cliente = FakeAnthropic([
        [BloqueToolUse("render_surface", {"messages": malo})],
        [BloqueToolUse("render_surface", {"messages": blueprint_perfilador()})],
        [BloqueTexto("Listo.")],
    ])
    eventos, sesion = correr(cliente, "hola")

    rechazos = [e for e in eventos if e.tipo == "render_rechazado"]
    assert len(rechazos) == 1
    assert any("inv.CryptoWidget" in err for err in rechazos[0].datos["errores"])

    # el error le volvio al modelo como tool_result is_error
    resultados = [c for m in sesion.historial if m["role"] == "user"
                  and isinstance(m["content"], list)
                  for c in m["content"] if c.get("type") == "tool_result"]
    assert any(r.get("is_error") for r in resultados)
    assert any("render_surface" in r["content"] for r in resultados)

    assert len([e for e in eventos if e.tipo == "a2ui"]) == 3
    assert eventos[-1].datos["render_ok"] is True


def test_tras_agotar_reintentos_monta_la_plantilla_de_respaldo():
    malo = [{"version": "v0.9", "updateComponents": {
        "surfaceId": "inv-main", "components": [{"id": "x", "component": "Nope"}]}}]
    cliente = FakeAnthropic([[BloqueToolUse("render_surface", {"messages": malo})]
                             for _ in range(4)])
    eventos, _ = correr(cliente, "hola")

    assert len([e for e in eventos if e.tipo == "render_rechazado"]) == 3
    a2ui = [e.datos["message"] for e in eventos if e.tipo == "a2ui"]
    assert a2ui, "el usuario no puede quedarse sin pantalla"
    componentes = a2ui[1]["updateComponents"]["components"]
    assert componentes[0]["component"] == "Card"
    assert componentes[0]["tone"] == "warning"


# ------------------------------------------- convencion de rutas fijas (bank.*)
def test_ruta_bank_correcta_no_genera_aviso():
    mensajes = [{"version": "v0.9", "updateComponents": {"surfaceId": "s", "components": [
        {"id": "root", "component": "bank.AccountsOverview",
         "cuentas": {"path": "/cuentas"}, "tarjetas": {"path": "/tarjetas"}},
    ]}}]
    assert _avisos_de_rutas_bank(mensajes) == []


def test_ruta_bank_desviada_genera_aviso():
    mensajes = [{"version": "v0.9", "updateComponents": {"surfaceId": "s", "components": [
        {"id": "root", "component": "bank.AccountsOverview",
         "cuentas": {"path": "/datos/cuentas"}, "tarjetas": {"path": "/tarjetas"}},
    ]}}]
    avisos = _avisos_de_rutas_bank(mensajes)
    assert len(avisos) == 1
    assert "/datos/cuentas" in avisos[0] and "/cuentas" in avisos[0]


def test_ruta_bank_literal_no_genera_aviso():
    """Un valor literal (no un binding) no es "la ruta equivocada": es otro caso."""
    mensajes = [{"version": "v0.9", "updateComponents": {"surfaceId": "s", "components": [
        {"id": "root", "component": "bank.SpendingBudgets", "alertas": []},
    ]}}]
    assert _avisos_de_rutas_bank(mensajes) == []


def test_render_con_ruta_bank_desviada_emite_warning_pero_no_rechaza():
    blueprint = [
        {"version": "v0.9", "createSurface": {"surfaceId": "bank-main", "catalogId": CATALOG_ID}},
        {"version": "v0.9", "updateDataModel": {"surfaceId": "bank-main", "path": "/alertas", "value": []}},
        {"version": "v0.9", "updateComponents": {"surfaceId": "bank-main", "components": [
            {"id": "root", "component": "bank.SpendingBudgets", "alertas": {"path": "/otra/ruta"}},
        ]}},
    ]
    cliente = FakeAnthropic([[BloqueToolUse("render_surface", {"messages": blueprint})],
                             [BloqueTexto("Listo.")]])
    eventos, _ = correr(cliente, "muéstrame mi control de gasto")
    assert eventos[-1].datos["render_ok"] is True   # no se rechaza, solo se avisa
    avisos = [e for e in eventos if e.tipo == "warning" and "avisos" in e.datos]
    assert any("bank.SpendingBudgets.alertas" in a for ev in avisos for a in ev.datos["avisos"])


# --------------------------------------------------------- errores de los servicios
def test_error_de_servicio_vuelve_como_tool_result_y_no_tumba_el_turno():
    cliente = FakeAnthropic([
        [BloqueToolUse("get_client_snapshot", {"client_id": "CLI-9999"})],
        [BloqueToolUse("get_client_snapshot", {"client_id": "CLI-0001"})],
        [BloqueTexto("Ya lo encontré.")],
    ])
    eventos, _ = correr(cliente, "quién soy")
    resultados = [e for e in eventos if e.tipo == "tool_result"]
    assert resultados[0].datos["ok"] is False
    assert "CLI-0001" in resultados[0].datos["resumen"]     # la sugerencia lista los validos
    assert resultados[1].datos["ok"] is True
    assert eventos[-1].tipo == "done"


def test_tool_inexistente_no_rompe_nada():
    cliente = FakeAnthropic([
        [BloqueToolUse("transferir_todo", {"a": "mi-cuenta"})],
        [BloqueTexto("Perdón, no tengo esa herramienta.")],
    ])
    eventos, _ = correr(cliente, "sácame el dinero")
    primero = next(e for e in eventos if e.tipo == "tool_result")
    assert primero.datos["ok"] is False
    assert "tool_desconocida" in primero.datos["resumen"]


# ------------------------------------------------------------------- orden segura
def test_place_order_no_ejecuta_en_el_primer_paso():
    asignacion = {"FND-GUB-CP": 0.3, "CETES-364": 0.7}
    cliente = FakeAnthropic([
        [BloqueToolUse("place_order", {
            "client_id": "CLI-0002", "asignacion": asignacion, "monto": 50000,
            "idempotency_key": "test-paso1"})],
        [BloqueTexto("Revísalo y confirma.")],
    ])
    eventos, sesion = correr(cliente, "inviérteme 50 mil")
    llamada = next(e for e in eventos if e.tipo == "tool_call")
    assert llamada.datos["efecto"] is True, "la UI tiene que saber que esta tool mueve dinero"
    resultado = next(e for e in eventos if e.tipo == "tool_result")
    assert resultado.datos["ok"] is True

    payload = payloads_de_tools(sesion)[0]
    assert '"estado": "pendiente"' in payload
    assert "confirmation_token" in payload
    assert '"requiere_confirmacion": true' in payload
    assert '"ejecutada"' not in payload


def test_place_order_con_token_inventado_se_rechaza():
    """El candado real: el modelo no puede ejecutar inventándose el token."""
    asignacion = {"FND-GUB-CP": 0.3, "CETES-364": 0.7}
    args = {"client_id": "CLI-0006", "asignacion": asignacion, "monto": 20000,
            "idempotency_key": "test-inventado"}
    cliente = FakeAnthropic([
        [BloqueToolUse("place_order", dict(args))],
        [BloqueToolUse("place_order", {**args, "confirmation_token": "token-que-me-invente"})],
        [BloqueTexto("No pude.")],
    ])
    eventos, sesion = correr(cliente, "inviérteme 20 mil")
    resultados = [e for e in eventos if e.tipo == "tool_result"]
    assert resultados[0].datos["ok"] is True
    assert resultados[1].datos["ok"] is False
    assert "confirmation_token" in payloads_de_tools(sesion)[1]
    # y la orden sigue sin ejecutarse
    from services import REGISTRO
    pendientes = REGISTRO["get_orders"]("CLI-0006", estado="pendiente")["ordenes"]
    assert any(o["idempotency_key"] == "test-inventado" for o in pendientes)


def test_confirm_payment_con_token_inventado_no_mueve_dinero():
    """El mismo candado que `place_order`, del lado de pagos."""
    import json

    from services import REGISTRO

    paso1 = FakeAnthropic([
        [BloqueToolUse("withdraw_cash", {"client_id": "CLI-0004", "monto": 500,
                                         "idempotency_key": "test-retiro-inventado"})],
        [BloqueTexto("Confírmalo en pantalla.")],
    ])
    eventos, sesion = correr(paso1, "sácame 500 sin tarjeta")
    llamada = next(e for e in eventos if e.tipo == "tool_call")
    assert llamada.datos["efecto"] is True
    pendiente = json.loads(payloads_de_tools(sesion)[0])
    assert pendiente["estado"] == "pendiente"
    resumen = next(e for e in eventos if e.tipo == "tool_result").datos["resumen"]
    assert pendiente["confirmation_token"] not in resumen, "el token no sale a la traza"

    paso2 = FakeAnthropic([
        [BloqueToolUse("confirm_payment", {"client_id": "CLI-0004",
                                           "payment_id": pendiente["payment_id"],
                                           "confirmation_token": "token-que-me-invente"})],
        [BloqueTexto("No pude.")],
    ])
    eventos2, _ = correr(paso2, {"name": "confirm_payment", "surfaceId": "pay-main", "context": {}})
    assert next(e for e in eventos2 if e.tipo == "tool_result").datos["ok"] is False
    pendientes = REGISTRO["get_payment_history"]("CLI-0004", estado="pendiente")["pagos"]
    assert any(p["payment_id"] == pendiente["payment_id"] for p in pendientes)


# ------------------------------------------------------------------------ limites
def test_corta_el_encadenado_infinito():
    cliente = FakeAnthropic(
        [[BloqueToolUse("get_risk_questions", {})] for _ in range(40)])
    eventos, _ = correr(cliente, "dale")
    assert len([e for e in eventos if e.tipo == "tool_call"]) <= 12
    assert any(e.tipo == "warning" for e in eventos)
    assert eventos[-1].tipo == "done"


def test_se_escribe_la_bitacora():
    registradas: list[tuple] = []
    cliente = FakeAnthropic([
        [BloqueToolUse("get_risk_questions", {})],
        [BloqueToolUse("render_surface", {"messages": blueprint_perfilador()})],
        [BloqueTexto("ok")],
    ])
    sesion = Sesion(session_id="sesion-bitacora", client_id="CLI-0001")
    agente = AgenteUIGenerativa(
        cliente=cliente, mcp=FakeClienteMCP(), modelo="falso",
        registrar_superficie=lambda *a: registradas.append(a))

    async def _ir():
        return [ev async for ev in agente.run_turn(sesion, "hola")]

    asyncio.run(_ir())
    assert len(registradas) == 1
    session_id, turno, surface_id, mensajes, tools = registradas[0]
    assert session_id == "sesion-bitacora"
    assert turno == 1
    assert surface_id == "inv-main"
    assert len(mensajes) == 3
    assert [t["name"] for t in tools] == ["get_risk_questions"]


def test_una_bitacora_que_falla_no_tumba_el_turno():
    def explota(*_a):
        raise RuntimeError("disco lleno")

    cliente = FakeAnthropic([
        [BloqueToolUse("render_surface", {"messages": blueprint_perfilador()})],
        [BloqueTexto("ok")],
    ])
    sesion = Sesion(session_id="s", client_id="CLI-0001")
    agente = AgenteUIGenerativa(cliente=cliente, mcp=FakeClienteMCP(), modelo="falso",
                                registrar_superficie=explota)

    async def _ir():
        return [ev async for ev in agente.run_turn(sesion, "hola")]

    eventos = asyncio.run(_ir())
    assert eventos[-1].tipo == "done"


# ------------------------------------------------------ contrato tools <-> servicios
def test_cada_tool_declarada_existe_como_servicio():
    from agent.tools import NOMBRES_DATOS
    from services import REGISTRO

    assert NOMBRES_DATOS == frozenset(REGISTRO), (
        "Se desincronizaron agent/tools.py y services/REGISTRO. "
        f"Solo en tools: {sorted(NOMBRES_DATOS - set(REGISTRO))}. "
        f"Solo en servicios: {sorted(set(REGISTRO) - NOMBRES_DATOS)}."
    )


@pytest.mark.parametrize("tool", sorted(
    t["name"] for t in __import__("agent.tools", fromlist=["x"]).TOOLS_DATOS))
def test_cada_tool_tiene_descripcion_util(tool):
    from agent.tools import TOOLS_DATOS
    spec = next(t for t in TOOLS_DATOS if t["name"] == tool)
    assert len(spec["description"]) > 40, f"{tool}: la descripción es el prompt, escríbela"
    assert spec["input_schema"]["type"] == "object"
