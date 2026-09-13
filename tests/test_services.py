"""Pruebas de la capa de servicios.

Dos cosas se verifican aquí: que los datos que salen sean coherentes con la
base, y que los errores estén escritos para que el modelo pueda corregirse
solo. Lo segundo importa tanto como lo primero: un `ServiceError` sin
sugerencia manda al agente a adivinar.
"""

from __future__ import annotations

import json

import pytest

from bank import db
from services import CON_EFECTO, REGISTRO, ServiceError
from services.errors import NotFound, ReglaDeNegocio

CLIENTES = [f"CLI-{i:04d}" for i in range(1, 9)]


# ------------------------------------------------------------------- snapshot
@pytest.mark.parametrize("client_id", CLIENTES)
def test_el_snapshot_cuadra_con_la_base(client_id):
    s = REGISTRO["get_client_snapshot"](client_id)
    assert s["client_id"] == client_id
    assert s["nombre"]
    assert s["efectivo_total"] == pytest.approx(
        sum(c["saldo_disponible"] for c in s["cuentas"]), abs=0.01)
    assert s["patrimonio_total"] == pytest.approx(
        s["efectivo_total"] + s["inversion"]["valor_mercado"], abs=0.01)
    assert s["inversion"]["rendimiento"] == pytest.approx(
        s["inversion"]["valor_mercado"] - s["inversion"]["costo_total"], abs=0.01)
    for p in s["posiciones"]:
        assert p["valor_mercado"] == pytest.approx(p["costo_total"] + p["rendimiento"], abs=0.01)


def test_cli_0001_no_tiene_perfil_vigente():
    """Es el invariante del guion: sin perfil, el agente monta el perfilador."""
    s = REGISTRO["get_client_snapshot"]("CLI-0001")
    assert s["perfil_vigente"] is False


def test_un_perfil_vencido_no_cuenta_como_vigente():
    s = REGISTRO["get_client_snapshot"]("CLI-0004")
    assert s["perfil_riesgo"] is not None, "CLI-0004 sí tiene perfil, pero viejo"
    assert s["perfil_riesgo"]["vigente"] is False
    assert s["perfil_vigente"] is False


def test_cliente_inexistente_sugiere_los_validos():
    with pytest.raises(NotFound) as exc:
        REGISTRO["get_client_snapshot"]("CLI-9999")
    assert "CLI-0001" in str(exc.value)


# --------------------------------------------------------------------- gasto
def test_el_resumen_de_gasto_no_cuenta_traspasos():
    """Mover dinero a la cuenta de inversión no es gastar."""
    g = REGISTRO["get_spending_summary"]("CLI-0002", meses=6)
    categorias = {c["categoria"] for c in g["por_categoria"]}
    assert "traspaso" not in categorias
    assert "inversion" not in categorias
    assert g["gasto_mensual_promedio"] > 0
    assert g["capacidad_ahorro_mensual"] >= 0
    assert 0 <= g["tasa_ahorro"] <= 1


def test_la_capacidad_de_ahorro_es_ingreso_menos_gasto():
    g = REGISTRO["get_spending_summary"]("CLI-0003", meses=6)
    esperado = max(0.0, g["ingreso_mensual_observado"] - g["gasto_mensual_promedio"])
    assert g["capacidad_ahorro_mensual"] == pytest.approx(esperado, abs=0.01)


def test_los_movimientos_vienen_del_mas_nuevo_al_mas_viejo():
    t = REGISTRO["get_transactions"]("CLI-0002", meses=6, limite=40)
    fechas = [m["fecha"] for m in t["movimientos"]]
    assert fechas == sorted(fechas, reverse=True)
    assert all(m["monto"] >= 0 for m in t["movimientos"])


def test_filtrar_por_categoria():
    t = REGISTRO["get_transactions"]("CLI-0002", meses=12, categoria="renta", limite=50)
    assert t["movimientos"], "debería haber pagos de renta"
    assert {m["categoria"] for m in t["movimientos"]} == {"renta"}


@pytest.mark.parametrize("meses", [0, 19, -3])
def test_rango_de_meses_invalido(meses):
    with pytest.raises(ServiceError) as exc:
        REGISTRO["get_transactions"]("CLI-0001", meses=meses)
    assert "1 y 18" in str(exc.value)


# --------------------------------------------------------------- instrumentos
def test_el_catalogo_completo_sale_ordenado_por_rendimiento_neto():
    from bank.instrumentos import INSTRUMENTOS
    r = REGISTRO["list_instruments"](limite=100)
    assert r["total"] == len(INSTRUMENTOS)
    netos = [i["rend_neto_anual"] for i in r["instrumentos"]]
    assert netos == sorted(netos, reverse=True)
    for i in r["instrumentos"]:
        assert i["rend_neto_anual"] == pytest.approx(
            i["rend_esperado_anual"] - i["comision_anual"])


def test_filtrar_por_riesgo_y_por_monto():
    bajo = REGISTRO["list_instruments"](riesgo_max=2)
    assert bajo["total"] > 0
    assert all(i["riesgo_1a5"] <= 2 for i in bajo["instrumentos"])

    chico = REGISTRO["list_instruments"](monto_disponible=5_000)
    assert all(i["monto_minimo"] <= 5_000 for i in chico["instrumentos"])
    assert chico["total"] < bajo["total"] + 24


@pytest.mark.parametrize("kwargs,pista", [
    ({"clase": "cripto"}, "clase"),
    ({"liquidez": "inmediata"}, "liquidez"),
    ({"ordenar_por": "magia"}, "ordenar_por"),
    ({"riesgo_max": 9}, "1 y 5"),
])
def test_filtros_invalidos_dicen_las_opciones(kwargs, pista):
    with pytest.raises(ServiceError) as exc:
        REGISTRO["list_instruments"](**kwargs)
    assert pista in str(exc.value)


def test_el_factsheet_trae_serie_y_peores_meses():
    f = REGISTRO["get_instrument_factsheet"]("NAFTRAC", meses_historia=60)
    assert f["instrument_id"] == "NAFTRAC"
    assert f["historia"]["meses"] == 60
    assert len(f["historia"]["serie"]) == 60
    fechas = [p["fecha"] for p in f["historia"]["serie"]]
    assert fechas == sorted(fechas), "la serie va de vieja a nueva"
    peores = [p["rend_mensual"] for p in f["historia"]["peores_meses"]]
    assert peores == sorted(peores)
    assert peores[0] < 0


def test_instrumento_inexistente_manda_a_list_instruments():
    with pytest.raises(NotFound) as exc:
        REGISTRO["get_instrument_factsheet"]("BITCOIN")
    assert "list_instruments" in str(exc.value)


# ------------------------------------------------------------------- perfil
def test_guardar_el_perfil_lo_deja_vigente():
    antes = REGISTRO["get_client_snapshot"]("CLI-0007")
    assert antes["perfil_vigente"] is False

    r = REGISTRO["score_risk_profile"](
        [{"id": "horizonte", "value": 4}, {"id": "reaccion_caida", "value": 3},
         {"id": "experiencia", "value": 3}, {"id": "proposito", "value": 3}],
        client_id="CLI-0007")
    assert r["guardado"] is True

    despues = REGISTRO["get_client_snapshot"]("CLI-0007")
    assert despues["perfil_vigente"] is True
    assert despues["perfil_riesgo"]["score"] == r["score"]


def test_calificar_sin_guardar_no_toca_la_base():
    antes = REGISTRO["get_client_snapshot"]("CLI-0001")["perfil_vigente"]
    REGISTRO["score_risk_profile"](
        [{"id": "horizonte", "value": 5}, {"id": "reaccion_caida", "value": 5},
         {"id": "experiencia", "value": 5}, {"id": "proposito", "value": 5}],
        client_id="CLI-0001", guardar=False)
    assert REGISTRO["get_client_snapshot"]("CLI-0001")["perfil_vigente"] is antes


# ------------------------------------------------------- asignación y simulación
def test_la_asignacion_se_acepta_como_objeto_o_como_lista():
    p = REGISTRO["propose_allocation"](perfil="moderado", horizonte_anios=5, monto=100_000)
    como_objeto = REGISTRO["simulate_portfolio"](p["asignacion"], 100_000, 5)
    como_lista = REGISTRO["simulate_portfolio"](
        [{"instrument_id": k, "peso": v} for k, v in p["asignacion"].items()], 100_000, 5)
    assert como_objeto["valor_final"] == como_lista["valor_final"]


def test_instrumento_fuera_del_catalogo_en_la_asignacion():
    with pytest.raises(ServiceError) as exc:
        REGISTRO["simulate_portfolio"]({"DOGECOIN": 1.0}, 1_000, 5)
    assert "DOGECOIN" in str(exc.value)
    assert "list_instruments" in str(exc.value) or "propose_allocation" in str(exc.value)


# -------------------------------------------------------------------- órdenes
def asignacion_simple() -> dict[str, float]:
    return {"FND-GUB-CP": 0.4, "CETES-364": 0.6}


def test_el_flujo_de_dos_pasos():
    cid = "CLI-0006"
    saldo_antes = next(c["saldo_disponible"] for c in
                       REGISTRO["get_accounts"](cid)["cuentas"] if c["tipo"] == "inversion")

    paso1 = REGISTRO["place_order"](client_id=cid, asignacion=asignacion_simple(),
                                    monto=30_000, idempotency_key="t-dos-pasos")
    assert paso1["estado"] == "pendiente"
    assert paso1["requiere_confirmacion"] is True
    assert paso1["confirmation_token"]
    assert sum(l["monto"] for l in paso1["legs"]) == pytest.approx(30_000, abs=1)

    # el saldo NO se movió todavía
    saldo_medio = next(c["saldo_disponible"] for c in
                       REGISTRO["get_accounts"](cid)["cuentas"] if c["tipo"] == "inversion")
    assert saldo_medio == pytest.approx(saldo_antes)

    paso2 = REGISTRO["place_order"](client_id=cid, asignacion=asignacion_simple(),
                                    monto=30_000, idempotency_key="t-dos-pasos",
                                    confirmation_token=paso1["confirmation_token"])
    assert paso2["estado"] == "ejecutada"
    assert paso2["folio"] == paso1["folio"]
    assert paso2["saldo_despues"] == pytest.approx(saldo_antes - 30_000, abs=0.01)


def test_el_reintento_no_compra_dos_veces():
    cid = "CLI-0002"
    p1 = REGISTRO["place_order"](client_id=cid, asignacion=asignacion_simple(),
                                 monto=25_000, idempotency_key="t-idempotente")
    p2 = REGISTRO["place_order"](client_id=cid, asignacion=asignacion_simple(),
                                 monto=25_000, idempotency_key="t-idempotente",
                                 confirmation_token=p1["confirmation_token"])
    saldo = p2["saldo_despues"]

    repetida = REGISTRO["place_order"](client_id=cid, asignacion=asignacion_simple(),
                                       monto=25_000, idempotency_key="t-idempotente",
                                       confirmation_token=p1["confirmation_token"])
    assert repetida["duplicado"] is True
    assert repetida["folio"] == p1["folio"]
    saldo_final = next(c["saldo_disponible"] for c in
                       REGISTRO["get_accounts"](cid)["cuentas"] if c["tipo"] == "inversion")
    assert saldo_final == pytest.approx(saldo, abs=0.01)

    ejecutadas = [o for o in REGISTRO["get_orders"](cid)["ordenes"]
                  if o["idempotency_key"] == "t-idempotente"]
    assert len(ejecutadas) == 1


def test_token_equivocado_no_ejecuta():
    p1 = REGISTRO["place_order"](client_id="CLI-0006", asignacion=asignacion_simple(),
                                 monto=15_000, idempotency_key="t-token-malo")
    with pytest.raises(ReglaDeNegocio) as exc:
        REGISTRO["place_order"](client_id="CLI-0006", asignacion=asignacion_simple(),
                                monto=15_000, idempotency_key="t-token-malo",
                                confirmation_token=p1["confirmation_token"] + "x")
    assert "confirmation_token" in str(exc.value)
    pendientes = REGISTRO["get_orders"]("CLI-0006", estado="pendiente")["ordenes"]
    assert any(o["idempotency_key"] == "t-token-malo" for o in pendientes)


def test_saldo_insuficiente_dice_cuanto_hay():
    with pytest.raises(ReglaDeNegocio) as exc:
        REGISTRO["place_order"](client_id="CLI-0005", asignacion=asignacion_simple(),
                                monto=40_000_000, idempotency_key="t-sin-lana")
    assert "insuficiente" in str(exc.value).lower()


def test_sin_idempotency_key_no_hay_orden():
    with pytest.raises(ServiceError) as exc:
        REGISTRO["place_order"](client_id="CLI-0002", asignacion=asignacion_simple(),
                                monto=5_000, idempotency_key="")
    assert "idempotency_key" in str(exc.value)


def test_los_pesos_de_la_orden_deben_sumar_uno():
    with pytest.raises(ServiceError) as exc:
        REGISTRO["place_order"](client_id="CLI-0002",
                                asignacion={"CETES-364": 0.3, "FND-GUB-CP": 0.3},
                                monto=10_000, idempotency_key="t-pesos")
    assert "suman" in str(exc.value)


def test_el_historial_nunca_expone_el_token():
    REGISTRO["place_order"](client_id="CLI-0008", asignacion=asignacion_simple(),
                            monto=12_000, idempotency_key="t-historial")
    ordenes = REGISTRO["get_orders"]("CLI-0008")["ordenes"]
    assert ordenes
    for o in ordenes:
        assert "confirmation_token" not in o


def test_la_orden_ejecutada_deja_movimiento_y_posiciones():
    cid = "CLI-0008"
    p1 = REGISTRO["place_order"](client_id=cid, asignacion=asignacion_simple(),
                                 monto=11_000, idempotency_key="t-efectos")
    REGISTRO["place_order"](client_id=cid, asignacion=asignacion_simple(),
                            monto=11_000, idempotency_key="t-efectos",
                            confirmation_token=p1["confirmation_token"])

    movimientos = REGISTRO["get_transactions"](cid, meses=1, categoria="inversion")
    assert any(p1["folio"] in m["descripcion"] for m in movimientos["movimientos"])

    posiciones = {p["instrument_id"] for p in
                  REGISTRO["get_client_snapshot"](cid)["posiciones"]}
    assert set(asignacion_simple()) <= posiciones


# ------------------------------------------------------------------- bitácora
def test_la_bitacora_guarda_el_blueprint():
    from services.orders import registrar_superficie

    mensajes = [{"version": "v0.9", "createSurface": {"surfaceId": "s1"}}]
    tools = [{"name": "get_client_snapshot", "ok": True}]
    registrar_superficie("ses-test", 1, "s1", mensajes, tools)

    with db.session(readonly=True) as conn:
        fila = db.query_one(
            conn, "SELECT * FROM surface_log WHERE session_id = ? AND turn = 1", ("ses-test",))
    assert fila is not None
    assert json.loads(fila["messages_json"]) == mensajes
    assert json.loads(fila["tools_json"]) == tools


# --------------------------------------------------------------- contrato general
def test_las_tools_con_efecto_estan_declaradas():
    assert CON_EFECTO == {
        "place_order",
        "block_card", "unblock_card", "set_card_limit", "set_card_alias",
        "set_account_alias", "set_budget",
        "register_service", "save_beneficiary", "create_deposit_reference",
        "pay_service", "transfer_money", "withdraw_cash", "confirm_payment", "cancel_payment",
    }
    assert CON_EFECTO <= set(REGISTRO)


def _argumentos_de_pagos(nombre: str) -> dict:
    """Las tools de pagos necesitan objetos vivos (un servicio con recibo, una
    operación pendiente con su token), así que se arman solo cuando toca."""
    import uuid

    from bank import pagos

    cid = "CLI-0006"
    unico = uuid.uuid4().hex[:8]
    if nombre == "pay_service":
        referencia = pagos.digitos_deterministas(f"serial-{unico}", 10)
        servicio = REGISTRO["register_service"](cid, "TELMEX", referencia)
        return {"client_id": cid, "service_id": servicio["service_id"],
                "idempotency_key": f"t-serial-{unico}"}
    if nombre in ("confirm_payment", "cancel_payment"):
        pendiente = REGISTRO["withdraw_cash"](cid, 100, f"t-serial-{unico}")
        argumentos = {"client_id": cid, "payment_id": pendiente["payment_id"]}
        if nombre == "confirm_payment":
            argumentos["confirmation_token"] = pendiente["confirmation_token"]
        return argumentos
    clabe = pagos.clabe_con_digito("014", "180", pagos.digitos_deterministas(unico, 11))
    return {
        "get_bills": {"client_id": cid},
        "get_billers": {"categoria": "internet", "client_id": cid},
        "get_beneficiaries": {"client_id": cid},
        "get_payment_history": {"client_id": cid, "meses": 2},
        "get_received_money": {"client_id": cid, "meses": 2},
        "get_deposit_options": {"client_id": cid},
        "register_service": {"client_id": cid, "biller_id": "CFE",
                             "referencia": pagos.digitos_deterministas(unico, 12)},
        "save_beneficiary": {"client_id": cid, "alias": "Serial", "titular": "Prueba",
                             "clabe": clabe},
        "create_deposit_reference": {"client_id": cid, "canal_id": "OXXO"},
        "transfer_money": {"client_id": cid, "monto": 100, "idempotency_key": f"t-serial-{unico}",
                           "clabe": clabe, "titular": "Prueba"},
        "withdraw_cash": {"client_id": cid, "monto": 100, "idempotency_key": f"t-serial-{unico}"},
    }[nombre]


@pytest.mark.parametrize("nombre", sorted(REGISTRO))
def test_todo_servicio_devuelve_algo_serializable(nombre):
    """Si un servicio devuelve algo que json no puede escribir, el turno se cae."""
    from services import accounts as accounts_mod
    from services import movements, payments

    if getattr(REGISTRO[nombre], "__module__", "") in (movements.__name__, payments.__name__):
        salida = REGISTRO[nombre](**_argumentos_de_pagos(nombre))
        json.dumps(salida)
        assert isinstance(salida, dict)
        return

    cuentas_0002 = accounts_mod.get_accounts("CLI-0002")
    account_id = cuentas_0002["cuentas"][0]["account_id"]
    card_debito = next(t["card_id"] for t in cuentas_0002["tarjetas"] if t["tipo"] == "debito")
    tarjeta_credito = next(t for t in cuentas_0002["tarjetas"] if t["tipo"] == "credito")
    card_credito = tarjeta_credito["card_id"]
    limite_valido = tarjeta_credito["saldo_utilizado"] + 1_000

    argumentos = {
        "get_client_snapshot": {"client_id": "CLI-0002"},
        "get_accounts": {"client_id": "CLI-0002"},
        "get_transactions": {"client_id": "CLI-0002", "limite": 5},
        "get_spending_summary": {"client_id": "CLI-0002"},
        "get_credit_overview": {"client_id": "CLI-0002"},
        "search_transactions": {"client_id": "CLI-0002", "categoria": "super", "limite": 5},
        "get_budgets": {"client_id": "CLI-0002"},
        "get_spending_alerts": {"client_id": "CLI-0002"},
        "list_instruments": {"limite": 3},
        "get_instrument_factsheet": {"instrument_id": "CETES-28", "meses_historia": 12},
        "get_risk_questions": {},
        "score_risk_profile": {"answers": [
            {"id": "horizonte", "value": 3}, {"id": "reaccion_caida", "value": 3},
            {"id": "experiencia", "value": 3}, {"id": "proposito", "value": 3}],
            "guardar": False},
        "propose_allocation": {"perfil": "moderado", "horizonte_anios": 5, "monto": 50_000},
        "simulate_portfolio": {"asignacion": {"CETES-364": 1.0}, "monto": 10_000,
                               "horizonte_anios": 3},
        "compare_allocations": {"izquierda": {"CETES-364": 1.0}, "derecha": {"NAFTRAC": 1.0},
                                "monto": 10_000, "horizonte_anios": 3},
        "place_order": {"client_id": "CLI-0006", "asignacion": asignacion_simple(),
                        "monto": 5_000, "idempotency_key": f"t-serial-{nombre}"},
        "get_orders": {"client_id": "CLI-0002"},
        "block_card": {"client_id": "CLI-0002", "card_id": card_debito},
        "unblock_card": {"client_id": "CLI-0002", "card_id": card_debito},
        "set_card_limit": {"client_id": "CLI-0002", "card_id": card_credito,
                           "nuevo_limite": limite_valido},
        "set_card_alias": {"client_id": "CLI-0002", "card_id": card_debito, "alias": "Diario"},
        "set_account_alias": {"client_id": "CLI-0002", "account_id": account_id, "alias": None},
        "set_budget": {"client_id": "CLI-0002", "categoria": "super", "monto_mensual": 1500},
        "get_issuer_profile": {"ticker": "WALMEX"},
        "get_funding_sources": {"client_id": "CLI-0002"},
        "check_suitability": {"asignacion": {"CETES-364": 1.0},
                              "perfil": "conservador", "horizonte_anios": 2},
        "get_fund_holdings": {"instrument_id": "NAFTRAC",
                              "asignacion": {"NAFTRAC": 0.5, "CETES-364": 0.5}},
    }[nombre]
    salida = REGISTRO[nombre](**argumentos)
    json.dumps(salida)          # explota si hay algo no serializable
    assert isinstance(salida, dict)
