"""Pruebas del dominio de pagos: servicios, transferencias, efectivo e historiales.

Igual que en `test_banking.py`, el foco es lo que no debe poder pasar: que el
paso 1 mueva dinero, que un token inventado o ajeno ejecute, que una CLABE mal
tecleada llegue a ser operación, que guardar un contacto sirva para saltarse el
tope, o que alguna tool pueda acreditar dinero que no salió de otra cuenta.

La base de pruebas es una sola por sesión y todas las operaciones caen en la
misma fecha simulada, así que cada prueba usa clientes y montos que no chocan
con los topes diarios de las demás.
"""

from __future__ import annotations

import uuid

import pytest

from bank import pagos
from services import REGISTRO, accounts, movements, payments
from services.errors import NotFound, ReglaDeNegocio, ServiceError


def _llave(prefijo: str) -> str:
    return f"t-{prefijo}-{uuid.uuid4().hex[:8]}"


def _saldo(account_id: str) -> float:
    client_id = next(
        c for c in (f"CLI-{i:04d}" for i in range(1, 9))
        if any(a["account_id"] == account_id for a in accounts.get_accounts(c)["cuentas"]))
    return next(a["saldo_disponible"] for a in accounts.get_accounts(client_id)["cuentas"]
                if a["account_id"] == account_id)


def _cuenta_uso(client_id: str) -> dict:
    return next(c for c in accounts.get_accounts(client_id)["cuentas"] if c["tipo"] != "inversion")


def _cuenta_inversion(client_id: str) -> dict:
    return next(c for c in accounts.get_accounts(client_id)["cuentas"] if c["tipo"] == "inversion")


def _clabe_externa(semilla: str, banco: str = "012") -> str:
    return pagos.clabe_con_digito(banco, "180", pagos.digitos_deterministas(semilla, 11))


# ------------------------------------------------------------- validaciones puras
def test_digito_verificador_de_clabe_con_el_ejemplo_de_banxico():
    assert pagos.digito_verificador_clabe("03218000011835971") == 9


def test_una_clabe_con_un_digito_cambiado_no_pasa():
    buena = _clabe_externa("un-digito")
    mala = buena[:-1] + str((int(buena[-1]) + 1) % 10)
    assert pagos.problema_clabe(buena) is None
    assert "verificador" in pagos.problema_clabe(mala)


def test_banco_que_no_participa_en_spei_no_pasa():
    base = "999180" + "12345678901"
    assert "participante" in pagos.problema_clabe(base + str(pagos.digito_verificador_clabe(base)))


def test_luhn():
    assert pagos.luhn_valido("4111111111111111")
    assert not pagos.luhn_valido("4111111111111112")


@pytest.mark.parametrize("client_id", [f"CLI-{i:04d}" for i in range(1, 9)])
def test_las_clabes_sembradas_tienen_digito_verificador_valido(client_id):
    for cuenta in payments.get_deposit_options(client_id)["cuentas"]:
        assert pagos.problema_clabe(cuenta["clabe"]) is None, cuenta


# ---------------------------------------------------------------------- convenios
def test_el_agua_se_filtra_a_la_ciudad_del_cliente():
    todos = {c["biller_id"] for c in payments.get_billers(categoria="agua")["convenios"]}
    de_monterrey = {c["biller_id"] for c in
                    payments.get_billers(categoria="agua", client_id="CLI-0001")["convenios"]}
    assert {"AYD_MTY", "SACMEX", "SIAPA"} <= todos
    assert de_monterrey == {"AYD_MTY"}


def test_categoria_de_servicio_invalida():
    with pytest.raises(ServiceError) as exc:
        payments.get_billers(categoria="cripto")
    assert "luz" in str(exc.value)


def test_referencia_con_formato_equivocado_dice_el_formato():
    with pytest.raises(ServiceError) as exc:
        movements.register_service("CLI-0004", "CFE", "12345678901")      # 11 dígitos
    assert "12 dígitos" in str(exc.value)


def test_registrar_un_servicio_consulta_su_adeudo_y_es_idempotente():
    referencia = pagos.digitos_deterministas("registro-cfe-0004", 12)
    primero = movements.register_service("CLI-0004", "CFE", referencia, alias="Luz del depa")
    assert primero["ya_existia"] is False
    assert primero["recibo"]["monto"] > 0
    assert primero["referencia_mask"].endswith(referencia[-4:])
    assert referencia not in str(primero), "la referencia completa no sale"

    segundo = movements.register_service("CLI-0004", "CFE", f" {referencia[:6]} {referencia[6:]} ")
    assert segundo["ya_existia"] is True
    assert segundo["service_id"] == primero["service_id"]
    assert segundo["recibo"]["bill_id"] == primero["recibo"]["bill_id"]


def test_convenio_inexistente_manda_a_get_billers():
    with pytest.raises(NotFound) as exc:
        movements.register_service("CLI-0004", "LUZ_Y_FUERZA", "123")
    assert "get_billers" in str(exc.value)


# ------------------------------------------------------------------------ recibos
@pytest.mark.parametrize("client_id", [f"CLI-{i:04d}" for i in range(1, 9)])
def test_cada_cliente_tiene_servicios_con_recibo(client_id):
    recibos = payments.get_bills(client_id)
    assert recibos["recibos_pendientes"] >= 1
    assert recibos["total_por_pagar"] == pytest.approx(
        sum(s["recibo"]["total"] for s in recibos["servicios"] if s["recibo"]), abs=0.01)


def test_el_cfe_del_guion_vence_pronto_y_no_esta_vencido():
    cfe = next(s for s in payments.get_bills("CLI-0001")["servicios"] if s["biller_id"] == "CFE")
    assert cfe["recibo"] is not None
    assert cfe["recibo"]["vencido"] is False
    assert 0 <= cfe["recibo"]["dias_para_vencer"] <= 5


# ------------------------------------------------------------- pagar un servicio
def test_pagar_un_servicio_en_dos_pasos():
    cid = "CLI-0001"
    cfe = next(s for s in payments.get_bills(cid)["servicios"] if s["biller_id"] == "CFE")
    cuenta = _cuenta_uso(cid)
    saldo_antes = cuenta["saldo_disponible"]
    llave = _llave("cfe")

    paso1 = movements.pay_service(cid, cfe["service_id"], llave)
    assert paso1["estado"] == "pendiente"
    assert paso1["requiere_confirmacion"] is True
    assert paso1["confirmation_token"]
    assert paso1["monto"] == cfe["recibo"]["monto"]
    assert _saldo(cuenta["account_id"]) == pytest.approx(saldo_antes), "el paso 1 no mueve dinero"

    paso2 = movements.confirm_payment(cid, paso1["payment_id"], paso1["confirmation_token"])
    assert paso2["estado"] == "ejecutada"
    assert paso2["folio"] == paso1["folio"]
    assert paso2["saldo_despues"] == pytest.approx(saldo_antes - paso1["total"], abs=0.01)
    assert _saldo(cuenta["account_id"]) == pytest.approx(saldo_antes - paso1["total"], abs=0.01)

    despues = next(s for s in payments.get_bills(cid)["servicios"]
                   if s["service_id"] == cfe["service_id"])
    assert despues["recibo"] is None
    assert despues["ultimo_pago"]["folio"] == paso1["folio"]

    # el pago cuenta en el gasto de "servicios", que es contra lo que se mide el presupuesto
    servicios = accounts.search_transactions(cid, categoria="servicios", comercio="CFE", limite=5)
    assert any(paso1["folio"] in m["descripcion"] for m in servicios["movimientos"])

    repetido = movements.confirm_payment(cid, paso1["payment_id"], paso1["confirmation_token"])
    assert repetido["duplicado"] is True
    assert _saldo(cuenta["account_id"]) == pytest.approx(saldo_antes - paso1["total"], abs=0.01)

    with pytest.raises(ReglaDeNegocio) as exc:
        movements.pay_service(cid, cfe["service_id"], _llave("cfe-otra-vez"))
    assert "al corriente" in str(exc.value)


def test_repetir_el_paso_1_con_la_misma_llave_no_crea_otra_operacion():
    cid = "CLI-0007"
    servicio = next(s for s in payments.get_bills(cid)["servicios"] if s["recibo"])
    llave = _llave("idem")
    primero = movements.pay_service(cid, servicio["service_id"], llave)
    segundo = movements.pay_service(cid, servicio["service_id"], llave)
    assert segundo["duplicado"] is True
    assert segundo["payment_id"] == primero["payment_id"]
    assert "confirmation_token" not in segundo, "el token se entrega una sola vez"


def test_la_misma_llave_no_sirve_para_otro_tipo_de_operacion():
    cid = "CLI-0007"
    llave = _llave("tipo")
    movements.withdraw_cash(cid, 500, llave)
    with pytest.raises(ReglaDeNegocio):
        movements.transfer_money(cid, 500, llave, cuenta_destino_id=_cuenta_inversion(cid)["account_id"])


def test_si_el_recibo_ya_se_pago_la_segunda_operacion_se_rechaza_y_queda_registrada():
    cid = "CLI-0008"
    servicio = next(s for s in payments.get_bills(cid)["servicios"] if s["recibo"])
    a = movements.pay_service(cid, servicio["service_id"], _llave("doble-a"))
    b = movements.pay_service(cid, servicio["service_id"], _llave("doble-b"))
    movements.confirm_payment(cid, a["payment_id"], a["confirmation_token"])
    saldo = _saldo(a["account_id"])

    with pytest.raises(ReglaDeNegocio) as exc:
        movements.confirm_payment(cid, b["payment_id"], b["confirmation_token"])
    assert "ya estaba pagado" in str(exc.value)
    assert _saldo(a["account_id"]) == pytest.approx(saldo), "no se cobró dos veces"
    rechazadas = payments.get_payment_history(cid, estado="rechazada")["pagos"]
    assert any(p["payment_id"] == b["payment_id"] for p in rechazadas), \
        "el rechazo tiene que persistir, no perderse en el rollback"


# ------------------------------------------------------------------------ tokens
def test_token_equivocado_no_ejecuta():
    cid = "CLI-0006"
    pendiente = movements.withdraw_cash(cid, 300, _llave("token-malo"))
    with pytest.raises(ReglaDeNegocio) as exc:
        movements.confirm_payment(cid, pendiente["payment_id"], pendiente["confirmation_token"] + "x")
    assert "confirmation_token" in str(exc.value)
    pendientes = payments.get_payment_history(cid, estado="pendiente")["pagos"]
    assert any(p["payment_id"] == pendiente["payment_id"] for p in pendientes)


def test_no_se_puede_confirmar_la_operacion_de_otro_cliente():
    ajena = movements.withdraw_cash("CLI-0006", 200, _llave("ajena"))
    with pytest.raises(NotFound) as exc:
        movements.confirm_payment("CLI-0002", ajena["payment_id"], ajena["confirmation_token"])
    assert "no pertenece" in str(exc.value)
    assert ajena["folio"] not in str(exc.value)


def test_el_historial_nunca_expone_hashes_tokens_ni_codigos():
    cid = "CLI-0006"
    pendiente = movements.withdraw_cash(cid, 400, _llave("secretos"))
    movements.confirm_payment(cid, pendiente["payment_id"], pendiente["confirmation_token"])
    for pago in payments.get_payment_history(cid, meses=18, limite=200)["pagos"]:
        texto = str(pago)
        for clave in ("confirmation_token", "codigo_retiro", "_hash"):
            assert clave not in texto, (clave, pago["folio"])


# ------------------------------------------------------------------ transferencias
def test_clabe_con_digito_verificador_malo_no_crea_operacion():
    buena = _clabe_externa("verificador-malo")
    mala = buena[:-1] + str((int(buena[-1]) + 3) % 10)
    antes = payments.get_payment_history("CLI-0002", estado="pendiente", limite=200)["total"]
    with pytest.raises(ServiceError) as exc:
        movements.transfer_money("CLI-0002", 1_000, _llave("clabe-mala"), clabe=mala, titular="X")
    assert "verificador" in str(exc.value)
    assert payments.get_payment_history("CLI-0002", estado="pendiente", limite=200)["total"] == antes


def test_exactamente_un_destino():
    with pytest.raises(ServiceError):
        movements.transfer_money("CLI-0002", 1_000, _llave("sin-destino"))
    with pytest.raises(ServiceError):
        movements.transfer_money("CLI-0002", 1_000, _llave("dos-destinos"),
                                 clabe=_clabe_externa("dos"), titular="X",
                                 cuenta_destino_id=_cuenta_inversion("CLI-0002")["account_id"])


def test_clabe_nueva_exige_titular():
    with pytest.raises(ServiceError) as exc:
        movements.transfer_money("CLI-0002", 1_000, _llave("sin-titular"),
                                 clabe=_clabe_externa("sin-titular"))
    assert "titular" in str(exc.value)


def test_una_cuenta_nueva_tiene_tope_por_operacion():
    cid = "CLI-0002"
    clabe = _clabe_externa("tope-nuevo")
    with pytest.raises(ReglaDeNegocio) as exc:
        movements.transfer_money(cid, pagos.TOPE_DESTINO_NUEVO + 1, _llave("tope"),
                                 clabe=clabe, titular="Proveedor Nuevo")
    assert "save_beneficiary" in str(exc.value)
    permitido = movements.transfer_money(cid, 5_000, _llave("tope-ok"), clabe=clabe,
                                         titular="Proveedor Nuevo")
    assert permitido["estado"] == "pendiente"
    assert permitido["destino_nuevo"] is True


def test_guardar_el_contacto_no_quita_el_tope_de_inmediato():
    cid = "CLI-0002"
    contacto = movements.save_beneficiary(cid, "Proveedor", "Proveedor Recién Guardado",
                                          clabe=_clabe_externa("recien-guardado"))
    assert contacto["destino_nuevo"] is True
    with pytest.raises(ReglaDeNegocio):
        movements.transfer_money(cid, pagos.TOPE_DESTINO_NUEVO + 1, _llave("recien"),
                                 beneficiary_id=contacto["beneficiary_id"])


def test_a_un_contacto_antiguo_no_le_aplica_el_tope_de_destino_nuevo():
    cid = "CLI-0002"
    antiguo = next(b for b in payments.get_beneficiaries(cid)["beneficiarios"]
                   if not b["mismo_banco"])
    assert antiguo["destino_nuevo"] is False
    pendiente = movements.transfer_money(cid, pagos.TOPE_DESTINO_NUEVO + 5_000, _llave("antiguo"),
                                         beneficiary_id=antiguo["beneficiary_id"], concepto="Renta")
    assert pendiente["estado"] == "pendiente"
    assert pendiente["destino"]["numero_mask"] == antiguo["numero_mask"]


def test_guardar_contacto_valida_y_no_duplica():
    cid = "CLI-0004"
    clabe = _clabe_externa("contacto-dup", banco="638")
    primero = movements.save_beneficiary(cid, "Nu", "Ana Pérez", clabe=clabe)
    segundo = movements.save_beneficiary(cid, "Nu otra vez", "Ana Pérez", clabe=clabe)
    assert segundo["ya_existia"] is True
    assert segundo["beneficiary_id"] == primero["beneficiary_id"]
    assert primero["banco"] == "NU MEXICO"
    with pytest.raises(ServiceError):
        movements.save_beneficiary(cid, "Tarjeta", "Ana Pérez", tarjeta="4111111111111112",
                                   banco_codigo="012")
    with pytest.raises(ReglaDeNegocio):
        movements.save_beneficiary(cid, "Yo", "Mariana Elizondo", clabe=_cuenta_uso(cid)["clabe_mock"])


def test_transferencia_al_mismo_banco_le_llega_al_otro_cliente():
    origen, destino = "CLI-0002", "CLI-0003"
    contacto = next(b for b in payments.get_beneficiaries(origen)["beneficiarios"] if b["mismo_banco"])
    cuenta_destino = _cuenta_uso(destino)
    saldo_destino = cuenta_destino["saldo_disponible"]

    pendiente = movements.transfer_money(origen, 1_234.56, _llave("interna"),
                                         beneficiary_id=contacto["beneficiary_id"],
                                         concepto="Cooperación posada")
    hecha = movements.confirm_payment(origen, pendiente["payment_id"], pendiente["confirmation_token"])
    assert hecha["estado"] == "ejecutada"
    assert hecha["clave_rastreo"]

    assert _saldo(cuenta_destino["account_id"]) == pytest.approx(saldo_destino + 1_234.56, abs=0.01)
    recibido = payments.get_received_money(destino, canal="interna", meses=1)
    llegada = next(m for m in recibido["movimientos"] if m["clave_rastreo"] == hecha["clave_rastreo"])
    assert llegada["remitente"] == "Javier Montemayor"
    assert llegada["concepto"] == "Cooperación posada"


def test_clabe_del_mismo_banco_que_no_existe_se_devuelve_sin_cobrar():
    cid = "CLI-0002"
    fantasma = pagos.clabe_con_digito("072", "180", "99999999999")
    pendiente = movements.transfer_money(cid, 800, _llave("fantasma"), clabe=fantasma,
                                         titular="Nadie")
    saldo = _saldo(pendiente["account_id"])
    with pytest.raises(ReglaDeNegocio) as exc:
        movements.confirm_payment(cid, pendiente["payment_id"], pendiente["confirmation_token"])
    assert "devuelta" in str(exc.value)
    assert _saldo(pendiente["account_id"]) == pytest.approx(saldo)


def test_traspaso_entre_cuentas_propias_no_cambia_ingreso_ni_gasto():
    cid = "CLI-0006"
    antes = accounts.get_spending_summary(cid, meses=1)
    inversion, uso = _cuenta_inversion(cid), _cuenta_uso(cid)

    pendiente = movements.transfer_money(cid, 2_500, _llave("propia"),
                                         account_id=inversion["account_id"],
                                         cuenta_destino_id=uso["account_id"])
    assert pendiente["destino"]["cuenta_propia"] is True
    movements.confirm_payment(cid, pendiente["payment_id"], pendiente["confirmation_token"])

    assert _saldo(inversion["account_id"]) == pytest.approx(inversion["saldo_disponible"] - 2_500, abs=0.01)
    assert _saldo(uso["account_id"]) == pytest.approx(uso["saldo_disponible"] + 2_500, abs=0.01)
    despues = accounts.get_spending_summary(cid, meses=1)
    assert despues["ingreso_mensual_observado"] == antes["ingreso_mensual_observado"]
    assert despues["gasto_mensual_promedio"] == antes["gasto_mensual_promedio"]


def test_de_la_cuenta_de_inversion_no_sale_una_transferencia_a_terceros():
    cid = "CLI-0006"
    with pytest.raises(ReglaDeNegocio) as exc:
        movements.transfer_money(cid, 1_000, _llave("desde-inversion"),
                                 account_id=_cuenta_inversion(cid)["account_id"],
                                 clabe=_clabe_externa("desde-inversion"), titular="X")
    assert "cuenta_destino_id" in str(exc.value)


def test_una_transferencia_ejecutada_no_se_cancela():
    cid = "CLI-0006"
    pendiente = movements.transfer_money(cid, 150, _llave("no-cancelable"),
                                         clabe=_clabe_externa("no-cancelable"), titular="Tienda")
    movements.confirm_payment(cid, pendiente["payment_id"], pendiente["confirmation_token"])
    with pytest.raises(ReglaDeNegocio):
        movements.cancel_payment(cid, pendiente["payment_id"])


def test_cancelar_una_pendiente_no_mueve_dinero():
    cid = "CLI-0006"
    pendiente = movements.transfer_money(cid, 700, _llave("cancelar"),
                                         clabe=_clabe_externa("cancelar"), titular="Tienda")
    saldo = _saldo(pendiente["account_id"])
    cancelada = movements.cancel_payment(cid, pendiente["payment_id"])
    assert cancelada["estado"] == "cancelada"
    assert cancelada["reembolso"] is None
    assert _saldo(pendiente["account_id"]) == pytest.approx(saldo)
    with pytest.raises(ReglaDeNegocio):
        movements.confirm_payment(cid, pendiente["payment_id"], pendiente["confirmation_token"])


# ----------------------------------------------------------------------- efectivo
@pytest.mark.parametrize("monto,pista", [(150, "múltiplo"), (50, "va de"), (9_100, "va de")])
def test_reglas_del_retiro_sin_tarjeta(monto, pista):
    with pytest.raises(ServiceError) as exc:
        movements.withdraw_cash("CLI-0004", monto, _llave("reglas"))
    assert pista in str(exc.value)


def test_retiro_sin_tarjeta_entrega_el_codigo_una_vez_y_se_puede_cancelar():
    cid = "CLI-0004"
    cuenta = _cuenta_uso(cid)
    saldo = cuenta["saldo_disponible"]

    pendiente = movements.withdraw_cash(cid, 1_000, _llave("retiro"))
    assert "codigo_retiro" not in pendiente, "el código no existe antes de confirmar"
    emitido = movements.confirm_payment(cid, pendiente["payment_id"], pendiente["confirmation_token"])
    assert len(emitido["codigo_retiro"]) == 12 and emitido["codigo_retiro"].isdigit()
    assert _saldo(cuenta["account_id"]) == pytest.approx(saldo - 1_000, abs=0.01)

    repetido = movements.confirm_payment(cid, pendiente["payment_id"], pendiente["confirmation_token"])
    assert repetido["duplicado"] is True
    assert "codigo_retiro" not in repetido

    cancelado = movements.cancel_payment(cid, pendiente["payment_id"])
    assert cancelado["reembolso"] == 1_000
    assert _saldo(cuenta["account_id"]) == pytest.approx(saldo, abs=0.01)
    assert payments.get_received_money(cid, canal="reembolso", meses=1)["total"] >= 1


def test_tope_diario_se_revisa_en_el_paso_1_y_otra_vez_al_ejecutar(monkeypatch):
    cid = "CLI-0005"          # nómina; nadie más opera con este cliente en las pruebas
    monkeypatch.setitem(pagos.TOPE_DIARIO_POR_SEGMENTO, "nomina", 1_500)

    a = movements.withdraw_cash(cid, 1_000, _llave("tope-a"))
    b = movements.withdraw_cash(cid, 1_000, _llave("tope-b"))    # todavía no sale nada: pasa
    movements.confirm_payment(cid, a["payment_id"], a["confirmation_token"])

    with pytest.raises(ReglaDeNegocio) as exc:
        movements.withdraw_cash(cid, 1_000, _llave("tope-c"))
    assert "tope diario" in str(exc.value)

    with pytest.raises(ReglaDeNegocio):
        movements.confirm_payment(cid, b["payment_id"], b["confirmation_token"])
    rechazadas = payments.get_payment_history(cid, estado="rechazada")["pagos"]
    assert any(p["payment_id"] == b["payment_id"] for p in rechazadas)


def test_referencia_de_deposito_y_su_liquidacion():
    cid = "CLI-0004"
    with pytest.raises(ServiceError):
        movements.create_deposit_reference(cid, "CAJERO")

    ref = movements.create_deposit_reference(cid, "OXXO")
    assert len(ref["referencia"]) == 16
    assert ref["comision"] > 0
    vigentes = payments.get_deposit_options(cid)["referencias_vigentes"]
    assert any(r["reference_id"] == ref["reference_id"] for r in vigentes)

    saldo = _saldo(ref["account_id"])
    liquidado = movements.liquidar_deposito_en_efectivo(ref["referencia"], 2_000)
    assert liquidado["saldo_despues"] == pytest.approx(saldo + 2_000, abs=0.01)
    with pytest.raises(ReglaDeNegocio):
        movements.liquidar_deposito_en_efectivo(ref["referencia"], 2_000)

    recibido = payments.get_received_money(cid, canal="deposito_efectivo", meses=1)
    assert any(m["txn_id"] == liquidado["txn_id"] for m in recibido["movimientos"])


def test_ninguna_tool_puede_acreditar_dinero():
    """El abono de un depósito lo dispara el corresponsal, no el agente."""
    from agent.tools import NOMBRES_DATOS

    assert movements.liquidar_deposito_en_efectivo not in REGISTRO.values()
    assert not any("liquidar" in nombre for nombre in NOMBRES_DATOS)


# --------------------------------------------------------------------- historiales
def test_historial_de_pagos_trae_lo_sembrado_y_filtra_por_tipo():
    cid = "CLI-0003"
    todo = payments.get_payment_history(cid, meses=18, limite=200)
    assert todo["total"] > 0
    assert {p["tipo"] for p in todo["pagos"]} >= {"servicio"}
    solo_servicios = payments.get_payment_history(cid, tipo="servicio", meses=18, limite=200)
    assert all(p["tipo"] == "servicio" for p in solo_servicios["pagos"])
    fechas = [p["fecha"] for p in todo["pagos"]]
    assert fechas == sorted(fechas, reverse=True)


def test_dinero_recibido_distingue_dinero_nuevo_de_traspasos():
    cid = "CLI-0002"
    recibido = payments.get_received_money(cid, meses=18, limite=200)
    canales = {c["canal"]: c["total"] for c in recibido["por_canal"]}
    assert "nomina" in canales
    esperado = sum(t for c, t in canales.items() if c not in ("traspaso_propio", "reembolso"))
    assert recibido["total_recibido"] == pytest.approx(esperado, abs=0.05)


def test_filtros_invalidos_dicen_las_opciones():
    with pytest.raises(ServiceError) as exc:
        payments.get_payment_history("CLI-0001", tipo="bitcoin")
    assert "transferencia" in str(exc.value)
    with pytest.raises(ServiceError) as exc:
        payments.get_received_money("CLI-0001", canal="paypal")
    assert "spei" in str(exc.value)
