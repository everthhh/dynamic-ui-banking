"""Ordenes de inversion. La unica parte del sistema con efecto real.

Dos candados, los dos exigidos por §07 del marco tecnico:

  1. Confirmacion en dos pasos. La primera llamada NO ejecuta: registra la
     orden como `pendiente` y devuelve un `confirmation_token`. Solo una
     segunda llamada con ese token mueve dinero. El modelo no puede ejecutar
     por su cuenta porque no puede inventar el token.

  2. Idempotencia. `idempotency_key` es UNIQUE en la base. Si el modelo
     reintenta la misma orden (porque se le cayo el stream, porque se confundio
     de turno), la segunda llamada devuelve el mismo folio con
     `duplicado: true` en lugar de comprar dos veces.

  3. Idoneidad. La asignacion se verifica contra el perfil GUARDADO del
     cliente antes de registrar la orden y otra vez antes de ejecutarla. Este
     era el hueco grande: el modelo podia armar cualquier asignacion y nadie
     la cruzaba contra el perfil. Se revisa dos veces a proposito, porque
     entre el paso 1 y el paso 2 pueden pasar minutos y el perfil pudo
     vencer.
"""

from __future__ import annotations

import hashlib
import math
import json
import secrets
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from bank import db
from bank.finance import idoneidad
from bank.finance import origen as origen_mod
from bank.instrumentos import BY_ID
from services.errors import NotFound, ReglaDeNegocio, ServiceError
from services.portfolio import _asignacion_desde_entrada

MONTO_MINIMO_ORDEN = 1_000.0
MONTO_MAXIMO_ORDEN = 50_000_000.0
TOLERANCIA_PESOS = 0.01
VIGENCIA_TOKEN_MINUTOS = 15

def _hash_token(token: str) -> str:
    """El token crudo (alta entropía, 144 bits) nunca se guarda en la base.
    Un hash simple basta; no es una contraseña de baja entropía sujeta a
    fuerza bruta, así que no hace falta salt/HMAC/costo adaptativo."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _ahora(conn) -> datetime:
    """Reloj del sistema simulado: anclado a la fecha de valuacion de la base."""
    row = db.query_one(conn, "SELECT fecha_valuacion FROM market_params WHERE id = 1")
    base = date.fromisoformat(row["fecha_valuacion"]) if row else date.today()
    return datetime.combine(base, datetime.now().time())


def _precio_actual(conn, instrument_id: str) -> float:
    row = db.query_one(
        conn,
        "SELECT valor_unitario FROM instrument_series WHERE instrument_id = ?"
        " ORDER BY fecha DESC LIMIT 1", (instrument_id,))
    if row is None:
        raise NotFound(f"No hay serie de precios para {instrument_id!r}.")
    return float(row["valor_unitario"])


def _siguiente_folio(conn, momento: datetime) -> str:
    n = db.query_one(conn, "SELECT COUNT(*) AS n FROM orders")["n"]
    return f"BN-{momento.year}-{100001 + int(n):06d}"


def _cuenta_de_inversion(conn, client_id: str, account_id: str | None) -> dict[str, Any]:
    if account_id:
        row = db.query_one(
            conn, "SELECT * FROM accounts WHERE account_id = ? AND client_id = ?",
            (account_id, client_id))
        if row is None:
            raise NotFound(
                f"La cuenta {account_id!r} no existe o no es de {client_id}.",
                sugerencia="Usa `get_accounts` para ver las cuentas del cliente.",
            )
        return row
    row = db.query_one(
        conn, "SELECT * FROM accounts WHERE client_id = ? AND tipo = 'inversion'"
              " ORDER BY saldo_disponible DESC LIMIT 1", (client_id,))
    if row is None:
        raise ReglaDeNegocio(
            f"{client_id} no tiene cuenta de inversión.",
            sugerencia="Hay que abrir una antes de poder comprar.",
        )
    return row


def _armar_legs(conn, pesos: dict[str, float], monto: float) -> list[dict[str, Any]]:
    total = sum(pesos.values())
    if abs(total - 1.0) > TOLERANCIA_PESOS:
        raise ServiceError(
            f"Los pesos de la asignación suman {total:.4f}, deben sumar 1.",
            sugerencia="Normaliza los pesos antes de mandar la orden.",
        )
    legs: list[dict[str, Any]] = []
    problemas: list[str] = []
    for iid, peso in sorted(pesos.items(), key=lambda kv: -kv[1]):
        peso_norm = peso / total
        monto_leg = round(monto * peso_norm, 2)
        inst = BY_ID[iid]
        if monto_leg < inst.monto_minimo:
            problemas.append(
                f"{inst.nombre}: le tocan ${monto_leg:,.2f} y el mínimo es "
                f"${inst.monto_minimo:,.2f}"
            )
            continue
        precio = _precio_actual(conn, iid)
        legs.append({
            "instrument_id": iid,
            "instrumento": inst.nombre,
            "clase": inst.clase,
            "peso": round(peso_norm, 6),
            "monto": monto_leg,
            "precio_unitario": round(precio, 6),
            "titulos": round(monto_leg / precio, 6),
            "liquidez": inst.liquidez,
            "plazo_dias": inst.plazo_dias,
        })
    if problemas:
        raise ReglaDeNegocio(
            "Hay instrumentos por debajo del monto mínimo: " + "; ".join(problemas) + ".",
            sugerencia="Sube el monto total o pide una propuesta con menos instrumentos "
                       "llamando `propose_allocation` con el monto real.",
        )
    if not legs:
        raise ReglaDeNegocio("La orden quedó sin instrumentos ejecutables.")
    return legs


def _orden_a_dict(conn, order_id: str) -> dict[str, Any]:
    orden = db.query_one(conn, "SELECT * FROM orders WHERE order_id = ?", (order_id,))
    legs = db.query(
        conn,
        "SELECT l.instrument_id, i.nombre AS instrumento, i.clase, l.peso, l.monto, l.titulos"
        "  FROM order_legs l JOIN instruments i USING (instrument_id)"
        " WHERE l.order_id = ? ORDER BY l.peso DESC", (order_id,))
    return {**orden, "legs": legs}


def _verificar_idoneidad(
    conn,
    client_id: str,
    pesos: dict[str, float],
    monto: float,
    cuenta: dict[str, Any],
    origen: str | None,
) -> dict[str, Any]:
    """Cruza la asignacion contra el perfil vigente. Revienta si no es apta.

    El perfil sale de la BASE, nunca de lo que diga el modelo. El horizonte
    tambien. El origen, si no se especifica, se deduce del tipo de la cuenta
    de cargo: cargar a una cuenta de nomina no es lo mismo que cargar a una
    de inversion.
    """
    perfil = db.query_one(
        conn,
        "SELECT perfil, score, horizonte_meses, vigente_hasta FROM risk_profiles"
        " WHERE client_id = ? ORDER BY respondido_en DESC LIMIT 1", (client_id,))
    if perfil is None:
        raise ReglaDeNegocio(
            f"{client_id} no tiene perfil de riesgo. No puedo ejecutar una orden "
            "sin saber si le corresponde.",
            sugerencia="Perfílalo con `get_risk_questions` y `score_risk_profile`.")

    hoy = _ahora(conn).date()
    if date.fromisoformat(perfil["vigente_hasta"]) < hoy:
        raise ReglaDeNegocio(
            f"El perfil de {client_id} venció el {perfil['vigente_hasta']}.",
            sugerencia="Vuelve a perfilar con `score_risk_profile` antes de operar.")

    if origen is None:
        origen = origen_mod.desde_cuenta(cuenta["tipo"]).clave

    try:
        return idoneidad.exigir(
            pesos, perfil["perfil"], perfil["horizonte_meses"] / 12,
            monto=monto, origen=origen)
    except idoneidad.IdoneidadInvalida as exc:
        raise ReglaDeNegocio(
            str(exc),
            sugerencia="Pide una asignación con `propose_allocation` pasando "
                       "`client_id`, o revisa el detalle con `check_suitability`.",
        ) from exc


# ---------------------------------------------------------------------------
def place_order(
    client_id: str,
    asignacion: Any,
    monto: float,
    idempotency_key: str,
    account_id: str | None = None,
    confirmation_token: str | None = None,
    origen: str | None = None,
) -> dict[str, Any]:
    """Registra o ejecuta una orden de inversion.

    Sin `confirmation_token`: valida todo, deja la orden `pendiente` y devuelve
    el token mas un resumen para que el usuario confirme en pantalla.
    Con `confirmation_token` valido: ejecuta, mueve el saldo y abre posiciones.

    Antes de cualquiera de las dos cosas corre el control de idoneidad
    (`bank/finance/idoneidad.py`) contra el perfil GUARDADO del cliente. Ese
    control no es opcional ni negociable desde el prompt: es la razon por la
    que el modelo no puede ejecutar una asignacion que no le corresponde al
    cliente, aunque se la haya inventado y aunque el usuario diga que si.
    """
    monto = float(monto)
    if not math.isfinite(monto):
        raise ServiceError("`monto` debe ser un número finito.")
    if not idempotency_key or not isinstance(idempotency_key, str):
        raise ServiceError(
            "`idempotency_key` es obligatorio y debe ser un string estable.",
            sugerencia="Usa algo derivado de la intención del usuario, por ejemplo "
                       "'<client_id>-<monto>-<turno>'.",
        )
    if not MONTO_MINIMO_ORDEN <= monto <= MONTO_MAXIMO_ORDEN:
        raise ServiceError(
            f"El monto debe estar entre ${MONTO_MINIMO_ORDEN:,.0f} y "
            f"${MONTO_MAXIMO_ORDEN:,.0f}; llegó ${monto:,.2f}."
        )

    pesos = _asignacion_desde_entrada(asignacion)

    with db.session() as conn:
        if db.query_one(conn, "SELECT 1 FROM clients WHERE client_id = ?",
                        (client_id,)) is None:
            raise NotFound(f"No existe el cliente {client_id!r}.")

        existente = db.query_one(
            conn, "SELECT * FROM orders WHERE idempotency_key = ? AND client_id = ?",
            (idempotency_key, client_id))

        # ------------------------------------------------ reintento idempotente
        if existente is not None:
            if existente["estado"] == "ejecutada":
                return {
                    **_orden_a_dict(conn, existente["order_id"]),
                    "duplicado": True,
                    "mensaje": f"Esta orden ya se había ejecutado. Folio {existente['folio']}.",
                    "requiere_confirmacion": False,
                }
            if existente["estado"] in ("rechazada", "cancelada"):
                return {
                    **_orden_a_dict(conn, existente["order_id"]),
                    "duplicado": True,
                    "requiere_confirmacion": False,
                }
            # pendiente
            if confirmation_token is None:
                return {
                    **_orden_a_dict(conn, existente["order_id"]),
                    "duplicado": True,
                    "requiere_confirmacion": True,
                    "mensaje": "Ya había una orden pendiente con esa clave; "
                               "sigue esperando confirmación. El token original ya se entregó "
                               "cuando se creó la orden; si se perdió, cancela y vuelve a "
                               "generar la orden con una nueva `idempotency_key`.",
                }
            if not secrets.compare_digest(
                _hash_token(confirmation_token), existente["confirmation_token_hash"]
            ):
                raise ReglaDeNegocio(
                    "El `confirmation_token` no corresponde a la orden pendiente.",
                    sugerencia="Vuelve a llamar `place_order` sin token para obtener uno nuevo.",
                )
            creada = datetime.fromisoformat(existente["creada_en"])
            if _ahora(conn) - creada > timedelta(minutes=VIGENCIA_TOKEN_MINUTOS):
                conn.execute(
                    "UPDATE orders SET estado='cancelada', motivo_rechazo=? WHERE order_id=?",
                    (f"token vencido tras {VIGENCIA_TOKEN_MINUTOS} min",
                     existente["order_id"]))
                raise ReglaDeNegocio(
                    "La confirmación venció. Hay que volver a generar la orden.",
                    sugerencia="Llama `place_order` sin token para empezar de nuevo.",
                )
            return _ejecutar(conn, existente["order_id"])

        # --------------------------------------------------- alta de orden nueva
        cuenta = _cuenta_de_inversion(conn, client_id, account_id)
        if cuenta["saldo_disponible"] + 1e-6 < monto:
            raise ReglaDeNegocio(
                f"Saldo insuficiente en {cuenta['account_id']}: hay "
                f"${cuenta['saldo_disponible']:,.2f} y la orden pide ${monto:,.2f}.",
                sugerencia="Baja el monto o elige otra cuenta con `get_accounts`.",
            )

        veredicto = _verificar_idoneidad(conn, client_id, pesos, monto,
                                         cuenta, origen)

        legs = _armar_legs(conn, pesos, monto)
        momento = _ahora(conn)
        order_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(18)
        folio = _siguiente_folio(conn, momento)

        try:
            conn.execute(
                "INSERT INTO orders (order_id, folio, client_id, account_id, estado, monto,"
                " creada_en, idempotency_key, confirmation_token_hash)"
                " VALUES (?,?,?,?,'pendiente',?,?,?,?)",
                (order_id, folio, client_id, cuenta["account_id"], monto,
                 momento.isoformat(), idempotency_key, _hash_token(token)))
        except sqlite3.IntegrityError as exc:        # carrera con otro turno
            raise ReglaDeNegocio(
                "Ya existe una orden con esa `idempotency_key` para este cliente.",
                sugerencia="Vuelve a llamar con la misma clave para recuperar su estado.",
            ) from exc

        conn.executemany(
            "INSERT INTO order_legs (order_id, instrument_id, peso, monto, titulos)"
            " VALUES (?,?,?,?,?)",
            [(order_id, l["instrument_id"], l["peso"], l["monto"], l["titulos"])
             for l in legs])

        return {
            "order_id": order_id,
            "folio": folio,
            "estado": "pendiente",
            "client_id": client_id,
            "account_id": cuenta["account_id"],
            "monto": round(monto, 2),
            "legs": legs,
            "saldo_antes": round(cuenta["saldo_disponible"], 2),
            "saldo_despues_estimado": round(cuenta["saldo_disponible"] - monto, 2),
            "idoneidad": veredicto,
            "requiere_confirmacion": True,
            "confirmation_token": token,
            "vence_en_minutos": VIGENCIA_TOKEN_MINUTOS,
            "mensaje": "Orden registrada sin ejecutar. Muestra el resumen al usuario y "
                       "vuelve a llamar `place_order` con el mismo `idempotency_key` y "
                       "este `confirmation_token` solo cuando el usuario confirme.",
            "disclaimer": "Operación simulada sobre datos sintéticos. No mueve dinero real.",
        }


def _ejecutar(conn, order_id: str) -> dict[str, Any]:
    orden = db.query_one(conn, "SELECT * FROM orders WHERE order_id = ?", (order_id,))

    # Reclamo atomico: si dos confirmaciones llegan casi al mismo tiempo, solo
    # una puede ganar este UPDATE (SQLite serializa escritores). La que pierde
    # ve rowcount == 0 y se detiene antes de tocar saldo o posiciones.
    cur = conn.execute(
        "UPDATE orders SET estado='ejecutando' WHERE order_id=? AND estado='pendiente'",
        (order_id,))
    if cur.rowcount == 0:
        raise ReglaDeNegocio(
            "La orden ya no está pendiente (fue ejecutada, rechazada o cancelada "
            "por otra solicitud).",
            sugerencia="Llama `get_orders` para ver el estado actual.",
        )

    legs = db.query(conn, "SELECT * FROM order_legs WHERE order_id = ?", (order_id,))
    cuenta = db.query_one(
        conn, "SELECT * FROM accounts WHERE account_id = ?", (orden["account_id"],))

    # Segunda pasada del control. Entre registrar y confirmar pudieron pasar
    # minutos: el perfil pudo vencer o alguien pudo reperfilar al cliente a
    # algo mas conservador. Se vuelve a verificar contra lo que dice la base
    # AHORA, no contra lo que decia cuando se armo la orden.
    try:
        _verificar_idoneidad(
            conn, orden["client_id"],
            {leg["instrument_id"]: leg["peso"] for leg in legs},
            orden["monto"], cuenta, None)
    except ReglaDeNegocio as exc:
        conn.execute(
            "UPDATE orders SET estado='rechazada', motivo_rechazo=? WHERE order_id=?",
            (f"idoneidad al ejecutar: {exc}"[:500], order_id))
        raise

    if cuenta["saldo_disponible"] + 1e-6 < orden["monto"]:
        conn.execute(
            "UPDATE orders SET estado='ejecutada', ejecutada_en=? "
            "WHERE order_id=? AND estado='ejecutando'",
            ("saldo insuficiente al momento de ejecutar", order_id))
        raise ReglaDeNegocio(
            f"Saldo insuficiente al ejecutar: hay ${cuenta['saldo_disponible']:,.2f} "
            f"y la orden pide ${orden['monto']:,.2f}.")

    momento = _ahora(conn)
    saldo_nuevo = round(cuenta["saldo_disponible"] - orden["monto"], 2)
    conn.execute(
        "UPDATE accounts SET saldo_disponible = ?, saldo_liquidado = ? WHERE account_id = ?",
        (saldo_nuevo, saldo_nuevo, cuenta["account_id"]))
    conn.execute(
        "INSERT INTO transactions (txn_id, account_id, fecha, tipo, monto, categoria,"
        " descripcion, comercio, saldo_posterior) VALUES (?,?,?,'cargo',?,?,?,?,?)",
        (f"TXN-{uuid.uuid4().hex[:10]}", cuenta["account_id"], momento.isoformat(),
         orden["monto"], "inversion", f"Compra de portafolio · folio {orden['folio']}",
         None, saldo_nuevo))

    posiciones = []
    for leg in legs:
        existente = db.query_one(
            conn, "SELECT * FROM positions WHERE account_id = ? AND instrument_id = ?",
            (cuenta["account_id"], leg["instrument_id"]))
        precio = leg["monto"] / leg["titulos"] if leg["titulos"] else _precio_actual(
            conn, leg["instrument_id"])
        if existente:
            titulos = existente["titulos"] + leg["titulos"]
            costo = ((existente["titulos"] * existente["costo_promedio"]) + leg["monto"]) / titulos
            conn.execute(
                "UPDATE positions SET titulos = ?, costo_promedio = ? WHERE position_id = ?",
                (round(titulos, 6), round(costo, 6), existente["position_id"]))
            position_id = existente["position_id"]
        else:
            position_id = f"POS-{uuid.uuid4().hex[:10]}"
            conn.execute(
                "INSERT INTO positions (position_id, client_id, account_id, instrument_id,"
                " titulos, costo_promedio, abierta_en) VALUES (?,?,?,?,?,?,?)",
                (position_id, orden["client_id"], cuenta["account_id"], leg["instrument_id"],
                 round(leg["titulos"], 6), round(precio, 6), momento.date().isoformat()))
            titulos = leg["titulos"]
        posiciones.append({
            "position_id": position_id,
            "instrument_id": leg["instrument_id"],
            "titulos": round(titulos, 6),
            "monto_aplicado": leg["monto"],
        })

    conn.execute(
        "UPDATE orders SET estado='ejecutada', ejecutada_en=? WHERE order_id=?",
        (momento.isoformat(), order_id))

    return {
        **_orden_a_dict(conn, order_id),
        "requiere_confirmacion": False,
        "duplicado": False,
        "saldo_despues": saldo_nuevo,
        "posiciones": posiciones,
        "mensaje": f"Orden ejecutada. Folio {orden['folio']}.",
        "disclaimer": "Operación simulada sobre datos sintéticos. No movió dinero real.",
    }


def get_orders(client_id: str, estado: str | None = None, limite: int = 20) -> dict[str, Any]:
    """Historial de ordenes, la mas reciente primero."""
    estados = ("pendiente", "ejecutada", "rechazada", "cancelada")
    if estado is not None and estado not in estados:
        raise ServiceError(f"estado inválido: {estado!r}.",
                           sugerencia=f"Opciones: {', '.join(estados)}.")
    if not 1 <= limite <= 100:
        raise ServiceError("`limite` debe estar entre 1 y 100.")

    with db.session(readonly=True) as conn:
        if db.query_one(conn, "SELECT 1 FROM clients WHERE client_id = ?",
                        (client_id,)) is None:
            raise NotFound(f"No existe el cliente {client_id!r}.")
        sql = "SELECT * FROM orders WHERE client_id = ?"
        params: list[Any] = [client_id]
        if estado:
            sql += " AND estado = ?"
            params.append(estado)
        sql += " ORDER BY creada_en DESC LIMIT ?"
        params.append(limite)
        ordenes = db.query(conn, sql, tuple(params))
        for o in ordenes:
            o.pop("confirmation_token", None)        # no sale de la capa de servicio
            o["legs"] = db.query(
                conn,
                "SELECT l.instrument_id, i.nombre AS instrumento, l.peso, l.monto, l.titulos"
                "  FROM order_legs l JOIN instruments i USING (instrument_id)"
                " WHERE l.order_id = ? ORDER BY l.peso DESC", (o["order_id"],))

    return {"client_id": client_id, "total": len(ordenes), "ordenes": ordenes}


def registrar_superficie(
    session_id: str, turn: int, surface_id: str,
    messages: list[dict[str, Any]], tools: list[dict[str, Any]],
) -> None:
    """Bitacora del blueprint (§07). Cada superficie emitida queda reconstruible."""
    with db.session() as conn:
        conn.execute(
            "INSERT INTO surface_log (session_id, turn, surface_id, messages_json,"
            " tools_json, created_at) VALUES (?,?,?,?,?,?)",
            (session_id, turn, surface_id,
             json.dumps(messages, ensure_ascii=False),
             json.dumps(tools, ensure_ascii=False),
             _ahora(conn).isoformat()))
