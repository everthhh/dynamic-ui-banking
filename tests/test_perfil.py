"""Perfil financiero y recomendaciones.

Tres niveles, de adentro hacia afuera:

  1. las deducciones puras con datos armados a mano, sin base: que una
     suscripcion se detecte por comportamiento, que un aguinaldo no vuelva
     variable un sueldo, que el habito de pago salga de los estados de cuenta;
  2. el perfil de los 8 clientes sembrados: que sus cifras cuadren y que
     DESCUBRA los habitos que declara cada persona, sin leerlos de ningun lado;
  3. el contrato entre el catalogo de herramientas, los servicios y el prompt.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from a2ui.models import COMPONENTES
from agent.prompts import COMPONENTES_POR_HERRAMIENTA, REGLAS
from bank.finance import deuda
from bank.finance import perfil as perfil_mod
from bank.finance import recomendaciones as recs
from services import REGISTRO, ServiceError, profile
from services.profile import TOOLS_POR_HERRAMIENTA

CLIENTES = [f"CLI-{i:04d}" for i in range(1, 9)]
HOY = date(2026, 9, 1)
CLAVES = perfil_mod.meses_de_ventana(HOY)


def _mov(fecha: str, monto: float, categoria: str, comercio: str = "Comercio (sim)") -> dict:
    return {"fecha": f"{fecha}T12:00:00", "tipo": "cargo", "monto": monto,
            "categoria": categoria, "comercio": comercio, "descripcion": "Compra",
            "card_id": None}


# ===========================================================================
# 1. deducciones puras
# ===========================================================================
def test_la_ventana_son_los_12_meses_completos_antes_de_la_valuacion():
    assert CLAVES[0] == "2025-09"
    assert CLAVES[-1] == "2026-08"
    assert len(CLAVES) == 12


def test_un_aguinaldo_no_vuelve_variable_un_sueldo():
    sueldo = [48_000.0] * 11 + [72_000.0]
    assert perfil_mod.variacion_robusta(sueldo) < perfil_mod.CV_INGRESO_VARIABLE
    negocio = [95_000 * f for f in (0.6, 1.3, 0.8, 1.1, 0.7, 1.4, 0.9, 1.2, 0.75, 1.25, 1.0, 0.65)]
    assert perfil_mod.variacion_robusta(negocio) >= perfil_mod.CV_INGRESO_VARIABLE


def test_una_suscripcion_se_detecta_por_comportamiento_no_por_nombre():
    movs = [_mov(f"{k}-05", 219.0, "entretenimiento", "Plataforma (sim)") for k in CLAVES[-6:]]
    # Varias compras al mes en el mismo comercio: habito, no suscripcion.
    movs += [_mov(f"{k}-{d:02d}", 60.0 + d * 7, "restaurantes", "Cafetería (sim)")
             for k in CLAVES[-6:] for d in (3, 12, 20)]
    # Renta: se repite igual, pero no es consumo discrecional.
    movs += [_mov(f"{k}-01", 12_000.0, "renta", "Arrendador (sim)") for k in CLAVES[-6:]]
    subs = perfil_mod.detectar_suscripciones(movs, CLAVES)
    assert [s["comercio"] for s in subs] == ["Plataforma (sim)"]
    assert subs[0]["monto_mensual"] == 219.0


def test_un_cargo_mensual_que_cambia_de_monto_no_es_suscripcion():
    movs = [_mov(f"{k}-05", 300.0 + 100 * i, "entretenimiento", "Cine (sim)")
            for i, k in enumerate(CLAVES[-6:])]
    assert perfil_mod.detectar_suscripciones(movs, CLAVES) == []


def test_las_compras_chicas_se_suman_y_excluyen_las_suscripciones():
    movs = [_mov(f"{k}-{d:02d}", 80.0, "restaurantes", "Cafetería (sim)")
            for k in CLAVES for d in range(1, 21)]
    movs += [_mov(f"{k}-05", 199.0, "entretenimiento", "App (sim)") for k in CLAVES]
    subs = perfil_mod.detectar_suscripciones(movs, CLAVES)
    hormiga = perfil_mod.detectar_gasto_hormiga(movs, CLAVES, subs, 20_000)
    assert hormiga["compras_mes"] == 20
    assert hormiga["gasto_mensual"] == 1_600
    assert hormiga["pct_ingreso"] == pytest.approx(0.08)


TARJETA = {"card_id": "CRD-X", "last4": "1234", "alias": None,
           "limite_credito": 50_000, "saldo_utilizado": 20_000, "tasa_anual": 0.45}


def _estado(corte: str, saldo: float, minimo: float, pagado: float, atraso: int) -> dict:
    limite = (date.fromisoformat(corte) + timedelta(days=20)).isoformat()
    return {"card_id": "CRD-X", "fecha_corte": corte, "fecha_limite_pago": limite,
            "saldo_al_corte": saldo, "pago_minimo": minimo, "pagado": pagado,
            "fecha_pago": limite, "dias_atraso": atraso,
            "intereses": 0.0 if pagado >= saldo else 300.0,
            "comisiones": 450.0 if atraso else 0.0}


@pytest.mark.parametrize("pagos,habito", [
    ([(10_000, 500, 10_000, 0)] * 10, "totalero"),
    ([(10_000, 500, 520, 0)] * 10, "paga_minimo"),
    ([(10_000, 500, 520, 8)] * 5 + [(10_000, 500, 520, 0)] * 5, "paga_tarde"),
    ([(10_000, 500, 5_000, 0)] * 10, "revolvente"),
])
def test_el_habito_de_pago_sale_de_los_estados_de_cuenta(pagos, habito):
    estados = [_estado(f"{k}-05", *p) for k, p in zip(CLAVES[:10], pagos)]
    ficha = perfil_mod.comportamiento_tarjeta(TARJETA, estados, HOY, CLAVES)
    assert ficha["habito"] == habito
    assert ficha["cortes_evaluados"] == 10


def test_un_corte_que_todavia_se_puede_pagar_no_cuenta():
    estados = [_estado("2026-08-25", 10_000, 500, 0, 0)]      # vence en septiembre
    ficha = perfil_mod.comportamiento_tarjeta(TARJETA, estados, HOY, CLAVES)
    assert ficha["cortes_evaluados"] == 0
    assert ficha["habito"] == "sin_uso"


def test_la_prioridad_crece_con_el_impacto_y_castiga_lo_que_no_existe():
    assert recs.prioridad("media", 0.01, True) < recs.prioridad("media", 0.10, True)
    assert recs.prioridad("baja", 5.0, True) == recs.PUNTOS_URGENCIA["baja"] + recs.TOPE_PUNTOS_IMPACTO
    assert (recs.prioridad("alta", 0.05, False)
            == recs.prioridad("alta", 0.05, True) - recs.PENALIZACION_NO_DISPONIBLE)


# ------------------------------------------------------------------- deuda
def test_pagar_mas_liquida_antes_y_cuesta_menos():
    lento = deuda.plan_pago_fijo(30_000, 0.45, 2_000)
    rapido = deuda.plan_pago_fijo(30_000, 0.45, 4_000)
    assert lento["liquidada"] and rapido["liquidada"]
    assert rapido["meses"] < lento["meses"]
    assert rapido["total_intereses"] < lento["total_intereses"]


def test_el_pago_para_liquidar_en_12_meses_liquida_en_12_meses():
    pago = deuda.pago_para_liquidar(30_000, 0.45, 12)
    assert deuda.plan_pago_fijo(30_000, 0.45, pago)["meses"] == 12


def test_pagar_solo_el_minimo_tarda_mas_y_cuesta_mas():
    minimo = deuda.plan_pago_minimo(30_000, 0.45)
    plan = deuda.plan_pago_fijo(30_000, 0.45, deuda.pago_para_liquidar(30_000, 0.45, 12))
    assert minimo["meses"] > plan["meses"]
    assert minimo["total_intereses"] > plan["total_intereses"]


def test_un_pago_que_no_cubre_los_intereses_se_rechaza():
    with pytest.raises(deuda.PlanInvalido):
        deuda.plan_pago_fijo(30_000, 0.45, 1_000)     # el interes del primer mes es 1,125


# ===========================================================================
# 2. los clientes sembrados
# ===========================================================================
@pytest.mark.parametrize("client_id", CLIENTES)
def test_el_perfil_cuadra(client_id):
    p = REGISTRO["get_financial_profile"](client_id)
    json.dumps(p)
    f = p["flujo"]
    assert f["ahorro_mensual"] == pytest.approx(
        f["ingreso_mensual"] - f["consumo_mensual"] - f["pagos_credito_mensual"]
        - f["costo_financiero_mensual"], abs=0.05)
    assert f["consumo_mensual"] == pytest.approx(
        f["consumo_esencial_mensual"] + f["consumo_discrecional_mensual"], abs=0.05)
    assert sum(c["participacion"] for c in p["consumo"]["por_categoria"]) == pytest.approx(1, abs=0.01)
    for salud in (p["salud_financiera"], p["credito"]["salud_crediticia"]):
        assert 0 <= salud["score"] <= 100
        assert salud["score"] == pytest.approx(sum(x["aporte"] for x in salud["desglose"]), abs=0.1)
        assert sum(x["peso"] for x in salud["desglose"]) == pytest.approx(1)
    assert p["productos"]["total"] == len(p["productos"]["lista"])
    assert p["resumen"].startswith(p["identidad"]["nombre_corto"])
    assert all(r["dato"] for r in p["rasgos"]), "cada rasgo trae el dato que lo sostiene"


def _perfil(client_id: str) -> dict:
    return REGISTRO["get_financial_profile"](client_id)


def test_los_habitos_de_cada_persona_se_descubren_en_sus_movimientos():
    """bank/personas.py declara habitos; el perfil no los lee, los deduce."""
    def habito(cid: str) -> str:
        return _perfil(cid)["credito"]["tarjetas"][0]["habito"]

    assert habito("CLI-0001") == "totalero"
    assert habito("CLI-0003") in ("paga_minimo", "revolvente")
    assert habito("CLI-0005") in ("paga_tarde", "paga_minimo")
    assert _perfil("CLI-0007")["flujo"]["tipo_ingreso"] == "variable"
    assert _perfil("CLI-0002")["flujo"]["tipo_ingreso"] == "fijo"
    assert len(_perfil("CLI-0008")["consumo"]["suscripciones"]["detectadas"]) >= 5
    assert _perfil("CLI-0003")["consumo"]["gasto_hormiga"]["pct_ingreso"] >= 0.08
    assert _perfil("CLI-0006")["credito"]["deuda_total"] < _perfil("CLI-0006")["liquidez"]["disponible"]


def test_el_revolvente_paga_intereses_y_el_totalero_no():
    assert _perfil("CLI-0003")["credito"]["tarjetas"][0]["intereses_12m"] > 0
    assert _perfil("CLI-0001")["credito"]["tarjetas"][0]["intereses_12m"] == 0


@pytest.mark.parametrize("client_id", CLIENTES)
def test_cada_recomendacion_trae_evidencia_impacto_y_herramienta(client_id):
    r = REGISTRO["get_recommendations"](client_id, limite=20)
    json.dumps(r)
    prioridades = [x["prioridad"] for x in r["recomendaciones"]]
    assert prioridades == sorted(prioridades, reverse=True)
    assert r["criterio_prioridad"]
    for x in r["recomendaciones"]:
        assert x["evidencia"], x["recomendacion_id"]
        assert x["impacto"]["valor"] >= 0
        assert 0 <= x["prioridad"] <= 100
        assert x["prompt"]
        h = x["herramienta"]
        assert h["herramienta_id"] in recs.POR_ID
        assert h["tools"] == list(TOOLS_POR_HERRAMIENTA[h["herramienta_id"]])


def test_la_recomendacion_principal_de_ana_lleva_al_perfilador():
    """Es el puente con el guion: el tablero de CLI-0001 abre el perfilador del turno 1."""
    primera = REGISTRO["get_recommendations"]("CLI-0001")["recomendaciones"][0]
    assert primera["recomendacion_id"] == "invertir_efectivo_ocioso"
    assert primera["herramienta"]["herramienta_id"] == "perfilador_inversion"


def test_sin_perfil_vigente_no_se_manda_a_nada_que_lo_exija():
    exigen_perfil = {"propuesta_inversion", "simulador_aportaciones", "comparador_portafolios"}
    for cid in CLIENTES:
        perfil, r = profile.perfil_y_recomendaciones(cid, limite=20)
        if not perfil["inversion"]["perfil_vigente"]:
            usadas = {x["herramienta"]["herramienta_id"] for x in r["recomendaciones"]}
            assert not usadas & exigen_perfil, cid


def test_la_recomendacion_de_tarjeta_cuadra_con_su_plan_de_pago():
    r = REGISTRO["get_recommendations"]("CLI-0003", limite=20)
    rec = next(x for x in r["recomendaciones"]
               if x["herramienta"]["herramienta_id"] == "plan_pago_tarjeta")
    plan = REGISTRO["simulate_debt_payoff"]("CLI-0003", card_id=rec["parametros"]["card_id"],
                                            meses_objetivo=12)
    assert plan["plan"]["pago_mensual"] == pytest.approx(rec["parametros"]["pago_mensual_sugerido"], abs=0.01)
    assert plan["ahorro_intereses"] == pytest.approx(rec["impacto"]["valor"], abs=0.01)
    assert plan["solo_minimo"]["meses"] > plan["plan"]["meses"]


def test_el_plan_de_pago_no_toca_tarjetas_ajenas():
    ajena = next(t for t in REGISTRO["get_accounts"]("CLI-0002")["tarjetas"] if t["tipo"] == "credito")
    with pytest.raises(ServiceError) as exc:
        REGISTRO["simulate_debt_payoff"]("CLI-0003", card_id=ajena["card_id"])
    assert "no pertenece" in str(exc.value)
    assert ajena["last4"] not in str(exc.value)


def test_el_plan_de_pago_pide_pago_o_plazo_no_los_dos():
    with pytest.raises(ServiceError):
        REGISTRO["simulate_debt_payoff"]("CLI-0003", pago_mensual=5_000, meses_objetivo=12)


def test_un_pago_insuficiente_sugiere_uno_que_si_liquida():
    with pytest.raises(ServiceError) as exc:
        REGISTRO["simulate_debt_payoff"]("CLI-0003", pago_mensual=100)
    assert "36 meses" in str(exc.value)


def test_get_recommendations_valida_el_limite():
    with pytest.raises(ServiceError):
        REGISTRO["get_recommendations"]("CLI-0001", limite=0)


# ===========================================================================
# 3. contrato: catalogo de herramientas <-> servicios <-> prompt
# ===========================================================================
def test_herramientas_servicios_y_prompt_dicen_lo_mismo():
    ids = set(recs.POR_ID)
    assert set(TOOLS_POR_HERRAMIENTA) == ids
    assert set(COMPONENTES_POR_HERRAMIENTA) == ids
    for h in recs.HERRAMIENTAS:
        tools = TOOLS_POR_HERRAMIENTA[h.herramienta_id]
        componentes = COMPONENTES_POR_HERRAMIENTA[h.herramienta_id]
        assert f"`{h.herramienta_id}`" in REGLAS, f"{h.herramienta_id} falta en el prompt"
        if h.disponible:
            assert tools and componentes, f"{h.herramienta_id} está disponible pero no tiene con qué"
            assert set(tools) <= set(REGISTRO), f"{h.herramienta_id} usa tools inexistentes"
            assert set(componentes) <= set(COMPONENTES), f"{h.herramienta_id} usa componentes inexistentes"
        else:
            assert not tools and not componentes, f"{h.herramienta_id} no está disponible: sin tools"
