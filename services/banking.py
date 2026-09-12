"""Mutaciones de banca personal: tarjetas, alias y presupuestos.

`services/accounts.py` es de solo lectura (ver su docstring); todo lo que
cambia estado de verdad vive aquí, siguiendo el mismo split que ya existe
entre `services/portfolio.py` (lectura/cálculo) y `services/orders.py`
(efecto) para inversiones.

Ninguna de estas mutaciones mueve dinero — no llevan el candado de dos pasos
de `place_order`. Sí llevan lo que sí les toca: verificación de que la
cuenta/tarjeta es del cliente en sesión (nunca se confirma ni se niega que
algo ajeno exista), límites de negocio explícitos, saneo de texto libre, e
idempotencia donde aplica (bloquear una tarjeta ya bloqueada no es error).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from bank import db
from services.accounts import CATEGORIAS_GASTO, _exigir_cliente, _exigir_cuenta_del_cliente
from services.errors import NotFound, ServiceError

ALIAS_LARGO_MAXIMO = 40
MULTIPLO_LIMITE_MAXIMO = 3  # una tarjeta de crédito no puede rebasar 3x el ingreso declarado


def _exigir_tarjeta_del_cliente(conn, client_id: str, card_id: str) -> dict[str, Any]:
    row = db.query_one(
        conn, "SELECT * FROM cards WHERE card_id = ? AND client_id = ?", (card_id, client_id))
    if row is None:
        raise NotFound(
            f"La tarjeta {card_id!r} no existe o no pertenece a {client_id}.",
            sugerencia="Usa `get_accounts` para ver las tarjetas de este cliente.",
        )
    return row


def _limpiar_alias(alias: str | None) -> str | None:
    """None o cadena vacía después de recortar -> se quita el apodo."""
    if alias is None:
        return None
    limpio = "".join(ch for ch in alias.strip() if ch.isprintable())
    if not limpio:
        return None
    if len(limpio) > ALIAS_LARGO_MAXIMO:
        raise ServiceError(
            f"El alias no puede pasar de {ALIAS_LARGO_MAXIMO} caracteres "
            f"(llegó con {len(limpio)}).")
    return limpio


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _registrar_evento_tarjeta(conn, card_id: str, client_id: str, tipo: str,
                              detalle: dict[str, Any]) -> None:
    conn.execute(
        "INSERT INTO card_events (event_id, card_id, client_id, tipo, detalle_json, creado_en)"
        " VALUES (?,?,?,?,?,?)",
        (f"CEV-{uuid.uuid4().hex[:12]}", card_id, client_id, tipo,
         json.dumps(detalle, ensure_ascii=False), _ahora()),
    )


def _tarjeta_publica(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "card_id": row["card_id"], "tipo": row["tipo"], "alias": row["alias"],
        "last4": row["last4"], "estado": row["estado"],
        "limite_credito": row["limite_credito"], "saldo_utilizado": row["saldo_utilizado"],
    }


def block_card(client_id: str, card_id: str) -> dict[str, Any]:
    """Bloquea una tarjeta. Idempotente: si ya estaba bloqueada, no es error.

    A propósito NO pide confirmación en dos pasos: en la vida real, bloquear
    una tarjeta (tarjeta perdida, cargo sospechoso) es la acción urgente que
    debe costar un solo toque. Lo que sí cuesta más es desbloquearla.
    """
    with db.session() as conn:
        _exigir_cliente(conn, client_id)
        tarjeta = _exigir_tarjeta_del_cliente(conn, client_id, card_id)
        ya_bloqueada = tarjeta["estado"] == "bloqueada"
        if not ya_bloqueada:
            conn.execute("UPDATE cards SET estado = 'bloqueada' WHERE card_id = ?", (card_id,))
            _registrar_evento_tarjeta(conn, card_id, client_id, "bloqueo", {})
            tarjeta = dict(tarjeta)
            tarjeta["estado"] = "bloqueada"
    return {**_tarjeta_publica(tarjeta), "ya_estaba_bloqueada": ya_bloqueada}


def unblock_card(client_id: str, card_id: str) -> dict[str, Any]:
    """Desbloquea una tarjeta. Idempotente igual que `block_card`."""
    with db.session() as conn:
        _exigir_cliente(conn, client_id)
        tarjeta = _exigir_tarjeta_del_cliente(conn, client_id, card_id)
        ya_activa = tarjeta["estado"] == "activa"
        if not ya_activa:
            conn.execute("UPDATE cards SET estado = 'activa' WHERE card_id = ?", (card_id,))
            _registrar_evento_tarjeta(conn, card_id, client_id, "desbloqueo", {})
            tarjeta = dict(tarjeta)
            tarjeta["estado"] = "activa"
    return {**_tarjeta_publica(tarjeta), "ya_estaba_activa": ya_activa}


def set_card_limit(client_id: str, card_id: str, nuevo_limite: float) -> dict[str, Any]:
    """Cambia el límite de una tarjeta de crédito, con las reglas de un banco real:
    no por debajo de lo ya usado, no por encima de un múltiplo del ingreso.
    """
    if nuevo_limite <= 0:
        raise ServiceError("`nuevo_limite` debe ser mayor que cero.")
    with db.session() as conn:
        cliente = _exigir_cliente(conn, client_id)
        tarjeta = _exigir_tarjeta_del_cliente(conn, client_id, card_id)
        if tarjeta["tipo"] != "credito":
            raise ServiceError(
                f"La tarjeta {card_id!r} es de débito; no tiene límite de crédito que ajustar.")
        if nuevo_limite < tarjeta["saldo_utilizado"]:
            raise ServiceError(
                f"El nuevo límite (${nuevo_limite:,.0f}) no puede ser menor al saldo ya "
                f"utilizado (${tarjeta['saldo_utilizado']:,.0f}).",
                sugerencia="Paga primero o propone un límite mayor o igual al saldo usado.",
            )
        tope = cliente["ingreso_mensual"] * MULTIPLO_LIMITE_MAXIMO
        if nuevo_limite > tope:
            raise ServiceError(
                f"${nuevo_limite:,.0f} excede el máximo que este perfil admite "
                f"(${tope:,.0f}, {MULTIPLO_LIMITE_MAXIMO}x el ingreso mensual declarado).",
                sugerencia=f"Pide como máximo ${tope:,.0f}.",
            )
        conn.execute("UPDATE cards SET limite_credito = ? WHERE card_id = ?",
                     (nuevo_limite, card_id))
        _registrar_evento_tarjeta(conn, card_id, client_id, "limite", {
            "anterior": tarjeta["limite_credito"], "nuevo": nuevo_limite})
        tarjeta = dict(tarjeta)
        tarjeta["limite_credito"] = nuevo_limite
    return _tarjeta_publica(tarjeta)


def set_card_alias(client_id: str, card_id: str, alias: str | None) -> dict[str, Any]:
    """Apodo de una tarjeta ('Platino viajes'). `alias=None` lo quita."""
    limpio = _limpiar_alias(alias)
    with db.session() as conn:
        _exigir_cliente(conn, client_id)
        tarjeta = _exigir_tarjeta_del_cliente(conn, client_id, card_id)
        conn.execute("UPDATE cards SET alias = ? WHERE card_id = ?", (limpio, card_id))
        _registrar_evento_tarjeta(conn, card_id, client_id, "alias", {"alias": limpio})
        tarjeta = dict(tarjeta)
        tarjeta["alias"] = limpio
    return _tarjeta_publica(tarjeta)


def set_account_alias(client_id: str, account_id: str, alias: str | None) -> dict[str, Any]:
    """Apodo de una cuenta ('Mi cuenta del súper'). `alias=None` lo quita."""
    limpio = _limpiar_alias(alias)
    with db.session() as conn:
        _exigir_cliente(conn, client_id)
        _exigir_cuenta_del_cliente(conn, client_id, account_id)
        conn.execute("UPDATE accounts SET alias = ? WHERE account_id = ?", (limpio, account_id))
    return {"account_id": account_id, "alias": limpio}


def set_budget(client_id: str, categoria: str, monto_mensual: float) -> dict[str, Any]:
    """Crea o actualiza el presupuesto mensual de una categoría de gasto."""
    if categoria not in CATEGORIAS_GASTO:
        raise ServiceError(
            f"{categoria!r} no es una categoría de gasto válida.",
            sugerencia=f"Categorías: {', '.join(sorted(CATEGORIAS_GASTO))}.",
        )
    if monto_mensual <= 0:
        raise ServiceError("`monto_mensual` debe ser mayor que cero.")
    with db.session() as conn:
        cliente = _exigir_cliente(conn, client_id)
        if monto_mensual > cliente["ingreso_mensual"]:
            raise ServiceError(
                f"${monto_mensual:,.0f} al mes en {categoria!r} es más que todo el ingreso "
                f"mensual declarado (${cliente['ingreso_mensual']:,.0f}).",
                sugerencia="Propone un presupuesto menor al ingreso mensual.",
            )
        ahora = _ahora()
        conn.execute(
            "INSERT INTO budgets (budget_id, client_id, categoria, monto_mensual,"
            " creado_en, actualizado_en) VALUES (?,?,?,?,?,?)"
            " ON CONFLICT (client_id, categoria) DO UPDATE SET"
            " monto_mensual = excluded.monto_mensual, actualizado_en = excluded.actualizado_en",
            (f"BUD-{uuid.uuid4().hex[:12]}", client_id, categoria, monto_mensual, ahora, ahora),
        )
    return {"client_id": client_id, "categoria": categoria, "monto_mensual": monto_mensual}
