"""Riesgo de emisora, look-through, idoneidad, origen, impuestos y plazo.

Es un producto de FONDOS: el cliente no compra acciones. Las 15 emisoras de
la BMV entran por debajo, como tenencias de los fondos, y de ahi sale el
riesgo de lo que si se puede contratar.

Son pruebas de propiedad, no de valores esperados: no comprueban que WALMEX
saque 17.05 de score --eso cambia en cuanto alguien actualice un
fundamental-- sino que el modelo se comporte como debe. Si manana Televisa
mejora su calificacion y baja su apalancamiento, su score TIENE que bajar, y
eso es lo que se prueba aqui.
"""

from __future__ import annotations

import pytest

from bank import carteras, emisoras
from bank.finance import fiscal, idoneidad, montecarlo, rules
from bank.finance import origen as origen_mod
from bank.instrumentos import BY_ID, correlacion_instrumentos
from services import REGISTRO
from services.errors import ReglaDeNegocio, ServiceError


# ===========================================================================
# 1. El riesgo de la empresa se DERIVA de sus fundamentales
# ===========================================================================
def test_el_riesgo_no_esta_escrito_a_mano_sino_calculado():
    """Empeorar un fundamental tiene que empeorar el score. Si no, es un literal."""
    base = emisoras.POR_TICKER["WALMEX"]
    peor = base._replace(calificacion="mxBBB", deuda_neta_ebitda=4.0,
                         cobertura_intereses=2.5)
    assert emisoras.perfil_riesgo(peor)["score"] > emisoras.perfil_riesgo(base)["score"]


@pytest.mark.parametrize("campo,valor", [
    ("volatilidad_anual", 0.44),
    ("calificacion", "mxBBB-"),
    ("importe_operado_diario", 55),
    ("deuda_neta_ebitda", 4.2),
    ("float_pct", 0.08),
])
def test_cada_factor_mueve_el_score_en_la_direccion_correcta(campo, valor):
    base = emisoras.POR_TICKER["FEMSAUBD"]
    peor = base._replace(**{campo: valor})
    assert emisoras.perfil_riesgo(peor)["score"] > emisoras.perfil_riesgo(base)["score"], (
        f"empeorar {campo} no subio el riesgo")


def test_mas_beta_con_la_misma_volatilidad_no_es_peor():
    """Beta NO es "riesgo" a secas, y el modelo tiene que reflejarlo.

    Con la misma volatilidad total, mas beta significa que una porcion mayor
    del movimiento es del mercado y una menor es propia de la empresa. El
    riesgo de mercado se paga (mas rendimiento esperado) y se diluye en un
    portafolio; el propio no hace ninguna de las dos. Por eso el score baja
    un poco mientras el rendimiento esperado sube.
    """
    base = emisoras.POR_TICKER["FEMSAUBD"]
    mas_beta = base._replace(beta=1.30)
    assert emisoras.r_cuadrada(mas_beta) > emisoras.r_cuadrada(base)
    assert emisoras.rendimiento_esperado(mas_beta) > emisoras.rendimiento_esperado(base)
    assert (emisoras.perfil_riesgo(mas_beta)["score"]
            <= emisoras.perfil_riesgo(base)["score"])


def test_el_catalogo_de_emisoras_es_internamente_consistente():
    """La volatilidad sistematica no puede exceder a la total.

    beta*sigma_mercado <= sigma es una identidad, no una preferencia: si se
    rompe, R^2 sale mayor que 1 y el modelo tendria que recortarlo en
    silencio, dando por "sin riesgo propio" a una emisora mal capturada.
    """
    problemas = emisoras.validar_catalogo()
    assert not problemas, problemas


def test_el_desglose_explica_el_score():
    for e in emisoras.EMISORAS:
        perfil = emisoras.perfil_riesgo(e)
        suma = sum(f["aporte"] for f in perfil["desglose"])
        assert suma == pytest.approx(perfil["score"], abs=0.05)
        assert len(perfil["desglose"]) == len(emisoras.PESOS_RIESGO)
        for f in perfil["desglose"]:
            assert f["etiqueta"], "cada factor tiene que poder mostrarse"
            assert 0 <= f["valor"] <= 100


def test_ninguna_emisora_es_contratable():
    """Es un producto de fondos: no se venden acciones sueltas."""
    for ticker in emisoras.POR_TICKER:
        assert ticker not in BY_ID, (
            f"{ticker} aparece como instrumento contratable")
    assert not any(i.clase == "accion" for i in BY_ID.values())


def test_una_emisora_suelta_nunca_seria_riesgo_bajo():
    """El piso existe aunque hoy no se puedan contratar: si alguna vez se
    abriera la venta directa, una sola empresa no es riesgo 1 ni 2."""
    for e in emisoras.EMISORAS:
        assert emisoras.perfil_riesgo(e)["riesgo_1a5"] >= emisoras.RIESGO_MINIMO_ACCION


def test_el_rendimiento_esperado_sigue_a_la_beta_y_no_a_la_volatilidad():
    """CAPM: el mercado paga por beta, no por riesgo propio. Es el argumento
    tecnico contra concentrarse en una emisora volatil."""
    televisa = emisoras.POR_TICKER["TLEVISACPO"]      # volatilidad 42%
    gmexico = emisoras.POR_TICKER["GMEXICOB"]         # volatilidad 31.5%
    assert televisa.volatilidad_anual > gmexico.volatilidad_anual
    assert televisa.beta < gmexico.beta
    assert emisoras.rendimiento_esperado(televisa) < emisoras.rendimiento_esperado(gmexico)


def test_el_riesgo_propio_es_lo_que_no_explica_el_mercado():
    for e in emisoras.EMISORAS:
        perfil = emisoras.perfil_riesgo(e)
        assert 0 < perfil["r_cuadrada"] < 1
        assert perfil["riesgo_propio_pct"] == pytest.approx(
            (1 - perfil["r_cuadrada"]) * 100, abs=0.01)


# ===========================================================================
# 2. Correlacion entre empresas
# ===========================================================================
def test_dos_emisoras_del_mismo_sector_se_parecen_mas():
    e = emisoras.POR_TICKER
    mismo = emisoras.correlacion_emisoras(e["ASURB"], e["GAPB"])       # aeropuertos
    distinto = emisoras.correlacion_emisoras(e["ASURB"], e["WALMEX"])
    assert mismo > distinto


def test_la_correlacion_entre_emisoras_es_simetrica_y_esta_acotada():
    for a in emisoras.EMISORAS:
        assert emisoras.correlacion_emisoras(a, a) == 1.0
        for b in emisoras.EMISORAS:
            rho = emisoras.correlacion_emisoras(a, b)
            assert -1.0 <= rho <= 1.0
            assert rho == pytest.approx(
                emisoras.correlacion_emisoras(b, a), abs=1e-9)


def test_la_correlacion_entre_fondos_sale_de_sus_tenencias():
    """Dos fondos de renta variable mexicana se parecen, pero no son iguales."""
    rho = correlacion_instrumentos("NAFTRAC", "FND-RV-MX")
    assert 0.85 < rho < 0.99
    assert correlacion_instrumentos("NAFTRAC", "CETES-28") < 0.2


# ===========================================================================
# 3. Idoneidad: el riesgo de la empresa contra el riesgo del cliente
# ===========================================================================
def test_un_conservador_no_recibe_renta_variable():
    r = idoneidad.evaluar({"NAFTRAC": 0.2, "CETES-364": 0.8}, "conservador", 5)
    assert not r["apto"]
    assert any(h["codigo"] in ("instrumento_sobre_perfil", "rv_excedida")
               for h in r["bloqueantes"])


def test_el_tope_de_concentracion_mira_DENTRO_de_los_fondos():
    """El cliente no compro ninguna empresa, pero quedo concentrado igual.

    90% en un fondo activo cuya mayor posicion es 22% deja al cliente con
    casi 20% de su patrimonio en un solo banco. Sin look-through esto se ve
    como "un fondo diversificado" y pasa sin que nadie lo note.
    """
    r = idoneidad.evaluar({"FND-RV-MX": 0.9, "CETES-364": 0.1}, "agresivo", 10)
    assert not r["apto"]
    bloq = [h for h in r["bloqueantes"] if h["codigo"] == "concentracion_emisora"]
    assert bloq, [h["codigo"] for h in r["bloqueantes"]]
    assert bloq[0]["ticker"] in emisoras.POR_TICKER
    assert bloq[0]["observado"] > idoneidad.TOPE_LOOKTHROUGH_EMISORA["agresivo"]


def test_el_indice_concentra_menos_que_el_fondo_activo():
    """Con el mismo peso, el fondo indexado deja menos expuesto a una empresa."""
    indexado = idoneidad.exposicion({"NAFTRAC": 0.6, "CETES-364": 0.4})
    activo = idoneidad.exposicion({"FND-RV-MX": 0.6, "CETES-364": 0.4})
    assert max(activo["por_emisora"].values()) > max(indexado["por_emisora"].values())


def test_la_cobertura_del_desglose_se_reporta():
    """No se puede mirar dentro de un fondo internacional; hay que decirlo."""
    exp = idoneidad.exposicion({"NAFTRAC": 0.3, "TRACK-SP500": 0.3, "CETES-364": 0.4})
    assert exp["cobertura_desglose"] == pytest.approx(0.3, abs=0.01)


@pytest.mark.parametrize("perfil", list(rules.POLITICA))
def test_la_propuesta_del_banco_pasa_su_propio_control(perfil):
    """El motor de reglas no puede producir algo que el control rechace.

    Este test existe por un bug real: `_elegir_instrumento` tomaba el
    instrumento mejor pagado del bloque sin mirar el perfil, y un conservador
    terminaba con un Bono M a 10 anios.
    """
    for monto in (8_000, 80_000, 2_000_000):
        p = rules.proponer(perfil, 10, monto)
        assert p["idoneidad"]["apto"], (
            f"{perfil} con ${monto}: {[b['mensaje'] for b in p['idoneidad']['bloqueantes']]}")


@pytest.mark.parametrize("perfil", list(rules.POLITICA))
def test_la_propuesta_solo_contiene_fondos(perfil):
    p = rules.proponer(perfil, 10, 500_000)
    for s in p["slices"]:
        assert s["instrument_id"] in BY_ID
        assert s["instrument_id"] not in emisoras.POR_TICKER


def test_el_fondo_propuesto_dice_que_empresas_trae():
    p = rules.proponer("agresivo", 10, 500_000)
    con_desglose = [s for s in p["slices"] if "principales_emisoras" in s]
    assert con_desglose, "la propuesta debería incluir algún fondo con desglose"
    for s in con_desglose:
        assert s["riesgo_derivado_de_tenencias"] is True
        for e in s["principales_emisoras"]:
            assert e["ticker"] in emisoras.POR_TICKER
            assert 0 < e["peso_efectivo"] <= s["peso"]
            assert e["calificacion"]


def test_la_propuesta_respeta_la_concentracion_look_through():
    """Las propuestas del banco nunca dejan al cliente sobreexpuesto a una empresa."""
    for perfil in rules.POLITICA:
        p = rules.proponer(perfil, 10, 500_000)
        exp = p["idoneidad"]["exposicion"]["por_emisora"]
        tope = idoneidad.TOPE_LOOKTHROUGH_EMISORA[perfil]
        for ticker, w in exp.items():
            assert w <= tope + idoneidad.TOLERANCIA, f"{perfil}: {ticker} en {w:.1%}"


# ===========================================================================
# 4. La asignacion se valida contra el perfil GUARDADO del cliente
# ===========================================================================
def test_propose_allocation_ignora_el_perfil_que_mande_el_modelo():
    """CLI-0005 tiene score 18 (conservador). Pedir 'agresivo' no debe colar."""
    p = REGISTRO["propose_allocation"](client_id="CLI-0005", perfil="agresivo",
                                       monto=100_000, horizonte_anios=5)
    assert p["perfil"] == "conservador"
    assert p.get("perfil_solicitado_ignorado") is True
    assert any("vigente" in n for n in p["notas"])


def test_no_se_propone_nada_sin_perfil_vigente():
    with pytest.raises(ServiceError) as exc:
        REGISTRO["propose_allocation"](client_id="CLI-0001", monto=80_000)
    assert "perfil" in str(exc.value).lower()


def test_place_order_rechaza_lo_que_no_le_corresponde_al_cliente():
    """CLI-0005 es conservador; un fondo sectorial de tecnologia no pasa."""
    with pytest.raises(ReglaDeNegocio) as exc:
        REGISTRO["place_order"](client_id="CLI-0005",
                                asignacion={"FND-RV-TEC": 1.0},
                                monto=20_000,
                                idempotency_key="t-idoneidad-rechazo")
    assert "conservador" in str(exc.value).lower()


def test_place_order_rechaza_a_quien_no_tiene_perfil():
    with pytest.raises(ReglaDeNegocio) as exc:
        REGISTRO["place_order"](client_id="CLI-0001",
                                asignacion={"CETES-364": 1.0},
                                monto=20_000,
                                idempotency_key="t-sin-perfil")
    assert "perfil" in str(exc.value).lower()


def test_place_order_rechaza_con_perfil_vencido():
    """CLI-0004 tiene perfil pero fuera de vigencia."""
    with pytest.raises(ReglaDeNegocio) as exc:
        REGISTRO["place_order"](client_id="CLI-0004",
                                asignacion={"CETES-364": 1.0},
                                monto=20_000,
                                idempotency_key="t-perfil-vencido")
    assert "venc" in str(exc.value).lower()


def test_check_suitability_es_el_mismo_control_que_place_order():
    asignacion = {"FND-RV-TEC": 1.0}
    veredicto = REGISTRO["check_suitability"](asignacion=asignacion,
                                              client_id="CLI-0005", monto=20_000)
    assert not veredicto["apto"]
    with pytest.raises(ReglaDeNegocio):
        REGISTRO["place_order"](client_id="CLI-0005", asignacion=asignacion,
                                monto=20_000, idempotency_key="t-mismo-control")


def test_una_asignacion_apta_si_se_registra():
    r = REGISTRO["place_order"](client_id="CLI-0005",
                                asignacion={"CETES-364": 0.6, "FND-GUB-CP": 0.4},
                                monto=15_000,
                                idempotency_key="t-idoneidad-ok")
    assert r["estado"] == "pendiente"
    assert r["idoneidad"]["apto"] is True


# ===========================================================================
# 5. El origen del dinero cambia la formula
# ===========================================================================
def test_con_tarjeta_de_credito_se_pierde_siempre():
    """42% de costo contra un portafolio que espera 12%: no hay escenario bueno."""
    sim = montecarlo.simular({"NAFTRAC": 1.0}, 200_000, 5, origen="tarjeta_credito")
    assert sim["prob_perdida_vs_origen"] == 1.0
    assert sim["financiamiento"]["deuda_final"] > 200_000 * 5


def test_el_mismo_portafolio_pierde_distinto_segun_de_donde_salga_el_dinero():
    kwargs = dict(asignacion={"NAFTRAC": 1.0}, monto=200_000, horizonte_anios=5)
    propio = montecarlo.simular(**{**kwargs, "origen": "cheques"})
    ahorro = montecarlo.simular(**{**kwargs, "origen": "ahorro"})
    hipoteca = montecarlo.simular(**{**kwargs, "origen": "credito_hipotecario"})
    tarjeta = montecarlo.simular(**{**kwargs, "origen": "tarjeta_credito"})
    # Mas caro el dinero, mas alta la barra para "no perder".
    assert (propio["prob_perdida_vs_origen"] <= ahorro["prob_perdida_vs_origen"]
            <= hipoteca["prob_perdida_vs_origen"] <= tarjeta["prob_perdida_vs_origen"])


def test_con_deuda_el_perfil_baja_a_conservador():
    efectivo = idoneidad.perfil_efectivo("agresivo", "credito_personal")
    assert efectivo["perfil"] == "conservador"
    assert efectivo["topado_por_origen"] is True
    # Con dinero propio no se toca.
    assert idoneidad.perfil_efectivo("agresivo", "ahorro")["perfil"] == "agresivo"


def test_invertir_con_credito_se_bloquea_por_valor_esperado_negativo():
    r = idoneidad.evaluar({"CETES-364": 1.0}, "conservador", 5, origen="tarjeta_credito")
    assert not r["apto"]
    motivo = next(h for h in r["bloqueantes"] if h["codigo"] == "credito_no_rentable")
    assert motivo["diferencia"] < 0


def test_el_origen_sale_de_la_cuenta_si_no_se_especifica():
    assert origen_mod.desde_cuenta("nomina").clave == "nomina"
    assert origen_mod.desde_cuenta("inversion").apalancado is False
    assert origen_mod.desde_credito("personal", 0.31).costo_anual == 0.31


def test_get_funding_sources_trae_los_origenes_reales_del_cliente():
    r = REGISTRO["get_funding_sources"](client_id="CLI-0002")
    claves = {o["origen"] for o in r["origenes_del_cliente"]}
    assert claves, "el cliente debe tener al menos una cuenta"
    for o in r["origenes_del_cliente"]:
        if o["apalancado"]:
            assert o["costo_anual"] > 0
            assert o["tope_perfil"] == "conservador"


# ===========================================================================
# 6. Impuestos
# ===========================================================================
def test_los_impuestos_bajan_el_resultado():
    con = montecarlo.simular({"CETES-364": 1.0}, 200_000, 5)
    sin = montecarlo.simular({"CETES-364": 1.0}, 200_000, 5, con_impuestos=False)
    assert con["valor_final"]["p50"] < sin["valor_final"]["p50"]
    assert con["tir_anual_p50"] < sin["tir_anual_p50"]
    assert con["impuestos"]["total_p50"] > 0
    assert sin["impuestos"]["total_p50"] == 0


def test_la_retencion_de_intereses_se_cobra_sobre_el_capital():
    """Por eso duele mas en instrumentos de tasa baja que en los de tasa alta."""
    assert fiscal.regimen_de("PAGARE-28") == "interes"
    assert fiscal.regimen_de("NAFTRAC") == "capital"
    assert fiscal.regimen_de("FND-RV-MX") == "capital"
    sim = montecarlo.simular({"PAGARE-28": 1.0}, 200_000, 5)
    assert sim["impuestos"]["retencion_intereses_p50"] > 0
    # Un pagare no genera ganancia de capital.
    assert sim["impuestos"]["isr_ganancia_capital_p50"] == 0


def test_los_fondos_de_renta_variable_pagan_isr_de_ganancia_y_de_dividendos():
    sim = montecarlo.simular({"NAFTRAC": 1.0}, 200_000, 10)
    assert sim["impuestos"]["isr_ganancia_capital_p50"] > 0
    # El dividendo del fondo sale de las empresas que trae, no de un literal.
    assert fiscal.arrastre_dividendos("NAFTRAC") > 0
    assert fiscal.arrastre_dividendos("NAFTRAC") == pytest.approx(
        carteras.dividend_yield("NAFTRAC") * 0.10, abs=1e-9)
    assert fiscal.arrastre_dividendos("CETES-28") == 0.0


def test_el_desglose_fiscal_reparte_el_portafolio_entre_los_dos_regimenes():
    d = fiscal.desglose({"CETES-364": 0.5, "NAFTRAC": 0.5})
    assert d["peso_interes"] == pytest.approx(0.5)
    assert d["peso_capital"] == pytest.approx(0.5)


# ===========================================================================
# 7. Plazo, reinversion y duracion
# ===========================================================================
def test_un_cetes_28_se_renueva_a_la_tasa_vigente_y_uno_largo_no():
    from bank.instrumentos import duracion_anios, sensibilidad_reinversion
    assert sensibilidad_reinversion("CETES-28") == 1.0
    assert sensibilidad_reinversion("BONOSM-10A") < 0.2
    # Al reves con la duracion: el corto no se mueve de precio, el largo si.
    assert duracion_anios("CETES-28") < 0.2
    assert duracion_anios("BONOSM-10A") > 5
    assert duracion_anios("NAFTRAC") == 0.0


def test_la_tasa_no_se_queda_congelada_diez_anios():
    """Sin esto, un CETES-28 se simula como un deposito a plazo de 10 anios."""
    sim = montecarlo.simular({"CETES-28": 1.0}, 100_000, 10)
    inicial = sim["supuestos"]["tasa_inicial"]
    final = sim["supuestos"]["tasa_final_p50"]
    assert final != inicial
    # Revierte hacia el nivel largo, no se va a cualquier lado.
    assert min(inicial, sim["supuestos"]["tasa_larga"]) <= final <= max(
        inicial, sim["supuestos"]["tasa_larga"]) + 0.01


def test_la_duracion_hace_que_el_bono_largo_caiga_de_verdad():
    corto = montecarlo.simular({"CETES-28": 1.0}, 100_000, 5)
    largo = montecarlo.simular({"BONOSM-10A": 1.0}, 100_000, 5)
    assert largo["max_drawdown"] > corto["max_drawdown"] * 10
    assert largo["prob_perdida_nominal"] > corto["prob_perdida_nominal"]


def test_no_se_recomienda_un_plazo_que_no_cabe_en_el_horizonte():
    r = idoneidad.evaluar({"PAGARE-360": 1.0}, "conservador", 0.5)
    assert not r["apto"]
    assert any(h["codigo"] == "plazo_supera_horizonte" for h in r["bloqueantes"])


# ===========================================================================
# 8. Tasa de perdida y porcentaje de riesgo
# ===========================================================================
def test_perder_contra_la_inflacion_es_mas_probable_que_perder_nominal():
    sim = montecarlo.simular({"PAGARE-28": 1.0}, 200_000, 5)
    assert sim["prob_perdida_real"] > sim["prob_perdida_nominal"]


def test_la_probabilidad_de_perder_viene_con_cuanto_se_pierde():
    """Una probabilidad sola no dice nada: no es igual perder 2% que 40%."""
    sim = montecarlo.simular({"FND-RV-TEC": 1.0}, 200_000, 5)
    p = sim["perdida"]["nominal"]
    assert 0 < p["prob"] < 1
    assert p["perdida_media_si_pierde"] > 0
    assert p["cvar_95"] >= p["var_95"]
    assert p["perdida_esperada_pct"] == pytest.approx(
        p["prob"] * p["perdida_media_si_pierde_pct"], abs=1e-3)


def test_el_indice_de_riesgo_ordena_los_portafolios():
    def riesgo(asig):
        return montecarlo.simular(asig, 200_000, 5)["indice_riesgo"]["score"]

    cetes = riesgo({"CETES-28": 1.0})
    mezcla = riesgo({"CETES-364": 0.6, "NAFTRAC": 0.4})
    indice = riesgo({"NAFTRAC": 1.0})
    sectorial = riesgo({"FND-RV-TEC": 1.0})
    assert cetes < mezcla < indice < sectorial
    assert 0 <= cetes and sectorial <= 100


def test_el_indice_de_riesgo_trae_su_desglose():
    sim = montecarlo.simular({"NAFTRAC": 1.0}, 200_000, 5)
    ind = sim["indice_riesgo"]
    assert ind["banda"] in ("muy bajo", "bajo", "medio", "alto", "muy alto")
    assert sum(f["aporte"] for f in ind["desglose"]) == pytest.approx(
        ind["score"], abs=0.05)


def test_el_indice_no_dice_muy_bajo_si_se_pierde_contra_la_deuda():
    """CETES con tarjeta al 42%: volatilidad casi cero, pero pierde contra la
    deuda en todas las trayectorias. Antes el indice decia "muy bajo"."""
    sim = montecarlo.simular({"CETES-28": 1.0}, 100_000, 1, origen="tarjeta_credito")
    ind = sim["indice_riesgo"]
    assert sim["prob_perdida_vs_origen"] > 0.9
    assert ind["referencia_perdida"] == "vs_origen"
    assert ind["banda"] == "muy alto"
    assert sum(f["aporte"] for f in ind["desglose"]) == pytest.approx(
        ind["score"], abs=0.05)


def test_con_dinero_propio_el_indice_usa_la_peor_entre_nominal_y_real():
    sim = montecarlo.simular({"CETES-28": 0.6, "NAFTRAC": 0.4}, 100_000, 1)
    ind = sim["indice_riesgo"]
    assert ind["prob_perdida"] == pytest.approx(
        max(sim["prob_perdida_nominal"], sim["prob_perdida_real"]))


@pytest.mark.parametrize("asignacion,horizonte,origen", [
    ({"CETES-28": 1.0}, 1, "tarjeta_credito"),
    ({"PAGARE-360": 1.0}, 5, "credito_personal"),
    ({"CETES-28": 0.6, "NAFTRAC": 0.4}, 1, None),
    ({"BONOSM-10A": 1.0}, 5, None),
    ({"NAFTRAC": 1.0}, 1, None),
    ({"FND-RV-TEC": 1.0}, 1, None),
])
def test_la_banda_no_contradice_la_probabilidad_de_perder(asignacion, horizonte, origen):
    """Con 25% o mas de probabilidad de perder, la banda no puede ser baja."""
    ind = montecarlo.simular(asignacion, 100_000, horizonte, origen=origen)["indice_riesgo"]
    if ind["prob_perdida"] >= 0.25:
        assert ind["banda"] not in ("muy bajo", "bajo")
    if ind["prob_perdida"] >= 0.50:
        assert ind["banda"] in ("alto", "muy alto")


def test_la_simulacion_sigue_siendo_determinista_con_todo_lo_nuevo():
    kwargs = dict(asignacion={"NAFTRAC": 0.3, "CETES-364": 0.7}, monto=150_000,
                  horizonte_anios=7, aportacion_mensual=1_500, origen="ahorro")
    a = montecarlo.simular(**kwargs)
    b = montecarlo.simular(**kwargs)
    assert a["valor_final"] == b["valor_final"]
    assert a["perdida"] == b["perdida"]
    assert a["impuestos"]["total_p50"] == b["impuestos"]["total_p50"]


# ===========================================================================
# 9. Procedencia de los datos de mercado
# ===========================================================================
def test_cada_parametro_de_mercado_dice_de_donde_salio():
    from bank import mercado
    for fila in mercado.ficha()["parametros"]:
        assert fila["tipo"] in ("anclado", "estimado")
        assert fila["fuente"] and fila["tomado_en"]


def test_los_precios_anclados_estan_marcados_como_tales():
    anclados = [e for e in emisoras.EMISORAS if e.fuente == "anclado"]
    assert anclados, "debe haber al menos algunos precios consultados"
    for e in emisoras.EMISORAS:
        assert e.fuente in ("anclado", "estimado")
        ficha = emisoras.ficha(e.ticker)
        assert ficha["fecha_precio"]
        assert "vivo" in ficha["disclaimer"] or "no es" in ficha["disclaimer"].lower()
