"""Pruebas de banca personal: búsqueda, presupuestos y mutaciones de tarjeta/cuenta.

El foco aquí es seguridad y reglas de negocio, no solo el camino feliz: que
una tarjeta ajena nunca se pueda tocar, que los límites tengan techo y piso,
y que las mutaciones sean idempotentes donde deben serlo.
"""

from __future__ import annotations

import pytest

from services import accounts, banking
from services.errors import ServiceError

CLIENTE = "CLI-0001"
OTRO_CLIENTE = "CLI-0002"


def _tarjetas(client_id: str = CLIENTE) -> list[dict]:
    return accounts.get_accounts(client_id)["tarjetas"]


def _tarjeta_credito(client_id: str = CLIENTE) -> dict:
    return next(t for t in _tarjetas(client_id) if t["tipo"] == "credito")


def _tarjeta_debito(client_id: str = CLIENTE) -> dict:
    return next(t for t in _tarjetas(client_id) if t["tipo"] == "debito")


def _cuenta(client_id: str = CLIENTE) -> dict:
    return accounts.get_accounts(client_id)["cuentas"][0]


# --------------------------------------------------------------- ownership
def test_no_se_puede_bloquear_tarjeta_ajena():
    tarjeta_de_otro = _tarjeta_debito(OTRO_CLIENTE)
    with pytest.raises(ServiceError) as exc:
        banking.block_card(CLIENTE, tarjeta_de_otro["card_id"])
    assert "no pertenece" in str(exc.value)


def test_no_se_puede_poner_alias_a_cuenta_ajena():
    cuenta_de_otro = _cuenta(OTRO_CLIENTE)
    with pytest.raises(ServiceError):
        banking.set_account_alias(CLIENTE, cuenta_de_otro["account_id"], "robada")


def test_error_de_ownership_no_revela_datos_de_la_tarjeta_ajena():
    """El mensaje dice 'no existe o no pertenece', nunca el tipo/alias/last4 real."""
    tarjeta_de_otro = _tarjeta_credito(OTRO_CLIENTE)
    with pytest.raises(ServiceError) as exc:
        banking.set_card_limit(CLIENTE, tarjeta_de_otro["card_id"], 50_000)
    mensaje = str(exc.value)
    assert tarjeta_de_otro["last4"] not in mensaje


# ------------------------------------------------------------- block/unblock
def test_bloquear_y_desbloquear_tarjeta():
    tarjeta = _tarjeta_debito()
    r1 = banking.block_card(CLIENTE, tarjeta["card_id"])
    assert r1["estado"] == "bloqueada"
    assert r1["ya_estaba_bloqueada"] is False

    r2 = banking.block_card(CLIENTE, tarjeta["card_id"])
    assert r2["ya_estaba_bloqueada"] is True  # idempotente, no truena

    r3 = banking.unblock_card(CLIENTE, tarjeta["card_id"])
    assert r3["estado"] == "activa"
    assert r3["ya_estaba_activa"] is False


def test_tarjeta_inexistente_es_not_found():
    with pytest.raises(ServiceError):
        banking.block_card(CLIENTE, "CRD-9999")


# -------------------------------------------------------------------- limite
def test_limite_no_puede_bajar_del_saldo_usado():
    tarjeta = _tarjeta_credito()
    with pytest.raises(ServiceError) as exc:
        banking.set_card_limit(CLIENTE, tarjeta["card_id"], tarjeta["saldo_utilizado"] - 1)
    assert "saldo" in str(exc.value).lower()


def test_limite_no_puede_pasar_de_3x_el_ingreso():
    cliente = accounts.get_client_snapshot(CLIENTE)
    tarjeta = _tarjeta_credito()
    tope = cliente["ingreso_mensual"] * banking.MULTIPLO_LIMITE_MAXIMO
    with pytest.raises(ServiceError) as exc:
        banking.set_card_limit(CLIENTE, tarjeta["card_id"], tope + 1)
    assert str(round(tope)) in str(exc.value) or f"{tope:,.0f}" in str(exc.value)


def test_limite_valido_se_aplica():
    tarjeta = _tarjeta_credito()
    nuevo = tarjeta["saldo_utilizado"] + 5_000
    resultado = banking.set_card_limit(CLIENTE, tarjeta["card_id"], nuevo)
    assert resultado["limite_credito"] == nuevo


def test_limite_en_tarjeta_de_debito_se_rechaza():
    tarjeta = _tarjeta_debito()
    with pytest.raises(ServiceError):
        banking.set_card_limit(CLIENTE, tarjeta["card_id"], 10_000)


# ---------------------------------------------------------------------- alias
def test_alias_se_recorta_y_se_puede_quitar():
    cuenta = _cuenta()
    r = banking.set_account_alias(CLIENTE, cuenta["account_id"], "  Mi cuenta   ")
    assert r["alias"] == "Mi cuenta"

    r2 = banking.set_account_alias(CLIENTE, cuenta["account_id"], "   ")
    assert r2["alias"] is None


def test_alias_demasiado_largo_se_rechaza():
    cuenta = _cuenta()
    with pytest.raises(ServiceError):
        banking.set_account_alias(CLIENTE, cuenta["account_id"], "x" * 41)


# ------------------------------------------------------------------- budgets
def test_set_budget_categoria_invalida():
    with pytest.raises(ServiceError):
        banking.set_budget(CLIENTE, "criptomonedas", 500)


def test_set_budget_no_puede_superar_el_ingreso():
    cliente = accounts.get_client_snapshot(CLIENTE)
    with pytest.raises(ServiceError):
        banking.set_budget(CLIENTE, "super", cliente["ingreso_mensual"] + 1)


def test_set_budget_crea_y_actualiza():
    banking.set_budget(CLIENTE, "transporte", 800)
    presupuestos = {b["categoria"]: b["monto_mensual"] for b in accounts.get_budgets(CLIENTE)["presupuestos"]}
    assert presupuestos["transporte"] == 800

    banking.set_budget(CLIENTE, "transporte", 950)
    presupuestos = {b["categoria"]: b["monto_mensual"] for b in accounts.get_budgets(CLIENTE)["presupuestos"]}
    assert presupuestos["transporte"] == 950  # actualizó, no duplicó


def test_alertas_vacias_sin_presupuestos():
    # CLI-0003 no tiene presupuestos sembrados.
    resultado = accounts.get_spending_alerts("CLI-0003")
    assert resultado["alertas"] == []


def test_alertas_marcan_excedido_correctamente():
    resultado = accounts.get_spending_alerts(CLIENTE)
    for alerta in resultado["alertas"]:
        assert alerta["excedido"] == (alerta["gastado"] > alerta["presupuesto"])


# -------------------------------------------------------------- search_transactions
def test_search_transactions_filtra_por_categoria():
    resultado = accounts.search_transactions(CLIENTE, categoria="super", limite=300)
    assert resultado["total"] > 0
    assert all(m["categoria"] == "super" for m in resultado["movimientos"])


def test_search_transactions_filtra_por_monto():
    resultado = accounts.search_transactions(CLIENTE, monto_min=5000, limite=300)
    assert all(m["monto"] >= 5000 for m in resultado["movimientos"])


def test_search_transactions_monto_min_mayor_que_max_falla():
    with pytest.raises(ServiceError):
        accounts.search_transactions(CLIENTE, monto_min=1000, monto_max=500)


def test_search_transactions_cuenta_ajena_falla():
    cuenta_de_otro = _cuenta(OTRO_CLIENTE)
    with pytest.raises(ServiceError):
        accounts.search_transactions(CLIENTE, account_id=cuenta_de_otro["account_id"])


def test_search_transactions_fecha_invalida_falla():
    with pytest.raises(ServiceError):
        accounts.search_transactions(CLIENTE, fecha_desde="no-es-una-fecha")
