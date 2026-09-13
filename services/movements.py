"""Todo lo que mueve dinero fuera de inversiones: pagar servicios, transferir y
sacar efectivo sin tarjeta. Más tres escrituras que no mueven dinero pero lo
preparan: registrar un servicio, guardar un contacto y generar una referencia
para depositar efectivo.

Los candados, en el orden en que se aplican:

  1. Dos pasos. `pay_service`, `transfer_money` y `withdraw_cash` NO ejecutan:
     validan todo, dejan la operación `pendiente` y entregan un
     `confirmation_token` (en la base solo queda su hash). Solo
     `confirm_payment` con ese token mueve dinero. A diferencia de
     `place_order`, el paso 2 es una tool aparte que recibe el `payment_id`:
     destino y monto ya quedaron guardados en el paso 1, así que entre lo que
     el usuario vio en pantalla y lo que se ejecuta no hay nada que el modelo
     pueda cambiar.
  2. Idempotencia. `idempotency_key` es UNIQUE por cliente: repetir el paso 1
     devuelve la misma operación, y repetir `confirm_payment` sobre una ya
     ejecutada devuelve el mismo folio con `duplicado: true`.
  3. Ownership. Cuenta de cargo, servicio, contacto y operación tienen que ser
     del cliente en sesión, y el error nunca confirma que algo ajeno exista.
  4. Reglas de dinero (`bank/pagos.py`): saldo, tope diario por segmento, tope
     por operación a destinos nuevos, CLABE con dígito verificador y retiros
     en múltiplos de 100. Se revisan en el paso 1 y OTRA VEZ al ejecutar,
     porque entre los dos pasos pudieron salir otros pagos.

Lo que ninguna tool hace: acreditar dinero que no salió de otra cuenta del
banco. El abono de un depósito en efectivo lo dispara el corresponsal
(`liquidar_deposito_en_efectivo`), y esa función a propósito NO está en
`services.REGISTRO`: el agente no puede crear dinero.
"""

from __future__ import annotations

import math
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta
from typing import Any

from bank import db, pagos
from services.accounts import _exigir_cliente, _exigir_cuenta_del_cliente, _fecha_valuacion
from services.banking import _limpiar_alias
from services.errors import NotFound, ReglaDeNegocio, ServiceError
from services.orders import VIGENCIA_TOKEN_MINUTOS, _ahora, _hash_token
from services.payments import (
    beneficiario_publico,
    pago_publico,
    referencia_publica,
    servicio_publico,
)

DISCLAIMER = "Operación simulada sobre datos sintéticos. No mueve dinero real."


# ---------------------------------------------------------------------- entradas
def _exigir_llave(idempotency_key: Any) -> None:
    if not idempotency_key or not isinstance(idempotency_key, str):
        raise ServiceError(
            "`idempotency_key` es obligatorio y debe ser un string estable.",
            sugerencia="Usa algo derivado de la intención, por ejemplo '<client_id>-t<turno>-luz'.",
        )


def _monto(valor: Any) -> float:
    try:
        monto = float(valor)
    except (TypeError, ValueError):
        raise ServiceError("`monto` debe ser un número.") from None
    if not math.isfinite(monto):
        raise ServiceError("`monto` debe ser un número finito.")
    return round(monto, 2)


def _texto(valor: Any, campo: str, largo_maximo: int, *, obligatorio: bool = False,
           sugerencia: str | None = None) -> str | None:
    """Recorta, quita caracteres no imprimibles y colapsa espacios."""
    limpio = " ".join("".join(ch for ch in str(valor) if ch.isprintable()).split()) \
        if valor is not None else ""
    if not limpio:
        if obligatorio:
            raise ServiceError(f"`{campo}` es obligatorio.", sugerencia=sugerencia)
        return None
    if len(limpio) > largo_maximo:
        raise ServiceError(
            f"`{campo}` no puede pasar de {largo_maximo} caracteres (llegó con {len(limpio)}).")
    return limpio


# ----------------------------------------------------------------------- reglas
def _cuenta_de_cargo(conn, client_id: str, account_id: str | None, *,
                     solo_transaccional: bool = True,
                     excluir: str | None = None) -> dict[str, Any]:
    if account_id:
        cuenta = _exigir_cuenta_del_cliente(conn, client_id, account_id)
    else:
        sql = "SELECT * FROM accounts WHERE client_id = ? AND account_id != ?"
        if solo_transaccional:
            sql += " AND tipo IN ('cheques', 'nomina', 'ahorro')"
        cuenta = db.query_one(conn, sql + " ORDER BY saldo_disponible DESC LIMIT 1",
                              (client_id, excluir or ""))
        if cuenta is None:
            raise ReglaDeNegocio(
                f"{client_id} no tiene una cuenta de la que pueda salir esta operación.",
                sugerencia="Usa `get_accounts` para ver sus cuentas.")
    if solo_transaccional and cuenta["tipo"] not in pagos.TIPOS_CUENTA_TRANSACCIONAL:
        raise ReglaDeNegocio(
            f"De la cuenta de {cuenta['tipo']} {cuenta['account_id']} no salen pagos, "
            "transferencias a terceros ni retiros.",
            sugerencia="Primero traspasa a una cuenta de cheques o nómina con `transfer_money` "
                       "y `cuenta_destino_id`.")
    return cuenta


def _exigir_saldo(cuenta: dict[str, Any], total: float) -> None:
    if cuenta["saldo_disponible"] + 1e-6 < total:
        raise ReglaDeNegocio(
            f"Saldo insuficiente en {cuenta['account_id']}: hay "
            f"${cuenta['saldo_disponible']:,.2f} y la operación pide ${total:,.2f}.",
            sugerencia="Baja el monto o elige otra cuenta con `get_accounts`.")


def _salidas_del_dia(conn, client_id: str, dia: str, excluir: str | None = None) -> float:
    """Lo que ya salió hoy del patrimonio. Los traspasos propios no cuentan."""
    fila = db.query_one(
        conn,
        "SELECT COALESCE(SUM(monto + comision), 0) AS total FROM payments"
        " WHERE client_id = ? AND estado IN ('ejecutada', 'ejecutando')"
        "   AND substr(COALESCE(ejecutada_en, creada_en), 1, 10) = ?"
        "   AND COALESCE(destino_tipo, '') != 'cuenta_propia'"
        "   AND payment_id != ?", (client_id, dia, excluir or ""))
    return float(fila["total"])


def _exigir_tope_diario(conn, cliente: dict[str, Any], total: float, momento: datetime,
                        excluir: str | None = None) -> None:
    tope = pagos.TOPE_DIARIO_POR_SEGMENTO[cliente["segmento"]]
    usado = _salidas_del_dia(conn, cliente["client_id"], momento.date().isoformat(), excluir)
    if usado + total > tope + 1e-6:
        raise ReglaDeNegocio(
            f"Rebasa el tope diario de salidas del segmento {cliente['segmento']} "
            f"(${tope:,.0f}): hoy ya salieron ${usado:,.2f} y esta operación pide ${total:,.2f}.",
            sugerencia=f"Hoy todavía pueden salir hasta ${max(0.0, tope - usado):,.2f}.")


def _es_destino_nuevo(beneficiario: dict[str, Any], momento: datetime) -> bool:
    creado = datetime.fromisoformat(beneficiario["creado_en"])
    return momento < creado + timedelta(minutes=pagos.ESPERA_DESTINO_NUEVO_MIN)


# ------------------------------------------------------------ ciclo de la operación
def _siguiente_folio(conn, momento: datetime) -> str:
    n = db.query_one(conn, "SELECT COUNT(*) AS n FROM payments")["n"]
    return f"PG-{momento.year}-{int(n) + 1:06d}"


def _operacion_existente(conn, client_id: str, idempotency_key: str,
                         tipo: str) -> dict[str, Any] | None:
    row = db.query_one(
        conn, "SELECT * FROM payments WHERE client_id = ? AND idempotency_key = ?",
        (client_id, idempotency_key))
    if row is None:
        return None
    if row["tipo"] != tipo:
        raise ReglaDeNegocio(
            f"La `idempotency_key` {idempotency_key!r} ya se usó para un {row['tipo']} "
            "de este cliente.",
            sugerencia="Usa una clave distinta para cada operación.")
    pendiente = row["estado"] == "pendiente"
    return {
        **pago_publico(conn, row),
        "duplicado": True,
        "requiere_confirmacion": pendiente,
        "mensaje": (
            "Ya había una operación pendiente con esa clave. El token se entregó cuando se "
            "creó; si se perdió, cancélala con `cancel_payment` y genera otra con una clave "
            "nueva." if pendiente else
            f"Esa operación ya está {row['estado']}. Folio {row['folio']}."),
        "disclaimer": DISCLAIMER,
    }


def _crear_pendiente(conn, *, cuenta: dict[str, Any], tipo: str, monto: float,
                     comision: float, concepto: str, idempotency_key: str,
                     momento: datetime, **destino: Any) -> tuple[dict[str, Any], str]:
    token = secrets.token_urlsafe(18)
    payment_id = f"PAY-{uuid.uuid4().hex[:16]}"
    columnas = {
        "payment_id": payment_id,
        "folio": _siguiente_folio(conn, momento),
        "client_id": cuenta["client_id"],
        "account_id": cuenta["account_id"],
        "tipo": tipo,
        "estado": "pendiente",
        "monto": monto,
        "comision": comision,
        "concepto": concepto,
        "creada_en": momento.isoformat(),
        "idempotency_key": idempotency_key,
        "confirmation_token_hash": _hash_token(token),
        **destino,
    }
    try:
        conn.execute(
            f"INSERT INTO payments ({', '.join(columnas)})"
            f" VALUES ({', '.join('?' for _ in columnas)})", tuple(columnas.values()))
    except sqlite3.IntegrityError as exc:           # carrera con otro turno
        raise ReglaDeNegocio(
            "Ya existe una operación con esa `idempotency_key` para este cliente.",
            sugerencia="Vuelve a llamar con la misma clave para recuperar su estado.",
        ) from exc
    return db.query_one(conn, "SELECT * FROM payments WHERE payment_id = ?", (payment_id,)), token


def _respuesta_pendiente(conn, row: dict[str, Any], token: str, cuenta: dict[str, Any],
                         extra: dict[str, Any] | None = None) -> dict[str, Any]:
    total = round(row["monto"] + row["comision"], 2)
    return {
        **pago_publico(conn, row),
        "saldo_antes": round(cuenta["saldo_disponible"], 2),
        "saldo_despues_estimado": round(cuenta["saldo_disponible"] - total, 2),
        **(extra or {}),
        "requiere_confirmacion": True,
        "confirmation_token": token,
        "vence_en_minutos": VIGENCIA_TOKEN_MINUTOS,
        "duplicado": False,
        "mensaje": "Operación registrada SIN ejecutar. Muéstrala en `pay.PaymentTicket` y llama "
                   "`confirm_payment` con este `payment_id` y `confirmation_token` solo cuando "
                   "el usuario confirme en pantalla.",
        "disclaimer": DISCLAIMER,
    }


def _cerrar_y_lanzar(conn, payment_id: str, estado: str, motivo: str,
                     error: ServiceError) -> None:
    """Deja la operación `rechazada`/`cancelada` y lo PERSISTE antes de lanzar.

    Sin el commit, el rollback de `db.session` borraría el cambio de estado
    junto con la excepción, y la operación volvería a quedar pendiente.
    """
    conn.execute("UPDATE payments SET estado = ?, motivo_rechazo = ? WHERE payment_id = ?",
                 (estado, motivo[:500], payment_id))
    conn.commit()
    raise error


def _mover(conn, account_id: str, tipo: str, monto: float, categoria: str,
           descripcion: str, comercio: str | None, momento: datetime) -> tuple[str, float]:
    """Un cargo o abono con su saldo posterior. Devuelve (txn_id, saldo nuevo)."""
    cuenta = db.query_one(
        conn, "SELECT saldo_disponible FROM accounts WHERE account_id = ?", (account_id,))
    signo = 1 if tipo == "abono" else -1
    saldo = round(cuenta["saldo_disponible"] + signo * monto, 2)
    conn.execute(
        "UPDATE accounts SET saldo_disponible = ?, saldo_liquidado = ? WHERE account_id = ?",
        (saldo, saldo, account_id))
    txn_id = f"TXN-{uuid.uuid4().hex[:10]}"
    conn.execute(
        "INSERT INTO transactions (txn_id, account_id, fecha, tipo, monto, categoria,"
        " descripcion, comercio, saldo_posterior) VALUES (?,?,?,?,?,?,?,?,?)",
        (txn_id, account_id, momento.isoformat(), tipo, round(monto, 2), categoria,
         descripcion, comercio, saldo))
    return txn_id, saldo


# ------------------------------------------------------------------ paso 1: servicio
def pay_service(
    client_id: str,
    service_id: str,
    idempotency_key: str,
    account_id: str | None = None,
) -> dict[str, Any]:
    """Paso 1 para pagar el recibo pendiente de un servicio guardado. No mueve dinero.

    Se paga el recibo completo: el monto sale del convenio, no de lo que diga
    el modelo.
    """
    _exigir_llave(idempotency_key)
    with db.session() as conn:
        cliente = _exigir_cliente(conn, client_id)
        existente = _operacion_existente(conn, client_id, idempotency_key, "servicio")
        if existente is not None:
            return existente

        servicio = db.query_one(
            conn, "SELECT * FROM saved_services WHERE service_id = ? AND client_id = ?",
            (service_id, client_id))
        if servicio is None:
            raise NotFound(
                f"El servicio {service_id!r} no existe o no pertenece a {client_id}.",
                sugerencia="Usa `get_bills` para ver sus servicios, o `register_service` para "
                           "dar de alta uno nuevo.")
        conv = pagos.CONVENIO_POR_ID[servicio["biller_id"]]
        recibo = db.query_one(
            conn, "SELECT * FROM bills WHERE service_id = ? AND estado = 'pendiente'"
                  " ORDER BY fecha_limite LIMIT 1", (service_id,))
        if recibo is None:
            raise ReglaDeNegocio(
                f"{servicio['alias'] or conv.nombre} no tiene recibo pendiente: está al corriente.",
                sugerencia="Revisa los demás recibos con `get_bills`.")

        cuenta = _cuenta_de_cargo(conn, client_id, account_id)
        momento = _ahora(conn)
        total = round(recibo["monto"] + conv.comision, 2)
        _exigir_saldo(cuenta, total)
        _exigir_tope_diario(conn, cliente, total, momento)

        row, token = _crear_pendiente(
            conn, cuenta=cuenta, tipo="servicio", monto=recibo["monto"],
            comision=conv.comision, concepto=f"Pago {conv.nombre} {recibo['periodo']}",
            idempotency_key=idempotency_key, momento=momento,
            service_id=service_id, bill_id=recibo["bill_id"])
        return _respuesta_pendiente(conn, row, token, cuenta)


# ------------------------------------------------------------- paso 1: transferencia
def transfer_money(
    client_id: str,
    monto: float,
    idempotency_key: str,
    concepto: str | None = None,
    account_id: str | None = None,
    beneficiary_id: str | None = None,
    clabe: str | None = None,
    titular: str | None = None,
    cuenta_destino_id: str | None = None,
) -> dict[str, Any]:
    """Paso 1 de una transferencia. No mueve dinero.

    Destino, exactamente uno de tres: `beneficiary_id` (contacto guardado),
    `clabe` (cuenta que no está guardada; exige `titular`) o
    `cuenta_destino_id` (una cuenta del mismo cliente, sin topes).
    """
    _exigir_llave(idempotency_key)
    destinos = [d for d in (beneficiary_id, clabe, cuenta_destino_id) if d not in (None, "")]
    if len(destinos) != 1:
        raise ServiceError(
            "Indica exactamente un destino: `beneficiary_id` (contacto guardado), `clabe` "
            "(cuenta nueva) o `cuenta_destino_id` (una cuenta propia).",
            sugerencia="Usa `get_beneficiaries` para ver los contactos del cliente.")
    monto = _monto(monto)
    if not pagos.MONTO_MINIMO_TRANSFERENCIA <= monto <= pagos.MONTO_MAXIMO_TRANSFERENCIA:
        raise ServiceError(
            f"Una transferencia va de ${pagos.MONTO_MINIMO_TRANSFERENCIA:,.2f} a "
            f"${pagos.MONTO_MAXIMO_TRANSFERENCIA:,.0f}; llegó ${monto:,.2f}.")
    concepto = _texto(concepto, "concepto", pagos.CONCEPTO_LARGO_MAXIMO) or "Transferencia"

    with db.session() as conn:
        cliente = _exigir_cliente(conn, client_id)
        existente = _operacion_existente(conn, client_id, idempotency_key, "transferencia")
        if existente is not None:
            return existente
        momento = _ahora(conn)

        def a_cuenta_propia(propia: dict[str, Any]) -> dict[str, Any]:
            return {"destino_tipo": "cuenta_propia", "destino_numero": propia["clabe_mock"],
                    "destino_banco": pagos.BANCO_PROPIO, "destino_titular": cliente["nombre"],
                    "destino_account_id": propia["account_id"]}

        def a_contacto(ben: dict[str, Any]) -> dict[str, Any]:
            return {"destino_tipo": ben["tipo_destino"], "destino_numero": ben["numero"],
                    "destino_banco": ben["banco_codigo"], "destino_titular": ben["titular"],
                    "beneficiary_id": ben["beneficiary_id"]}

        es_nuevo = False
        if cuenta_destino_id:
            destino = a_cuenta_propia(_exigir_cuenta_del_cliente(conn, client_id, cuenta_destino_id))
        elif beneficiary_id:
            ben = db.query_one(
                conn, "SELECT * FROM beneficiaries WHERE beneficiary_id = ? AND client_id = ?",
                (beneficiary_id, client_id))
            if ben is None:
                raise NotFound(
                    f"El contacto {beneficiary_id!r} no existe o no pertenece a {client_id}.",
                    sugerencia="Usa `get_beneficiaries`, o manda la `clabe` directo.")
            es_nuevo = _es_destino_nuevo(ben, momento)
            destino = a_contacto(ben)
        else:
            numero = pagos.normalizar_numero(clabe)
            problema = pagos.problema_clabe(numero)
            if problema:
                raise ServiceError(
                    f"La CLABE no es válida: {problema}.",
                    sugerencia="Pídele al usuario que la revise. No completes ni corrijas dígitos "
                               "por tu cuenta.")
            propia = db.query_one(
                conn, "SELECT * FROM accounts WHERE clabe_mock = ? AND client_id = ?",
                (numero, client_id))
            ben = db.query_one(
                conn, "SELECT * FROM beneficiaries WHERE numero = ? AND client_id = ?",
                (numero, client_id))
            if propia is not None:
                destino = a_cuenta_propia(propia)
            elif ben is not None:
                es_nuevo = _es_destino_nuevo(ben, momento)
                destino = a_contacto(ben)
            else:
                es_nuevo = True
                destino = {
                    "destino_tipo": "clabe", "destino_numero": numero,
                    "destino_banco": numero[:3],
                    "destino_titular": _texto(
                        titular, "titular", pagos.TITULAR_LARGO_MAXIMO, obligatorio=True,
                        sugerencia="Pídele al usuario el nombre de quien recibe; va en el "
                                   "comprobante SPEI."),
                }

        propio = destino["destino_tipo"] == "cuenta_propia"
        cuenta = _cuenta_de_cargo(conn, client_id, account_id, solo_transaccional=not propio,
                                  excluir=destino.get("destino_account_id"))
        if propio and destino["destino_account_id"] == cuenta["account_id"]:
            raise ServiceError("La cuenta de origen y la de destino son la misma.",
                               sugerencia="Elige otra cuenta con `get_accounts`.")
        if es_nuevo and monto > pagos.TOPE_DESTINO_NUEVO:
            raise ReglaDeNegocio(
                f"A una cuenta nueva (sin guardar, o guardada hace menos de "
                f"{pagos.ESPERA_DESTINO_NUEVO_MIN} minutos) se pueden mandar hasta "
                f"${pagos.TOPE_DESTINO_NUEVO:,.0f} por operación; esta pide ${monto:,.2f}.",
                sugerencia=f"Manda hasta ${pagos.TOPE_DESTINO_NUEVO:,.0f} ahora, o guarda el "
                           f"contacto con `save_beneficiary`: pasados "
                           f"{pagos.ESPERA_DESTINO_NUEVO_MIN} minutos ya no aplica el tope.")
        _exigir_saldo(cuenta, monto)
        if not propio:
            _exigir_tope_diario(conn, cliente, monto, momento)

        row, token = _crear_pendiente(
            conn, cuenta=cuenta, tipo="transferencia", monto=monto, comision=0.0,
            concepto=concepto, idempotency_key=idempotency_key, momento=momento, **destino)
        return _respuesta_pendiente(conn, row, token, cuenta, {
            "destino_nuevo": es_nuevo,
            "mismo_banco": destino["destino_banco"] == pagos.BANCO_PROPIO,
        })


# ------------------------------------------------------------------ paso 1: retiro
def withdraw_cash(
    client_id: str,
    monto: float,
    idempotency_key: str,
    account_id: str | None = None,
) -> dict[str, Any]:
    """Paso 1 de un retiro sin tarjeta. No mueve dinero ni genera el código."""
    _exigir_llave(idempotency_key)
    monto = _monto(monto)
    if not pagos.MONTO_MINIMO_RETIRO <= monto <= pagos.TOPE_RETIRO_SIN_TARJETA:
        raise ServiceError(
            f"Un retiro sin tarjeta va de ${pagos.MONTO_MINIMO_RETIRO:,.0f} a "
            f"${pagos.TOPE_RETIRO_SIN_TARJETA:,.0f}; llegó ${monto:,.2f}.")
    if monto % pagos.MULTIPLO_RETIRO:
        abajo = math.floor(monto / pagos.MULTIPLO_RETIRO) * pagos.MULTIPLO_RETIRO
        raise ServiceError(
            f"Los cajeros entregan billetes: el monto tiene que ser múltiplo de "
            f"${pagos.MULTIPLO_RETIRO}. Llegó ${monto:,.2f}.",
            sugerencia=f"Prueba ${abajo:,.0f} o ${abajo + pagos.MULTIPLO_RETIRO:,.0f}.")

    with db.session() as conn:
        cliente = _exigir_cliente(conn, client_id)
        existente = _operacion_existente(conn, client_id, idempotency_key, "retiro_sin_tarjeta")
        if existente is not None:
            return existente
        cuenta = _cuenta_de_cargo(conn, client_id, account_id)
        momento = _ahora(conn)
        _exigir_saldo(cuenta, monto)
        _exigir_tope_diario(conn, cliente, monto, momento)
        row, token = _crear_pendiente(
            conn, cuenta=cuenta, tipo="retiro_sin_tarjeta", monto=monto, comision=0.0,
            concepto="Retiro sin tarjeta", idempotency_key=idempotency_key, momento=momento)
        return _respuesta_pendiente(conn, row, token, cuenta, {
            "vigencia_codigo_horas": pagos.VIGENCIA_CODIGO_RETIRO_HORAS,
        })


# ------------------------------------------------------------------------ paso 2
def confirm_payment(client_id: str, payment_id: str, confirmation_token: str) -> dict[str, Any]:
    """Paso 2: ejecuta una operación pendiente. La única tool que mueve dinero.

    Solo se llama cuando el usuario confirmó en pantalla: el token viaja en el
    `context` de la acción `confirm_payment` de `pay.PaymentTicket`.
    """
    if not confirmation_token or not isinstance(confirmation_token, str):
        raise ServiceError("`confirmation_token` es obligatorio: es el que devolvió el paso 1.")

    with db.session() as conn:
        cliente = _exigir_cliente(conn, client_id)
        row = db.query_one(
            conn, "SELECT * FROM payments WHERE payment_id = ? AND client_id = ?",
            (payment_id, client_id))
        if row is None:
            raise NotFound(
                f"La operación {payment_id!r} no existe o no pertenece a {client_id}.",
                sugerencia="Usa `get_payment_history` para ver sus operaciones.")

        if row["estado"] == "ejecutada":
            aviso = (" El código de retiro se entrega una sola vez; si se perdió, cancela el "
                     "retiro y genera otro." if row["tipo"] == "retiro_sin_tarjeta" else "")
            return {**pago_publico(conn, row), "duplicado": True, "requiere_confirmacion": False,
                    "mensaje": f"Esta operación ya se había ejecutado. Folio {row['folio']}.{aviso}",
                    "disclaimer": DISCLAIMER}
        if row["estado"] in ("rechazada", "cancelada"):
            motivo = f": {row['motivo_rechazo']}" if row["motivo_rechazo"] else ""
            raise ReglaDeNegocio(
                f"La operación {row['folio']} está {row['estado']}{motivo}.",
                sugerencia="Genera una operación nueva con otra `idempotency_key`.")
        if not secrets.compare_digest(_hash_token(confirmation_token),
                                      row["confirmation_token_hash"]):
            raise ReglaDeNegocio(
                "El `confirmation_token` no corresponde a esta operación.",
                sugerencia="Usa exactamente el token que devolvió el paso 1; si se perdió, "
                           "cancela con `cancel_payment` y vuelve a generar la operación.")

        momento = _ahora(conn)
        if momento - datetime.fromisoformat(row["creada_en"]) > timedelta(
                minutes=VIGENCIA_TOKEN_MINUTOS):
            _cerrar_y_lanzar(
                conn, payment_id, "cancelada", f"confirmación vencida tras {VIGENCIA_TOKEN_MINUTOS} min",
                ReglaDeNegocio("La confirmación venció. Hay que volver a generar la operación.",
                               sugerencia="Llama otra vez el paso 1 con una clave nueva."))

        # Reclamo atómico, igual que en `orders._ejecutar`: si dos confirmaciones
        # llegan juntas, solo una gana este UPDATE.
        cur = conn.execute(
            "UPDATE payments SET estado = 'ejecutando' WHERE payment_id = ? AND estado = 'pendiente'",
            (payment_id,))
        if cur.rowcount == 0:
            raise ReglaDeNegocio(
                "La operación ya no está pendiente: la tomó otra solicitud.",
                sugerencia="Consulta `get_payment_history` para ver cómo quedó.")

        # Segunda revisión: entre el paso 1 y este pudieron salir otros pagos.
        cuenta = db.query_one(conn, "SELECT * FROM accounts WHERE account_id = ?",
                              (row["account_id"],))
        total = round(row["monto"] + row["comision"], 2)
        try:
            _exigir_saldo(cuenta, total)
            if row["destino_tipo"] != "cuenta_propia":
                _exigir_tope_diario(conn, cliente, total, momento, excluir=payment_id)
        except ReglaDeNegocio as exc:
            _cerrar_y_lanzar(conn, payment_id, "rechazada", f"al ejecutar: {exc}", exc)

        if row["tipo"] == "servicio":
            resultado = _ejecutar_servicio(conn, row, cuenta, momento)
        elif row["tipo"] == "transferencia":
            resultado = _ejecutar_transferencia(conn, row, cuenta, cliente, momento)
        else:
            resultado = _ejecutar_retiro(conn, row, cuenta, momento)

        conn.execute("UPDATE payments SET estado = 'ejecutada', ejecutada_en = ? WHERE payment_id = ?",
                     (momento.isoformat(), payment_id))
        final = db.query_one(conn, "SELECT * FROM payments WHERE payment_id = ?", (payment_id,))
        return {**pago_publico(conn, final), **resultado, "duplicado": False,
                "requiere_confirmacion": False, "disclaimer": DISCLAIMER}


def _ejecutar_servicio(conn, row, cuenta, momento) -> dict[str, Any]:
    servicio = db.query_one(conn, "SELECT * FROM saved_services WHERE service_id = ?",
                            (row["service_id"],))
    conv = pagos.CONVENIO_POR_ID[servicio["biller_id"]]
    recibo = db.query_one(conn, "SELECT * FROM bills WHERE bill_id = ?", (row["bill_id"],))
    if recibo["estado"] != "pendiente":
        _cerrar_y_lanzar(
            conn, row["payment_id"], "rechazada", "el recibo ya estaba pagado",
            ReglaDeNegocio(
                f"El recibo {recibo['periodo']} de {conv.nombre} ya estaba pagado; no se cobró "
                "dos veces.", sugerencia="Revisa `get_payment_history`."))
    _, saldo = _mover(conn, cuenta["account_id"], "cargo", row["monto"], "servicios",
                      f"Pago {conv.nombre} · folio {row['folio']}", conv.nombre, momento)
    if row["comision"] > 0:
        _, saldo = _mover(conn, cuenta["account_id"], "cargo", row["comision"], "comisiones",
                          f"Comisión pago {conv.nombre} · folio {row['folio']}", None, momento)
    conn.execute("UPDATE bills SET estado = 'pagado', payment_id = ? WHERE bill_id = ?",
                 (row["payment_id"], recibo["bill_id"]))
    return {"saldo_despues": saldo,
            "mensaje": f"Pagado: {conv.nombre} {recibo['periodo']}. Folio {row['folio']}."}


def _ejecutar_transferencia(conn, row, cuenta, cliente, momento) -> dict[str, Any]:
    concepto = row["concepto"]
    if row["destino_tipo"] == "cuenta_propia":
        destino = db.query_one(conn, "SELECT * FROM accounts WHERE account_id = ?",
                               (row["destino_account_id"],))
        _, saldo = _mover(conn, cuenta["account_id"], "cargo", row["monto"], "traspaso",
                          f"Traspaso a tu cuenta de {destino['tipo']} · folio {row['folio']}",
                          None, momento)
        _mover(conn, destino["account_id"], "abono", row["monto"], "traspaso",
               f"Traspaso desde tu cuenta de {cuenta['tipo']} · folio {row['folio']}",
               None, momento)
        return {"saldo_despues": saldo,
                "mensaje": f"Listo: el dinero ya está en tu cuenta de {destino['tipo']}. "
                           f"Folio {row['folio']}."}

    banco = pagos.BANCOS.get(row["destino_banco"], row["destino_banco"])
    interna = None
    if row["destino_banco"] == pagos.BANCO_PROPIO and row["destino_tipo"] == "clabe":
        interna = db.query_one(conn, "SELECT * FROM accounts WHERE clabe_mock = ?",
                               (row["destino_numero"],))
        if interna is None:
            _cerrar_y_lanzar(
                conn, row["payment_id"], "rechazada", "SPEI devuelto: la cuenta destino no existe",
                ReglaDeNegocio(
                    "La transferencia fue devuelta: la CLABE no corresponde a una cuenta activa. "
                    "No se cobró nada.",
                    sugerencia="Pídele al usuario que confirme la CLABE con quien va a recibir."))

    clave = f"BNTE{momento:%Y%m%d}{secrets.randbelow(10**10):010d}"
    _, saldo = _mover(
        conn, cuenta["account_id"], "cargo", row["monto"], "transferencia",
        f"{'Transferencia' if interna else 'SPEI enviado'} · {concepto} · rastreo {clave}",
        f"{row['destino_titular']} ({banco})", momento)
    if interna is not None:
        # Mismo banco: el dinero llega en el acto y el que recibe ve de quién.
        txn_abono, _ = _mover(conn, interna["account_id"], "abono", row["monto"],
                              "transferencia", f"Transferencia recibida · {concepto}",
                              cliente["nombre"], momento)
        conn.execute(
            "INSERT INTO incoming_transfers (txn_id, canal, remitente, banco_origen,"
            " cuenta_origen_mask, concepto, clave_rastreo) VALUES (?,?,?,?,?,?,?)",
            (txn_abono, "interna", cliente["nombre"], pagos.BANCO_PROPIO,
             pagos.enmascarar(cuenta["clabe_mock"]), concepto, clave))
        conn.execute("UPDATE payments SET destino_account_id = ? WHERE payment_id = ?",
                     (interna["account_id"], row["payment_id"]))
    conn.execute("UPDATE payments SET clave_rastreo = ? WHERE payment_id = ?",
                 (clave, row["payment_id"]))
    return {"saldo_despues": saldo,
            "mensaje": f"Transferencia enviada a {row['destino_titular']} ({banco}). "
                       f"Clave de rastreo {clave}."}


def _ejecutar_retiro(conn, row, cuenta, momento) -> dict[str, Any]:
    codigo = f"{secrets.randbelow(10**12):012d}"
    vence = momento + timedelta(hours=pagos.VIGENCIA_CODIGO_RETIRO_HORAS)
    _, saldo = _mover(conn, cuenta["account_id"], "cargo", row["monto"], "efectivo",
                      f"Retiro sin tarjeta · folio {row['folio']}", None, momento)
    conn.execute(
        "UPDATE payments SET codigo_retiro_hash = ?, codigo_vence_en = ? WHERE payment_id = ?",
        (_hash_token(codigo), vence.isoformat(), row["payment_id"]))
    return {
        "saldo_despues": saldo,
        "codigo_retiro": codigo,
        "codigo_vence_en": vence.isoformat(),
        "mensaje": "Código listo. Se muestra una sola vez: úsalo en un cajero del banco antes "
                   "de que venza.",
    }


# ----------------------------------------------------------------------- cancelar
def cancel_payment(client_id: str, payment_id: str) -> dict[str, Any]:
    """Cancela una operación pendiente, o un retiro sin tarjeta cuyo código no se usó.

    Pendiente: no se había movido nada, solo cambia de estado. Retiro ya
    emitido: el código deja de servir y el dinero regresa a la cuenta. Un pago
    de servicio o un SPEI ya ejecutados no se revierten desde aquí.
    """
    with db.session() as conn:
        _exigir_cliente(conn, client_id)
        row = db.query_one(
            conn, "SELECT * FROM payments WHERE payment_id = ? AND client_id = ?",
            (payment_id, client_id))
        if row is None:
            raise NotFound(
                f"La operación {payment_id!r} no existe o no pertenece a {client_id}.",
                sugerencia="Usa `get_payment_history` para ver sus operaciones.")

        if row["estado"] in ("cancelada", "rechazada"):
            return {**pago_publico(conn, row), "ya_estaba_cerrada": True, "reembolso": None,
                    "mensaje": f"La operación ya estaba {row['estado']}."}
        if row["estado"] == "ejecutando":
            raise ReglaDeNegocio("La operación se está ejecutando en este momento.",
                                 sugerencia="Consulta `get_payment_history` en un momento.")

        momento = _ahora(conn)
        if row["estado"] == "pendiente":
            conn.execute(
                "UPDATE payments SET estado = 'cancelada', motivo_rechazo = ?"
                " WHERE payment_id = ? AND estado = 'pendiente'",
                ("cancelada por el cliente antes de confirmar", payment_id))
            final = db.query_one(conn, "SELECT * FROM payments WHERE payment_id = ?", (payment_id,))
            return {**pago_publico(conn, final), "ya_estaba_cerrada": False, "reembolso": None,
                    "mensaje": "Cancelada. No se movió dinero."}

        if row["tipo"] != "retiro_sin_tarjeta":
            que = "una transferencia" if row["tipo"] == "transferencia" else "un pago de servicio"
            raise ReglaDeNegocio(
                f"La operación {row['folio']} ya se ejecutó: {que} liquidado no se revierte "
                "desde aquí.",
                sugerencia="Si fue un error, el cliente tiene que pedir la aclaración al banco o "
                           "la devolución a quien recibió.")

        # En la simulación ningún cajero cobra el código, así que cancelarlo
        # siempre reembolsa. En un banco real habría que verificar antes que
        # no se haya dispuesto.
        conn.execute(
            "UPDATE payments SET estado = 'cancelada', motivo_rechazo = ?, codigo_retiro_hash = NULL"
            " WHERE payment_id = ? AND estado = 'ejecutada'",
            ("retiro cancelado por el cliente; código invalidado", payment_id))
        _, saldo = _mover(conn, row["account_id"], "abono", row["monto"], "efectivo",
                          f"Cancelación de retiro sin tarjeta · folio {row['folio']}", None, momento)
        final = db.query_one(conn, "SELECT * FROM payments WHERE payment_id = ?", (payment_id,))
        return {**pago_publico(conn, final), "ya_estaba_cerrada": False, "reembolso": row["monto"],
                "saldo_despues": saldo,
                "mensaje": "Retiro cancelado: el código ya no sirve y el dinero regresó a la cuenta."}


# --------------------------------------------------- escrituras que no mueven dinero
def register_service(
    client_id: str,
    biller_id: str,
    referencia: str,
    alias: str | None = None,
) -> dict[str, Any]:
    """Guarda un servicio (convenio + referencia) y consulta su adeudo.

    La referencia se valida contra el formato del convenio antes de guardar
    nada. La consulta de adeudo es simulada pero determinista: registrar dos
    veces la misma referencia no inventa dos recibos.
    """
    conv = pagos.CONVENIO_POR_ID.get(biller_id)
    if conv is None:
        raise NotFound(f"No existe el convenio {biller_id!r}.",
                       sugerencia="Usa `get_billers` para ver los convenios y su `biller_id`.")
    numero = pagos.normalizar_numero(referencia)
    if not pagos.referencia_valida(conv, numero):
        raise ServiceError(
            f"La referencia de {conv.nombre} es: {conv.referencia_etiqueta}. Llegaron "
            f"{len(numero)} caracteres{'' if numero.isdigit() else ', no todos dígitos'}.",
            sugerencia="Pídele al usuario que la copie tal cual del recibo.")
    limpio = _limpiar_alias(alias)

    with db.session() as conn:
        _exigir_cliente(conn, client_id)
        hoy = _fecha_valuacion(conn)
        existente = db.query_one(
            conn, "SELECT * FROM saved_services WHERE client_id = ? AND biller_id = ?"
                  " AND referencia = ?", (client_id, conv.biller_id, numero))
        if existente is not None:
            if limpio and limpio != existente["alias"]:
                conn.execute("UPDATE saved_services SET alias = ? WHERE service_id = ?",
                             (limpio, existente["service_id"]))
                existente = {**existente, "alias": limpio}
            return {**servicio_publico(conn, existente, hoy), "ya_existia": True,
                    "mensaje": "Ese servicio ya estaba registrado."}

        service_id = f"SRV-{uuid.uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO saved_services (service_id, client_id, biller_id, referencia, alias,"
            " creado_en) VALUES (?,?,?,?,?,?)",
            (service_id, client_id, conv.biller_id, numero, limpio, _ahora(conn).isoformat()))
        recibo = pagos.recibo_simulado(conv, numero, hoy)
        conn.execute(
            "INSERT INTO bills (bill_id, service_id, periodo, monto, fecha_emision, fecha_limite)"
            " VALUES (?,?,?,?,?,?)",
            (f"BIL-{uuid.uuid4().hex[:12]}", service_id, recibo["periodo"], recibo["monto"],
             recibo["fecha_emision"], recibo["fecha_limite"]))
        row = db.query_one(conn, "SELECT * FROM saved_services WHERE service_id = ?", (service_id,))
        return {**servicio_publico(conn, row, hoy), "ya_existia": False,
                "mensaje": "Servicio registrado. El adeudo se consultó al convenio (simulado)."}


def save_beneficiary(
    client_id: str,
    alias: str,
    titular: str,
    clabe: str | None = None,
    tarjeta: str | None = None,
    banco_codigo: str | None = None,
) -> dict[str, Any]:
    """Guarda un contacto para transferir. No mueve dinero.

    Un contacto recién guardado sigue contando como destino nuevo durante
    `ESPERA_DESTINO_NUEVO_MIN`: guardarlo no es un atajo para saltarse el tope.
    """
    if (clabe in (None, "")) == (tarjeta in (None, "")):
        raise ServiceError("Manda `clabe` o `tarjeta`, una de las dos.")
    alias_limpio = _limpiar_alias(alias)
    if alias_limpio is None:
        raise ServiceError("`alias` es obligatorio: es como el cliente reconoce al contacto.")
    titular_limpio = _texto(titular, "titular", pagos.TITULAR_LARGO_MAXIMO, obligatorio=True,
                            sugerencia="Pídele al usuario el nombre de quien recibe.")

    if clabe not in (None, ""):
        numero = pagos.normalizar_numero(clabe)
        problema = pagos.problema_clabe(numero)
        if problema:
            raise ServiceError(f"La CLABE no es válida: {problema}.",
                               sugerencia="Pídele al usuario que la revise.")
        if banco_codigo and banco_codigo != numero[:3]:
            raise ServiceError(
                f"Esa CLABE es de {pagos.BANCOS[numero[:3]]} (código {numero[:3]}), no del "
                f"código {banco_codigo}.", sugerencia="No mandes `banco_codigo` con una CLABE.")
        tipo, banco = "clabe", numero[:3]
    else:
        numero = pagos.normalizar_numero(tarjeta)
        if len(numero) != 16 or not pagos.luhn_valido(numero):
            raise ServiceError("Una tarjeta de débito tiene 16 dígitos y un dígito verificador "
                               "válido; esta no cuadra.",
                               sugerencia="Pídele al usuario que la revise.")
        if banco_codigo not in pagos.BANCOS:
            raise ServiceError(
                "Para una tarjeta hace falta `banco_codigo`: el SPEI a tarjeta necesita saber "
                "el banco.",
                sugerencia="Códigos: " + ", ".join(f"{c} {n}" for c, n in pagos.BANCOS.items()) + ".")
        tipo, banco = "tarjeta", banco_codigo

    with db.session() as conn:
        _exigir_cliente(conn, client_id)
        if tipo == "clabe" and db.query_one(
                conn, "SELECT 1 FROM accounts WHERE client_id = ? AND clabe_mock = ?",
                (client_id, numero)):
            raise ReglaDeNegocio(
                "Esa CLABE es de una cuenta del propio cliente; no hace falta guardarla.",
                sugerencia="Para moverle dinero usa `transfer_money` con `cuenta_destino_id`.")
        momento = _ahora(conn)
        existente = db.query_one(
            conn, "SELECT * FROM beneficiaries WHERE client_id = ? AND numero = ?",
            (client_id, numero))
        if existente is not None:
            return {**beneficiario_publico(existente, momento), "ya_existia": True,
                    "mensaje": "Ese contacto ya estaba guardado."}
        beneficiary_id = f"BEN-{uuid.uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO beneficiaries (beneficiary_id, client_id, alias, titular, tipo_destino,"
            " numero, banco_codigo, creado_en) VALUES (?,?,?,?,?,?,?,?)",
            (beneficiary_id, client_id, alias_limpio, titular_limpio, tipo, numero, banco,
             momento.isoformat()))
        row = db.query_one(conn, "SELECT * FROM beneficiaries WHERE beneficiary_id = ?",
                           (beneficiary_id,))
        return {**beneficiario_publico(row, momento), "ya_existia": False,
                "mensaje": f"Contacto guardado. Durante {pagos.ESPERA_DESTINO_NUEVO_MIN} minutos "
                           f"cuenta como destino nuevo: hasta ${pagos.TOPE_DESTINO_NUEVO:,.0f} "
                           "por operación."}


def create_deposit_reference(
    client_id: str,
    canal_id: str,
    account_id: str | None = None,
) -> dict[str, Any]:
    """Referencia para depositar efectivo en un corresponsal. No mueve dinero.

    El abono llega cuando el corresponsal liquida (`liquidar_deposito_en_efectivo`),
    que no es una tool: el agente no puede acreditar dinero.
    """
    canal = pagos.CANAL_POR_ID.get(canal_id)
    if canal is None or not canal.requiere_referencia:
        con_referencia = [c.canal_id for c in pagos.CANALES_EFECTIVO if c.requiere_referencia]
        extra = (" En cajeros y sucursal se deposita con la tarjeta o el número de cuenta, sin "
                 "referencia." if canal is not None else "")
        raise ServiceError(f"{canal_id!r} no genera referencia de depósito.{extra}",
                           sugerencia=f"Canales con referencia: {', '.join(con_referencia)}.")

    with db.session() as conn:
        _exigir_cliente(conn, client_id)
        cuenta = _cuenta_de_cargo(conn, client_id, account_id)
        momento = _ahora(conn)
        while True:
            referencia = f"{secrets.randbelow(10**16):016d}"
            if db.query_one(conn, "SELECT 1 FROM deposit_references WHERE referencia = ?",
                            (referencia,)) is None:
                break
        reference_id = f"DEP-{uuid.uuid4().hex[:12]}"
        conn.execute(
            "INSERT INTO deposit_references (reference_id, client_id, account_id, canal_id,"
            " referencia, comision, monto_maximo, creada_en, vence_en)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (reference_id, client_id, cuenta["account_id"], canal.canal_id, referencia,
             canal.comision_deposito, canal.monto_maximo_deposito, momento.isoformat(),
             (momento + timedelta(hours=pagos.VIGENCIA_REFERENCIA_DEPOSITO_HORAS)).isoformat()))
        row = db.query_one(conn, "SELECT * FROM deposit_references WHERE reference_id = ?",
                           (reference_id,))
    return {**referencia_publica(row),
            "mensaje": f"Referencia lista para depositar en {canal.nombre}. El dinero llega a la "
                       "cuenta cuando la tienda confirma el pago.",
            "disclaimer": DISCLAIMER}


# ------------------------------------------------ liquidación (NO es una tool)
def liquidar_deposito_en_efectivo(referencia: str, monto: float) -> dict[str, Any]:
    """El corresponsal avisa que el cliente pagó en caja y el banco acredita.

    Vive aquí para reutilizar el mismo `_mover`, pero NO está en
    `services.REGISTRO` ni en `agent/tools.py`: es la frontera entre lo que el
    agente puede hacer y lo que solo pasa cuando llega dinero de fuera. La usa
    `scripts/simular_deposito.py` para el demo.
    """
    monto = _monto(monto)
    if monto <= 0:
        raise ServiceError("`monto` debe ser mayor que cero.")
    with db.session() as conn:
        ref = db.query_one(conn, "SELECT * FROM deposit_references WHERE referencia = ?",
                           (pagos.normalizar_numero(referencia),))
        if ref is None:
            raise NotFound("No existe esa referencia de depósito.")
        if ref["estado"] != "vigente":
            raise ReglaDeNegocio(f"La referencia ya está {ref['estado']}; no se acredita dos veces.")
        momento = _ahora(conn)
        if momento > datetime.fromisoformat(ref["vence_en"]):
            raise ReglaDeNegocio("La referencia venció; el corresponsal debe rechazar el depósito.")
        if monto > ref["monto_maximo"]:
            raise ReglaDeNegocio(
                f"El máximo por depósito en este canal es ${ref['monto_maximo']:,.0f}.")
        canal = pagos.CANAL_POR_ID[ref["canal_id"]]
        txn_id, saldo = _mover(conn, ref["account_id"], "abono", monto, "deposito",
                               f"Depósito en efectivo · {canal.nombre}", canal.nombre, momento)
        conn.execute(
            "INSERT INTO incoming_transfers (txn_id, canal, remitente, banco_origen,"
            " cuenta_origen_mask, concepto, clave_rastreo) VALUES (?,?,?,?,?,?,?)",
            (txn_id, "deposito_efectivo", "Depósito en efectivo", None, None,
             f"{canal.nombre} · ref {pagos.enmascarar(ref['referencia'])}", None))
        conn.execute(
            "UPDATE deposit_references SET estado = 'liquidada', liquidada_en = ?,"
            " monto_liquidado = ?, txn_id = ? WHERE reference_id = ?",
            (momento.isoformat(), monto, txn_id, ref["reference_id"]))
    return {"reference_id": ref["reference_id"], "account_id": ref["account_id"],
            "estado": "liquidada", "monto": monto, "saldo_despues": saldo, "txn_id": txn_id}
