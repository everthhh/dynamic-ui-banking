"""Test de contrato del catalogo.

Tres cosas tienen que decir lo mismo: `a2ui/catalog.json`, el fragmento del
system prompt y los tipos de TypeScript. Este archivo es lo que hace que no se
desalineen sin que nadie se de cuenta.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from a2ui.models import (
    ACCIONES,
    CATALOG,
    CATALOG_ID,
    COMPONENTES,
    validate_a2ui,
)

ROOT = Path(__file__).resolve().parents[2]
PROMPT = ROOT / "agent" / "catalog_prompt.md"
TS = ROOT / "web" / "src" / "catalog.types.ts"


# --------------------------------------------------------------- forma del catalogo
def test_catalogo_bien_formado():
    assert CATALOG["a2uiVersion"] == "v0.9"
    assert CATALOG_ID.startswith("https://")
    assert CATALOG["theme"]["primaryColor"] == "#EB0029"
    assert COMPONENTES, "el catálogo no puede estar vacío"


@pytest.mark.parametrize("nombre", sorted(COMPONENTES))
def test_cada_componente_declara_lo_minimo(nombre):
    spec = COMPONENTES[nombre]
    assert spec.get("tipo") in ("primitivo", "dominio"), nombre
    assert spec.get("cuando"), f"{nombre} no dice cuándo usarse; el modelo lo va a adivinar"
    assert isinstance(spec.get("props", {}), dict)
    assert isinstance(spec.get("children", False), bool)
    for prop, ps in spec["props"].items():
        assert ps.get("tipo"), f"{nombre}.{prop} sin tipo"
        if ps["tipo"] == "enum":
            assert ps.get("valores"), f"{nombre}.{prop} es enum sin valores"
            if "default" in ps:
                assert ps["default"] in ps["valores"], f"{nombre}.{prop} default fuera del enum"


def test_acciones_referenciadas_existen():
    for nombre, spec in COMPONENTES.items():
        for accion in spec.get("emite", []):
            assert accion in ACCIONES, f"{nombre} emite {accion!r}, que no está declarada"
    for accion, spec in ACCIONES.items():
        for comp in spec.get("emitida_por", []):
            assert comp in COMPONENTES, f"la acción {accion!r} dice venir de {comp!r}, inexistente"


def test_componentes_de_dominio_llevan_prefijo():
    """Cada dominio tiene su prefijo ('inv.', 'bank.', ...); los primitivos no llevan ninguno."""
    for nombre, spec in COMPONENTES.items():
        if spec["tipo"] == "dominio":
            assert "." in nombre, nombre
        else:
            assert "." not in nombre, nombre


# --------------------------------------------------- artefactos derivados alineados
def test_artefactos_generados_estan_al_dia():
    r = subprocess.run(
        [sys.executable, "-m", "scripts.gen_catalog_artifacts", "--check"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr


@pytest.mark.parametrize("nombre", sorted(COMPONENTES))
def test_prompt_y_tipos_mencionan_cada_componente(nombre):
    assert f"`{nombre}`" in PROMPT.read_text(encoding="utf-8"), f"{nombre} falta en el prompt"
    assert json.dumps(nombre) in TS.read_text(encoding="utf-8"), f"{nombre} falta en los tipos TS"


# ------------------------------------------------------------------- blueprint valido
def blueprint_valido() -> list[dict]:
    return [
        {"version": "v0.9", "createSurface": {
            "surfaceId": "inv-main", "catalogId": CATALOG_ID,
            "theme": {"primaryColor": "#EB0029"}}},
        {"version": "v0.9", "updateComponents": {"surfaceId": "inv-main", "components": [
            {"id": "root", "component": "Column", "children": ["h", "donut", "proj", "cta"]},
            {"id": "h", "component": "Text", "text": "Propuesta moderada a 5 años",
             "variant": "h2"},
            {"id": "donut", "component": "inv.AllocationDonut",
             "slices": {"path": "/propuesta/slices"},
             "total": {"path": "/propuesta/monto"}},
            {"id": "proj", "component": "inv.ProjectionChart",
             "scenarios": {"path": "/sim/escenarios"},
             "horizonYears": {"path": "/sim/horizonte"},
             "disclaimer": "Simulación sobre datos sintéticos."},
            {"id": "cta", "component": "inv.OrderTicket",
             "order": {"path": "/orden"}, "requiresConfirmation": True,
             "disclaimer": "Operación simulada.",
             "action": {"event": {"name": "place_order"}}},
        ]}},
        {"version": "v0.9", "updateDataModel": {
            "surfaceId": "inv-main", "path": "/sim/escenarios",
            "value": {"p10": [], "p50": [], "p90": []}}},
    ]


def test_blueprint_de_referencia_pasa():
    res = validate_a2ui(blueprint_valido())
    assert res.ok, res.errores
    assert res.superficies == ["inv-main"]


def test_acepta_la_forma_de_la_tool():
    assert validate_a2ui({"messages": blueprint_valido()}).ok


def test_deleteSurface_valido():
    res = validate_a2ui([{"version": "v0.9", "deleteSurface": {"surfaceId": "inv-main"}}])
    assert res.ok, res.errores


def test_blueprint_banca_personal_pasa():
    mensajes = [
        {"version": "v0.9", "createSurface": {"surfaceId": "bank-main", "catalogId": CATALOG_ID}},
        {"version": "v0.9", "updateComponents": {"surfaceId": "bank-main", "components": [
            {"id": "root", "component": "Column", "children": ["cuentas", "presupuestos"]},
            {"id": "cuentas", "component": "bank.AccountsOverview",
             "cuentas": {"path": "/cuentas"}, "tarjetas": {"path": "/tarjetas"}},
            {"id": "presupuestos", "component": "bank.SpendingBudgets",
             "alertas": {"path": "/alertas"}},
        ]}},
    ]
    res = validate_a2ui(mensajes)
    assert res.ok, res.errores


# ------------------------------------------------------------------ casos que fallan
def _solo_componentes(componentes: list[dict]) -> list[dict]:
    return [{"version": "v0.9",
             "updateComponents": {"surfaceId": "s", "components": componentes}}]


CASOS_INVALIDOS = {
    "componente fuera del catalogo": _solo_componentes([
        {"id": "root", "component": "inv.CryptoWidget"}]),
    "prop obligatoria faltante": _solo_componentes([
        {"id": "root", "component": "Text"}]),
    "enum invalido": _solo_componentes([
        {"id": "root", "component": "Text", "text": "x", "variant": "titulo-gigante"}]),
    "prop no declarada": _solo_componentes([
        {"id": "root", "component": "Text", "text": "x", "color": "#fff"}]),
    "binding en prop no enlazable": _solo_componentes([
        {"id": "root", "component": "inv.AmountSlider", "label": "Monto",
         "value": 1, "min": 0, "max": 10, "step": {"path": "/paso"},
         "action": {"event": {"name": "simulate"}}}]),
    "ruta sin slash": _solo_componentes([
        {"id": "root", "component": "Text", "text": {"path": "sin-slash"}}]),
    "accion inexistente": _solo_componentes([
        {"id": "root", "component": "Button", "label": "Ir",
         "action": {"event": {"name": "transferir_a_mi_cuenta"}}}]),
    "ticket sin confirmacion": _solo_componentes([
        {"id": "root", "component": "inv.OrderTicket", "order": {},
         "requiresConfirmation": False, "disclaimer": "x",
         "action": {"event": {"name": "place_order"}}}]),
    "ticket con accion equivocada": _solo_componentes([
        {"id": "root", "component": "inv.OrderTicket", "order": {},
         "requiresConfirmation": True, "disclaimer": "x",
         "action": {"event": {"name": "simulate"}}}]),
    "action con functionCall (no soportado)": _solo_componentes([
        {"id": "root", "component": "Button", "label": "Ir",
         "action": {"functionCall": {"call": "cerrarModal"}}}]),
    "action sin event": _solo_componentes([
        {"id": "root", "component": "Button", "label": "Ir", "action": {}}]),
    "children en componente que no anida": _solo_componentes([
        {"id": "root", "component": "Text", "text": "x", "children": ["a"]}]),
    "falta root": _solo_componentes([
        {"id": "titulo", "component": "Text", "text": "x"}]),
    "hijo huerfano": _solo_componentes([
        {"id": "root", "component": "Column", "children": ["no-existe"]}]),
    "ids repetidos": _solo_componentes([
        {"id": "root", "component": "Column", "children": ["a"]},
        {"id": "a", "component": "Text", "text": "1"},
        {"id": "a", "component": "Text", "text": "2"}]),
    "columna invalida en tabla": _solo_componentes([
        {"id": "root", "component": "inv.InstrumentTable", "rows": [],
         "columns": ["nombre", "precio_objetivo"]}]),
    "dos acciones en un mensaje": [
        {"version": "v0.9",
         "createSurface": {"surfaceId": "s", "catalogId": CATALOG_ID},
         "updateDataModel": {"surfaceId": "s", "path": "/a", "value": 1}}],
    "version equivocada": [
        {"version": "v0.8", "createSurface": {"surfaceId": "s", "catalogId": CATALOG_ID}}],
    "catalogId ajeno": [
        {"version": "v0.9",
         "createSurface": {"surfaceId": "s", "catalogId": "https://otro/catalog.json"}}],
    "updateDataModel sin value": [
        {"version": "v0.9", "updateDataModel": {"surfaceId": "s", "path": "/a"}}],
    "lista vacia": [],
    "no es lista": {"hola": 1},
}


@pytest.mark.parametrize("caso", sorted(CASOS_INVALIDOS))
def test_casos_invalidos_se_rechazan(caso):
    res = validate_a2ui(CASOS_INVALIDOS[caso])
    assert not res.ok, f"{caso}: debió fallar y pasó"
    assert res.errores


@pytest.mark.parametrize("caso", sorted(CASOS_INVALIDOS))
def test_el_error_es_accionable(caso):
    """Un error que no nombra el problema no sirve para que el modelo se corrija."""
    texto = validate_a2ui(CASOS_INVALIDOS[caso]).para_el_modelo()
    assert "render_surface" in texto
    assert len(texto.splitlines()) >= 2
    assert all(len(linea) > 20 for linea in texto.splitlines()[1:3])


def test_aviso_por_componente_inalcanzable():
    res = validate_a2ui(_solo_componentes([
        {"id": "root", "component": "Column", "children": ["a"]},
        {"id": "a", "component": "Text", "text": "visible"},
        {"id": "huerfano", "component": "Text", "text": "nadie me pinta"},
    ]))
    assert res.ok
    assert any("huerfano" in a for a in res.avisos)
