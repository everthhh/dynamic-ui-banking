"""Pruebas del motor financiero.

No se verifican cifras exactas (cambiarían con cada ajuste del catálogo), sino
las propiedades que tienen que sostenerse siempre. Si una de estas se rompe,
el agente va a decir algo falso en pantalla con cara de certeza.
"""

from __future__ import annotations

import pytest

from bank.finance import compare, montecarlo, risk, rules
from bank.instrumentos import BY_ID

PERFILES = ("conservador", "moderado", "balanceado", "crecimiento", "agresivo")


def respuestas(horizonte=3, caida=3, experiencia=3, proposito=3):
    return [
        {"id": "horizonte", "value": horizonte},
        {"id": "reaccion_caida", "value": caida},
        {"id": "experiencia", "value": experiencia},
        {"id": "proposito", "value": proposito},
    ]


# ------------------------------------------------------------------ perfilamiento
def test_los_extremos_dan_los_extremos():
    assert risk.calificar(respuestas(1, 1, 1, 1))["score"] == 0
    assert risk.calificar(respuestas(5, 5, 5, 5))["score"] == 100


def test_el_horizonte_corto_topa_el_score():
    """Nadie sale agresivo con dinero que necesita el mes que entra."""
    r = risk.calificar(respuestas(horizonte=1, caida=5, experiencia=5, proposito=5))
    assert r["topado"] is True
    assert r["score"] <= risk.TOPE_POR_HORIZONTE[1]
    assert r["perfil"] in ("conservador", "moderado")
    assert r["score_bruto"] > r["score"]


def test_el_score_es_monotono_en_cada_pregunta():
    base = risk.calificar(respuestas(3, 3, 3, 3))["score"]
    for campo in ("horizonte", "caida", "experiencia", "proposito"):
        mas = risk.calificar(respuestas(**{campo: 4}))["score"]
        menos = risk.calificar(respuestas(**{campo: 2}))["score"]
        assert menos <= base <= mas, f"{campo} no es monótona"


def test_el_desglose_explica_el_score():
    r = risk.calificar(respuestas(4, 2, 5, 1))
    assert len(r["desglose"]) == 4
    assert sum(d["aporte"] for d in r["desglose"]) == pytest.approx(r["score_bruto"], abs=1)
    for d in r["desglose"]:
        assert d["respuesta"], "cada fila debe traer la etiqueta que el usuario eligió"


@pytest.mark.parametrize("malas", [
    [],
    [{"id": "horizonte", "value": 3}],                       # faltan tres
    [*respuestas(), {"id": "inventada", "value": 3}],         # pregunta que no existe
    [{"id": "horizonte", "value": 0}, *respuestas()[1:]],     # fuera de rango
    [{"id": "horizonte", "value": "tres"}, *respuestas()[1:]],
])
def test_respuestas_invalidas_se_rechazan_con_mensaje(malas):
    with pytest.raises(risk.RespuestaInvalida) as exc:
        risk.calificar(malas)
    assert len(str(exc.value)) > 10


# ------------------------------------------------------------------ asignación
@pytest.mark.parametrize("perfil", PERFILES)
def test_la_propuesta_suma_uno_y_usa_el_catalogo(perfil):
    p = rules.proponer(perfil, 5, 200_000)
    assert sum(s["peso"] for s in p["slices"]) == pytest.approx(1.0, abs=1e-6)
    assert sum(s["monto"] for s in p["slices"]) == pytest.approx(200_000, rel=1e-4)
    for s in p["slices"]:
        assert s["instrument_id"] in BY_ID


def test_mas_riesgo_en_el_perfil_significa_mas_rendimiento_esperado():
    rend = [rules.proponer(p, 10, 500_000)["rend_esperado_anual"] for p in PERFILES]
    assert rend == sorted(rend), f"el orden de los perfiles no se refleja: {rend}"


def test_el_horizonte_corto_saca_la_renta_variable():
    corta = rules.proponer("agresivo", 0.5, 200_000)
    larga = rules.proponer("agresivo", 15, 200_000)
    rv_corta = sum(s["peso"] for s in corta["slices"] if s["bloque"].startswith("rv_"))
    rv_larga = sum(s["peso"] for s in larga["slices"] if s["bloque"].startswith("rv_"))
    assert rv_corta == 0.0, "a seis meses no debería quedar nada de renta variable"
    assert rv_larga > 0.5
    assert corta["notas"], "un recorte así tiene que venir explicado"


def test_cada_slice_dice_por_que_esta_ahi():
    for s in rules.proponer("balanceado", 5, 100_000)["slices"]:
        assert s["porque"], f"{s['bloque']} sin justificación"
        assert s["etiqueta"]


def test_montos_chicos_respetan_los_minimos():
    p = rules.proponer("agresivo", 10, 3_000)
    for s in p["slices"]:
        assert s["monto"] >= BY_ID[s["instrument_id"]].monto_minimo * 0.999
    assert p["notas"], "si se redistribuyó, se dice"


def test_liquidez_requerida_evita_plazos_forzosos():
    p = rules.proponer("moderado", 4, 300_000, liquidez_requerida=True)
    liquidez = [BY_ID[s["instrument_id"]].liquidez for s in p["slices"]]
    assert liquidez.count("al_vencimiento") <= 1, liquidez


@pytest.mark.parametrize("kwargs,mensaje", [
    ({"perfil": "temerario", "horizonte_anios": 5, "monto": 1000}, "perfil"),
    ({"perfil": "moderado", "horizonte_anios": 5, "monto": -1}, "monto"),
    ({"perfil": "moderado", "horizonte_anios": 0, "monto": 1000}, "horizonte"),
])
def test_entradas_invalidas_en_la_propuesta(kwargs, mensaje):
    with pytest.raises(rules.SinPropuesta) as exc:
        rules.proponer(**kwargs)
    assert mensaje in str(exc.value).lower()


# ------------------------------------------------------------------ Monte Carlo
def asignacion_ejemplo() -> dict[str, float]:
    return rules.asignacion_plana(rules.proponer("balanceado", 5, 100_000))


def test_la_simulacion_es_determinista():
    a = montecarlo.simular(asignacion_ejemplo(), 100_000, 5, 1_000)
    b = montecarlo.simular(asignacion_ejemplo(), 100_000, 5, 1_000)
    assert a["valor_final"] == b["valor_final"]
    assert a["escenarios"]["p50"] == b["escenarios"]["p50"]


def test_los_percentiles_estan_ordenados_en_todo_momento():
    sim = montecarlo.simular(asignacion_ejemplo(), 100_000, 8, 2_000)
    for i, (a, b, c) in enumerate(zip(sim["escenarios"]["p10"],
                                      sim["escenarios"]["p50"],
                                      sim["escenarios"]["p90"])):
        assert a["valor"] <= b["valor"] <= c["valor"], f"se cruzan en el mes {i}"


def test_la_serie_arranca_en_el_monto_inicial():
    sim = montecarlo.simular(asignacion_ejemplo(), 50_000, 3)
    for p in ("p10", "p50", "p90"):
        assert sim["escenarios"][p][0]["valor"] == pytest.approx(50_000)
    assert len(sim["escenarios"]["p50"]) == 3 * 12 + 1


def test_las_aportaciones_suben_el_total_aportado_y_el_valor_final():
    sin_aporte = montecarlo.simular(asignacion_ejemplo(), 80_000, 5, 0)
    con_aporte = montecarlo.simular(asignacion_ejemplo(), 80_000, 5, 2_500)
    assert con_aporte["total_aportado"] == pytest.approx(80_000 + 2_500 * 60)
    assert con_aporte["valor_final"]["p50"] > sin_aporte["valor_final"]["p50"]


def test_la_tir_no_se_deja_engañar_por_las_aportaciones():
    """El truco: (final/aportado)^(1/años)-1 subestima muchísimo con aportaciones."""
    sim = montecarlo.simular(asignacion_ejemplo(), 80_000, 5, 2_500)
    ingenua = (sim["valor_final"]["p50"] / sim["total_aportado"]) ** (1 / 5) - 1
    assert sim["tir_anual_p50"] > ingenua + 0.02
    # y queda en el rango del rendimiento del portafolio, no en cualquier lado
    assert 0.02 < sim["tir_anual_p50"] < 0.20


def test_mas_volatilidad_significa_mas_rango_y_mas_caida():
    quieto = montecarlo.simular({"CETES-364": 1.0}, 100_000, 10)
    movido = montecarlo.simular({"FND-RV-TEC": 1.0}, 100_000, 10)
    rango = lambda s: s["valor_final"]["p90"] - s["valor_final"]["p10"]  # noqa: E731
    assert rango(movido) > rango(quieto) * 5
    assert movido["max_drawdown"] > quieto["max_drawdown"]
    assert movido["volatilidad_anual"] > quieto["volatilidad_anual"]


def test_diversificar_reduce_la_volatilidad():
    """Si la correlación no estuviera haciendo nada, esto sería igual."""
    solo_rv = montecarlo.simular({"NAFTRAC": 1.0}, 100_000, 10)
    mezcla = montecarlo.simular({"NAFTRAC": 0.5, "CETES-364": 0.5}, 100_000, 10)
    assert mezcla["volatilidad_anual"] < solo_rv["volatilidad_anual"]


def test_la_comision_se_cobra():
    """Dos fondos casi idénticos salvo la comisión: el caro rinde menos."""
    barato = montecarlo.simular({"NAFTRAC": 1.0}, 100_000, 20)      # 0.10%
    caro = montecarlo.simular({"FND-RV-MX": 1.0}, 100_000, 20)      # 1.35%
    assert BY_ID["FND-RV-MX"].comision_anual > BY_ID["NAFTRAC"].comision_anual
    assert caro["valor_final"]["p50"] < barato["valor_final"]["p50"] * 1.35


def test_los_pesos_se_normalizan_solos():
    a = montecarlo.simular({"CETES-364": 2, "NAFTRAC": 2}, 100_000, 3)
    b = montecarlo.simular({"CETES-364": 0.5, "NAFTRAC": 0.5}, 100_000, 3)
    assert a["valor_final"] == b["valor_final"]


@pytest.mark.parametrize("args", [
    ({}, 1000, 5),
    ({"NO-EXISTE": 1.0}, 1000, 5),
    ({"CETES-28": -1.0}, 1000, 5),
    ({"CETES-28": 1.0}, 1000, 0),
    ({"CETES-28": 1.0}, 1000, 100),
    ({"CETES-28": 1.0}, 0, 5),
])
def test_simulaciones_invalidas_se_rechazan(args):
    with pytest.raises(montecarlo.SimulacionInvalida):
        montecarlo.simular(*args)


# ------------------------------------------------------------------ comparación
def test_la_comparacion_usa_los_mismos_supuestos():
    izq = rules.asignacion_plana(rules.proponer("agresivo", 5, 80_000))
    der = rules.asignacion_plana(rules.proponer("conservador", 5, 80_000))
    c = compare.comparar(izq, der, 80_000, 5, 2_500)

    assert c["supuestos"]["monto"] == 80_000
    assert len(c["filas"]) == len(compare.METRICAS_DEFAULT)
    assert c["marcador"]["izquierda"] + c["marcador"]["derecha"] <= len(c["filas"])

    por_metrica = {f["metrica"]: f for f in c["filas"]}
    # el agresivo debe ganar en valor esperado y perder en volatilidad
    assert por_metrica["valor_final_p50"]["mejor"] == "izquierda"
    assert por_metrica["volatilidad_anual"]["mejor"] == "derecha"
    assert por_metrica["max_drawdown"]["mejor"] == "derecha"


def test_cada_fila_sabe_como_se_formatea_y_cual_gana():
    c = compare.comparar({"CETES-364": 1.0}, {"NAFTRAC": 1.0}, 50_000, 5)
    # Si se agrega una metrica con un formato que el front no sabe pintar,
    # la celda cae al formato por defecto y el numero se ve mal en silencio.
    for f in c["filas"]:
        assert f["formato"] in compare.FORMATOS_VALIDOS, f["formato"]
        assert f["mejor"] in ("izquierda", "derecha", "empate")
        assert f["etiqueta"]


def test_comparar_algo_contra_si_mismo_empata():
    a = {"CETES-364": 0.5, "NAFTRAC": 0.5}
    c = compare.comparar(a, dict(a), 50_000, 5)
    assert all(f["mejor"] == "empate" for f in c["filas"])
    assert c["marcador"] == {"izquierda": 0, "derecha": 0}


def test_metrica_desconocida_se_rechaza():
    with pytest.raises(compare.ComparacionInvalida) as exc:
        compare.comparar({"CETES-28": 1.0}, {"NAFTRAC": 1.0}, 1_000, 5,
                         metricas=("sharpe_ratio",))
    assert "sharpe_ratio" in str(exc.value)
