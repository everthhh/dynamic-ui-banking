"""Genera el guion simulado del front: web/src/fixtures/demo.json.

    python -m scripts.gen_fixtures

Esto es la "simulacion del sistema de componentes": los seis turnos del demo
(§06 del marco tecnico) con los MISMOS blueprints A2UI y los MISMOS numeros que
produciria el agente, pero grabados. Sirve para tres cosas:

  * desarrollar el renderer sin gastar tokens ni depender de la red;
  * tener un respaldo si la API se cae en medio de la presentacion
    (`?mock=1` y la demo corre igual);
  * que los blueprints del guion pasen por el MISMO validador que los del
    modelo, asi que si el catalogo cambia, el guion se rompe y nos enteramos.

Los montos, escenarios y folios salen de `services`, no estan escritos a mano.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from a2ui.models import CATALOG_ID, validate_a2ui

ROOT = Path(__file__).resolve().parent.parent
SALIDA = ROOT / "web" / "src" / "fixtures" / "demo.json"

CLIENT_ID = "CLI-0001"
SURFACE = "inv-main"
MONTO = 80_000.0
HORIZONTE = 5.0
APORTACION = 2_500.0


def v(msg: dict[str, Any]) -> dict[str, Any]:
    return {"version": "v0.9", **msg}


def _turno(disparador: dict[str, Any], eventos: list[dict[str, Any]]) -> dict[str, Any]:
    return {"disparador": disparador, "eventos": eventos}


def _tool(nombre: str, efecto: bool = False) -> dict[str, Any]:
    return {"type": "tool_call", "name": nombre, "efecto": efecto}


def _tool_ok(nombre: str, resumen: str) -> dict[str, Any]:
    return {"type": "tool_result", "name": nombre, "ok": True, "resumen": resumen}


def construir() -> dict[str, Any]:
    from services import REGISTRO

    snapshot = REGISTRO["get_client_snapshot"](CLIENT_ID)
    preguntas = REGISTRO["get_risk_questions"]()
    gasto = REGISTRO["get_spending_summary"](CLIENT_ID, meses=6)

    respuestas = [
        {"id": "horizonte", "value": 4},
        {"id": "reaccion_caida", "value": 3},
        {"id": "experiencia", "value": 2},
        {"id": "proposito", "value": 3},
    ]
    perfil = REGISTRO["score_risk_profile"](respuestas, client_id=None, guardar=False)
    propuesta = REGISTRO["propose_allocation"](
        perfil=perfil["perfil"], horizonte_anios=HORIZONTE, monto=MONTO)
    asignacion = propuesta["asignacion"]

    sim_sin_aporte = REGISTRO["simulate_portfolio"](asignacion, MONTO, HORIZONTE, 0)
    sim_con_aporte = REGISTRO["simulate_portfolio"](asignacion, MONTO, HORIZONTE, APORTACION)

    conservadora = REGISTRO["propose_allocation"](
        perfil="conservador", horizonte_anios=HORIZONTE, monto=MONTO)
    comparacion = REGISTRO["compare_allocations"](
        asignacion, conservadora["asignacion"], MONTO, HORIZONTE, APORTACION,
        etiqueta_izquierda=f"Tu perfil ({perfil['perfil']})",
        etiqueta_derecha="Conservador")

    orden_pendiente = REGISTRO["place_order"](
        client_id=CLIENT_ID, asignacion=asignacion, monto=MONTO,
        idempotency_key=f"{CLIENT_ID}-fixture-1")
    orden_ejecutada = REGISTRO["place_order"](
        client_id=CLIENT_ID, asignacion=asignacion, monto=MONTO,
        idempotency_key=f"{CLIENT_ID}-fixture-1",
        confirmation_token=orden_pendiente["confirmation_token"])
    snapshot_final = REGISTRO["get_client_snapshot"](CLIENT_ID)

    cap = min(gasto["capacidad_ahorro_mensual"], 10_000)
    tope_aportacion = max(1_000.0, round(cap / 500) * 500)

    # ------------------------------------------------------------------ turno 1
    t1 = _turno(
        {"tipo": "chat", "texto": "tengo 80 mil pesos parados y los podría dejar 5 años, ¿qué hago?"},
        [
            _tool("get_client_snapshot"),
            _tool_ok("get_client_snapshot",
                     f"{snapshot['nombre']} · perfil_vigente=False · "
                     f"efectivo {snapshot['efectivo_total']:,.0f}"),
            {"type": "text", "text":
                "Antes de proponerte algo necesito cuatro datos. Te tomo treinta segundos."},
            _tool("get_risk_questions"),
            _tool_ok("get_risk_questions", f"{preguntas['total']} preguntas"),
            {"type": "a2ui", "message": v({"createSurface": {
                "surfaceId": SURFACE, "catalogId": CATALOG_ID,
                "theme": {"primaryColor": "#EB0029"}}})},
            {"type": "a2ui", "message": v({"updateDataModel": {
                "surfaceId": SURFACE, "path": "/perfilador/questions",
                "value": preguntas["questions"]}})},
            {"type": "a2ui", "message": v({"updateComponents": {
                "surfaceId": SURFACE, "components": [
                    {"id": "root", "component": "Column",
                     "children": ["titulo", "perfilador"]},
                    {"id": "titulo", "component": "Text", "variant": "h2",
                     "text": f"Hola {snapshot['nombre'].split()[0]}, empecemos por tu perfil"},
                    {"id": "perfilador", "component": "inv.RiskProfiler",
                     "questions": {"path": "/perfilador/questions"},
                     "intro": "Con esto sé cuánto riesgo tiene sentido para ti. "
                              "Ninguna respuesta es la correcta.",
                     "action": {"event": {"name": "profile_done"}}},
                ]}})},
            {"type": "done", "turno": 1, "render_ok": True},
        ],
    )

    # ------------------------------------------------------------------ turno 2
    t2 = _turno(
        {"tipo": "accion", "name": "profile_done"},
        [
            _tool("score_risk_profile"),
            _tool_ok("score_risk_profile",
                     f"score {perfil['score']} · perfil {perfil['perfil']}"),
            _tool("get_spending_summary"),
            _tool_ok("get_spending_summary",
                     f"capacidad de ahorro {gasto['capacidad_ahorro_mensual']:,.0f}/mes"),
            _tool("propose_allocation"),
            _tool_ok("propose_allocation",
                     f"{len(propuesta['slices'])} bloques · rendimiento esperado "
                     f"{propuesta['rend_esperado_anual']:.2%}"),
            _tool("simulate_portfolio"),
            _tool_ok("simulate_portfolio",
                     f"p50 {sim_sin_aporte['valor_final']['p50']:,.0f}"),
            {"type": "text", "text":
                f"Saliste **{perfil['perfil']}** ({perfil['score']}/100). "
                f"{perfil['descripcion']} Te armé esta propuesta a {HORIZONTE:.0f} años."},
            {"type": "a2ui", "message": v({"updateDataModel": {
                "surfaceId": SURFACE, "path": "/perfil", "value": perfil}})},
            {"type": "a2ui", "message": v({"updateDataModel": {
                "surfaceId": SURFACE, "path": "/propuesta", "value": propuesta}})},
            {"type": "a2ui", "message": v({"updateDataModel": {
                "surfaceId": SURFACE, "path": "/sim", "value": {
                    "escenarios": sim_sin_aporte["escenarios"],
                    "horizonte": HORIZONTE,
                    "monto": MONTO,
                    "mensual": 0,
                    "aportado": sim_sin_aporte["total_aportado"],
                    "tir": sim_sin_aporte["tir_anual_p50"],
                    "final_p50": sim_sin_aporte["valor_final"]["p50"],
                    "dd": sim_sin_aporte["max_drawdown"],
                }}})},
            {"type": "a2ui", "message": v({"updateComponents": {
                "surfaceId": SURFACE, "components": [
                    {"id": "root", "component": "Column",
                     "children": ["encabezado", "metricas", "dona", "proyeccion",
                                  "controles", "pieComparar"]},
                    {"id": "encabezado", "component": "Row",
                     "children": ["titulo", "badgePerfil"]},
                    {"id": "titulo", "component": "Text", "variant": "h2",
                     "text": f"Propuesta {perfil['perfil']} a {HORIZONTE:.0f} años"},
                    {"id": "badgePerfil", "component": "Badge", "tone": "info",
                     "label": {"path": "/perfil/perfil"}},
                    {"id": "metricas", "component": "Row",
                     "children": ["statFinal", "statTir", "statCaida"]},
                    {"id": "statFinal", "component": "Stat", "format": "moneda",
                     "label": "Escenario medio a 5 años",
                     "value": {"path": "/sim/final_p50"}},
                    {"id": "statTir", "component": "Stat", "format": "porcentaje",
                     "label": "Rendimiento anual", "value": {"path": "/sim/tir"}},
                    {"id": "statCaida", "component": "Stat", "format": "porcentaje",
                     "label": "Peor caída esperada", "value": {"path": "/sim/dd"},
                     "hint": "Promedio de la mayor caída en cada escenario"},
                    {"id": "dona", "component": "inv.AllocationDonut",
                     "slices": {"path": "/propuesta/slices"},
                     "total": {"path": "/propuesta/monto"},
                     "subtitulo": "Siete bloques; cada uno tiene una razón de estar.",
                     "action": {"event": {"name": "select_instrument"}}},
                    {"id": "proyeccion", "component": "inv.ProjectionChart",
                     "scenarios": {"path": "/sim/escenarios"},
                     "horizonYears": {"path": "/sim/horizonte"},
                     "aportado": {"path": "/sim/aportado"},
                     "disclaimer": sim_sin_aporte["disclaimer"]},
                    {"id": "controles", "component": "Card",
                     "title": "Muévele y vuelvo a calcular",
                     "children": ["sliderMonto", "sliderPlazo", "sliderMensual"]},
                    {"id": "sliderMonto", "component": "inv.AmountSlider",
                     "label": "Monto inicial", "value": {"path": "/sim/monto"},
                     "min": 10000, "max": 300000, "step": 5000, "format": "moneda",
                     "action": {"event": {"name": "simulate"}}},
                    {"id": "sliderPlazo", "component": "inv.AmountSlider",
                     "label": "Plazo en años", "value": {"path": "/sim/horizonte"},
                     "min": 1, "max": 20, "step": 1, "format": "anios",
                     "action": {"event": {"name": "simulate"}}},
                    {"id": "sliderMensual", "component": "inv.AmountSlider",
                     "label": "Aportación mensual", "value": {"path": "/sim/mensual"},
                     "min": 0, "max": tope_aportacion, "step": 500, "format": "moneda",
                     "action": {"event": {"name": "simulate"}}},
                    {"id": "pieComparar", "component": "Row",
                     "children": ["btnComparar", "btnOrden"]},
                    {"id": "btnComparar", "component": "Button", "variant": "secondary",
                     "label": "¿Y si fuera más conservador?",
                     "action": {"event": {"name": "compare"}}},
                    {"id": "btnOrden", "component": "Button", "variant": "primary",
                     "label": "Quiero invertir así",
                     "action": {"event": {
                         "name": "ask",
                         "context": {"prompt": "Arma la orden con esta propuesta"}}}},
                ]}})},
            {"type": "done", "turno": 2, "render_ok": True},
        ],
    )

    # ------------------------------------------------------------------ turno 3
    t3 = _turno(
        {"tipo": "accion", "name": "simulate"},
        [
            _tool("simulate_portfolio"),
            _tool_ok("simulate_portfolio",
                     f"con {APORTACION:,.0f}/mes · p50 "
                     f"{sim_con_aporte['valor_final']['p50']:,.0f}"),
            {"type": "text", "text":
                f"Con {APORTACION:,.0f} al mes el escenario medio sube a "
                f"{sim_con_aporte['valor_final']['p50']:,.0f}."},
            # UN solo mensaje, y de datos: los componentes no se remontan.
            {"type": "a2ui", "message": v({"updateDataModel": {
                "surfaceId": SURFACE, "path": "/sim", "value": {
                    "escenarios": sim_con_aporte["escenarios"],
                    "horizonte": HORIZONTE,
                    "monto": MONTO,
                    "mensual": APORTACION,
                    "aportado": sim_con_aporte["total_aportado"],
                    "tir": sim_con_aporte["tir_anual_p50"],
                    "final_p50": sim_con_aporte["valor_final"]["p50"],
                    "dd": sim_con_aporte["max_drawdown"],
                }}})},
            {"type": "done", "turno": 3, "render_ok": True},
        ],
    )

    # ------------------------------------------------------------------ turno 4
    t4 = _turno(
        {"tipo": "accion", "name": "compare"},
        [
            _tool("propose_allocation"),
            _tool_ok("propose_allocation", "alternativa conservadora"),
            _tool("compare_allocations"),
            _tool_ok("compare_allocations",
                     f"marcador {comparacion['marcador']['izquierda']}-"
                     f"{comparacion['marcador']['derecha']}"),
            {"type": "text", "text":
                "Las puse lado a lado con los mismos supuestos. La conservadora casi no cae, "
                "pero deja mucho sobre la mesa a cinco años."},
            {"type": "a2ui", "message": v({"updateDataModel": {
                "surfaceId": SURFACE, "path": "/comparacion", "value": comparacion}})},
            {"type": "a2ui", "message": v({"updateComponents": {
                "surfaceId": SURFACE, "components": [
                    {"id": "root", "component": "Column",
                     "children": ["titulo", "panel", "controles", "pie"]},
                    {"id": "titulo", "component": "Text", "variant": "h2",
                     "text": "Tu perfil contra una versión conservadora"},
                    {"id": "panel", "component": "inv.ComparePanel",
                     "left": {"path": "/comparacion/izquierda"},
                     "right": {"path": "/comparacion/derecha"},
                     "metrics": {"path": "/comparacion/filas"},
                     "disclaimer": comparacion["disclaimer"],
                     "action": {"event": {"name": "select_allocation"}}},
                    {"id": "controles", "component": "Card",
                     "title": "Los mismos supuestos en las dos",
                     "children": ["sliderMensual"]},
                    {"id": "sliderMensual", "component": "inv.AmountSlider",
                     "label": "Aportación mensual", "value": {"path": "/sim/mensual"},
                     "min": 0, "max": tope_aportacion, "step": 500, "format": "moneda",
                     "action": {"event": {"name": "simulate"}}},
                    {"id": "pie", "component": "Row", "children": ["btnVolver"]},
                    {"id": "btnVolver", "component": "Button", "variant": "primary",
                     "label": "Me quedo con mi perfil y quiero invertir",
                     "action": {"event": {
                         "name": "ask",
                         "context": {"prompt": "Arma la orden con la propuesta original"}}}},
                ]}})},
            {"type": "done", "turno": 4, "render_ok": True},
        ],
    )

    # ------------------------------------------------------------------ turno 5
    t5 = _turno(
        {"tipo": "accion", "name": "ask"},
        [
            _tool("place_order", efecto=True),
            _tool_ok("place_order",
                     f"estado pendiente · folio {orden_pendiente['folio']} · "
                     "requiere confirmación"),
            {"type": "text", "text":
                "Revisa el ticket. No se ejecuta nada hasta que lo confirmes."},
            {"type": "a2ui", "message": v({"updateDataModel": {
                "surfaceId": SURFACE, "path": "/orden", "value": orden_pendiente}})},
            {"type": "a2ui", "message": v({"updateComponents": {
                "surfaceId": SURFACE, "components": [
                    {"id": "root", "component": "Column",
                     "children": ["titulo", "ticket", "dona"]},
                    {"id": "titulo", "component": "Text", "variant": "h2",
                     "text": "Confirma la orden"},
                    {"id": "ticket", "component": "inv.OrderTicket",
                     "order": {"path": "/orden"},
                     "requiresConfirmation": True,
                     "disclaimer": orden_pendiente["disclaimer"],
                     "action": {"event": {"name": "place_order"}}},
                    {"id": "dona", "component": "inv.AllocationDonut",
                     "slices": {"path": "/propuesta/slices"},
                     "total": {"path": "/propuesta/monto"},
                     "subtitulo": "Así queda repartido."},
                ]}})},
            {"type": "done", "turno": 5, "render_ok": True},
        ],
    )

    # ------------------------------------------------------------------ turno 6
    t6 = _turno(
        {"tipo": "accion", "name": "place_order"},
        [
            _tool("place_order", efecto=True),
            _tool_ok("place_order",
                     f"EJECUTADA · folio {orden_ejecutada['folio']} · "
                     f"saldo {orden_ejecutada['saldo_despues']:,.2f}"),
            _tool("get_client_snapshot"),
            _tool_ok("get_client_snapshot",
                     f"{len(snapshot_final['posiciones'])} posiciones"),
            {"type": "text", "text":
                f"Listo. Folio {orden_ejecutada['folio']}. Así queda tu cuenta."},
            {"type": "a2ui", "message": v({"updateDataModel": {
                "surfaceId": SURFACE, "path": "/orden", "value": orden_ejecutada}})},
            {"type": "a2ui", "message": v({"updateDataModel": {
                "surfaceId": SURFACE, "path": "/cuenta", "value": {
                    "posiciones": snapshot_final["posiciones"],
                    "inversion": snapshot_final["inversion"],
                    "patrimonio": snapshot_final["patrimonio_total"],
                }}})},
            # Tarea nueva: estado de cuenta. Superficie nueva.
            {"type": "a2ui", "message": v({"createSurface": {
                "surfaceId": "inv-estado", "catalogId": CATALOG_ID}})},
            {"type": "a2ui", "message": v({"updateDataModel": {
                "surfaceId": "inv-estado", "path": "/cuenta", "value": {
                    "posiciones": snapshot_final["posiciones"],
                    "inversion": snapshot_final["inversion"],
                    "patrimonio": snapshot_final["patrimonio_total"],
                }}})},
            {"type": "a2ui", "message": v({"updateDataModel": {
                "surfaceId": "inv-estado", "path": "/orden", "value": orden_ejecutada}})},
            {"type": "a2ui", "message": v({"updateComponents": {
                "surfaceId": "inv-estado", "components": [
                    {"id": "root", "component": "Column",
                     "children": ["titulo", "folio", "posiciones", "nota"]},
                    {"id": "titulo", "component": "Text", "variant": "h2",
                     "text": "Tu cuenta de inversión"},
                    {"id": "folio", "component": "Badge", "tone": "positive",
                     "label": f"Orden {orden_ejecutada['folio']} ejecutada"},
                    {"id": "posiciones", "component": "inv.PositionsTable",
                     "positions": {"path": "/cuenta/posiciones"},
                     "resumen": {"path": "/cuenta/inversion"},
                     "action": {"event": {"name": "select_instrument"}}},
                    {"id": "nota", "component": "Text", "variant": "caption",
                     "tone": "muted",
                     "text": "Valuación con series sintéticas. Operación simulada."},
                ]}})},
            {"type": "done", "turno": 6, "render_ok": True},
        ],
    )

    turnos = [t1, t2, t3, t4, t5, t6]

    # Todo blueprint del guion pasa por el mismo validador que los del modelo.
    for i, t in enumerate(turnos, 1):
        mensajes = [e["message"] for e in t["eventos"] if e["type"] == "a2ui"]
        if not mensajes:
            continue
        res = validate_a2ui(mensajes)
        if not res.ok:
            raise SystemExit(
                f"El blueprint del turno {i} del guion no valida:\n"
                + "\n".join(f"  - {e}" for e in res.errores)
            )

    return {
        "generado_por": "scripts/gen_fixtures.py",
        "nota": "Numeros reales de services/ con la semilla fija del seed. "
                "No editar a mano: corre `python -m scripts.gen_fixtures`.",
        "client_id": CLIENT_ID,
        "clientes": _clientes(),
        "turnos": turnos,
    }


def _clientes() -> list[dict[str, Any]]:
    from bank import db
    with db.session(readonly=True) as conn:
        filas = db.query(
            conn,
            "SELECT c.client_id, c.nombre, c.segmento, c.ingreso_mensual,"
            "  (SELECT COUNT(*) FROM risk_profiles r WHERE r.client_id = c.client_id"
            "    AND r.vigente_hasta >= (SELECT fecha_valuacion FROM market_params WHERE id=1))"
            "   AS n FROM clients c ORDER BY c.client_id")
    return [{"client_id": f["client_id"], "nombre": f["nombre"], "segmento": f["segmento"],
             "ingreso_mensual": f["ingreso_mensual"], "perfil_vigente": bool(f["n"])}
            for f in filas]


def main() -> int:
    # El guion ejecuta una orden real, asi que se genera contra una copia
    # desechable de la base: `data/bank.sqlite` queda intacta.
    from bank import db, seed

    with tempfile.TemporaryDirectory() as tmp:
        destino = Path(tmp) / "bank.sqlite"
        original = db.DB_PATH
        os.environ["BANK_DB_PATH"] = str(destino)
        db.DB_PATH = destino
        try:
            seed.construir(destino)
            datos = construir()
        finally:
            db.DB_PATH = original
            os.environ.pop("BANK_DB_PATH", None)

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(len(t["eventos"]) for t in datos["turnos"])
    print(f"escrito {SALIDA.relative_to(ROOT)} · {len(datos['turnos'])} turnos · {total} eventos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
