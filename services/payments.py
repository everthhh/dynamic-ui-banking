"""Lectura del dominio de pagos: convenios, recibos, contactos, historiales y
cómo meter o sacar efectivo.

Todo lo que mueve dinero vive en `services/movements.py`, con el mismo split
que ya existe entre `services/accounts.py` (lectura) y `services/banking.py`
(efecto). Aquí nada escribe.

Dos reglas de exposición, pensadas para un demo que se proyecta:
  * CLABEs, tarjetas y referencias de servicio salen enmascaradas
    ('•••• 1234'). La única CLABE completa que sale es la del propio cliente,
    en `get_deposit_options`, porque es justo la que tiene que compartir para
    que le depositen.
  * Ni el hash del `confirmation_token` ni el del código de retiro salen de la
    base: `pago_publico` es la única forma de convertir una fila en respuesta.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from bank import db, pagos
from services.accounts import _exigir_cliente, _fecha_valuacion
from services.errors import ServiceError
from services.orders import _ahora

TIPOS_PAGO = ("servicio", "transferencia", "retiro_sin_tarjeta")
ESTADOS_PAGO = ("pendiente", "ejecutada", "rechazada", "cancelada")
CANALES_INGRESO = ("nomina", "honorarios", "spei", "interna", "deposito_efectivo",
                   "traspaso_propio", "reembolso", "otro")
# Lo que entra pero no es dinero nuevo: viene de otra cuenta del mismo cliente.
CANALES_SIN_DINERO_NUEVO = frozenset({"traspaso_propio", "reembolso"})


def _validar_ventana(meses: int, limite: int, limite_maximo: int = 200) -> None:
    if not 1 <= meses <= 18:
        raise ServiceError("`meses` debe estar entre 1 y 18.",
                           sugerencia="La base simulada tiene 18 meses de historia.")
    if not 1 <= limite <= limite_maximo:
        raise ServiceError(f"`limite` debe estar entre 1 y {limite_maximo}.")


# ---------------------------------------------------------------- convertidores
def convenio_publico(conv: pagos.Convenio) -> dict[str, Any]:
    return {
        "biller_id": conv.biller_id,
        "nombre": conv.nombre,
        "categoria": conv.categoria,
        "referencia_etiqueta": conv.referencia_etiqueta,
        "referencia_regex": conv.referencia_regex,
        "fuente_formato": conv.fuente_formato,
        "cobertura": list(conv.cobertura) or ["nacional"],
        "periodicidad": conv.periodicidad,
        "comision": conv.comision,
        "descripcion": conv.descripcion,
    }


def servicio_publico(conn, row: dict[str, Any], hoy: date) -> dict[str, Any]:
    """Un servicio guardado con su recibo pendiente (si hay) y su último pago."""
    conv = pagos.CONVENIO_POR_ID[row["biller_id"]]
    recibo_row = db.query_one(
        conn, "SELECT * FROM bills WHERE service_id = ? AND estado = 'pendiente'"
              " ORDER BY fecha_limite LIMIT 1", (row["service_id"],))
    ultimo = db.query_one(
        conn, "SELECT folio, monto, ejecutada_en FROM payments"
              " WHERE service_id = ? AND estado = 'ejecutada'"
              " ORDER BY ejecutada_en DESC LIMIT 1", (row["service_id"],))
    recibo = None
    if recibo_row is not None:
        dias = (date.fromisoformat(recibo_row["fecha_limite"]) - hoy).days
        recibo = {
            "bill_id": recibo_row["bill_id"],
            "periodo": recibo_row["periodo"],
            "monto": recibo_row["monto"],
            "comision": conv.comision,
            "total": round(recibo_row["monto"] + conv.comision, 2),
            "fecha_emision": recibo_row["fecha_emision"],
            "fecha_limite": recibo_row["fecha_limite"],
            "dias_para_vencer": dias,
            "vencido": dias < 0,
        }
    return {
        "service_id": row["service_id"],
        "biller_id": row["biller_id"],
        "convenio": conv.nombre,
        "categoria": conv.categoria,
        "alias": row["alias"],
        "nombre": row["alias"] or conv.nombre,
        "referencia_mask": pagos.enmascarar(row["referencia"]),
        "referencia_etiqueta": conv.referencia_etiqueta,
        "recibo": recibo,
        "ultimo_pago": ultimo,
    }


def beneficiario_publico(row: dict[str, Any], ahora: datetime) -> dict[str, Any]:
    creado = datetime.fromisoformat(row["creado_en"])
    sin_tope_desde = creado + timedelta(minutes=pagos.ESPERA_DESTINO_NUEVO_MIN)
    nuevo = ahora < sin_tope_desde
    return {
        "beneficiary_id": row["beneficiary_id"],
        "alias": row["alias"],
        "titular": row["titular"],
        "tipo_destino": row["tipo_destino"],
        "numero_mask": pagos.enmascarar(row["numero"]),
        "banco_codigo": row["banco_codigo"],
        "banco": pagos.BANCOS.get(row["banco_codigo"], row["banco_codigo"]),
        "mismo_banco": row["banco_codigo"] == pagos.BANCO_PROPIO,
        "creado_en": row["creado_en"],
        "destino_nuevo": nuevo,
        "tope_por_operacion": pagos.TOPE_DESTINO_NUEVO if nuevo else None,
        "sin_tope_desde": sin_tope_desde.isoformat(),
    }


def pago_publico(conn, row: dict[str, Any]) -> dict[str, Any]:
    """Una operación como la ve el cliente. Nunca incluye hashes."""
    salida: dict[str, Any] = {
        k: row[k] for k in (
            "payment_id", "folio", "client_id", "account_id", "tipo", "estado", "monto",
            "comision", "concepto", "clave_rastreo", "creada_en", "ejecutada_en",
            "motivo_rechazo", "idempotency_key")
    }
    salida["total"] = round(row["monto"] + row["comision"], 2)
    salida["fecha"] = row["ejecutada_en"] or row["creada_en"]

    if row["tipo"] == "servicio":
        servicio = db.query_one(
            conn, "SELECT * FROM saved_services WHERE service_id = ?", (row["service_id"],))
        conv = pagos.CONVENIO_POR_ID[servicio["biller_id"]]
        recibo = db.query_one(
            conn, "SELECT periodo, fecha_limite FROM bills WHERE bill_id = ?",
            (row["bill_id"],)) if row["bill_id"] else None
        salida["destino"] = {
            "tipo": "servicio",
            "nombre": servicio["alias"] or conv.nombre,
            "convenio": conv.nombre,
            "categoria": conv.categoria,
            "referencia_mask": pagos.enmascarar(servicio["referencia"]),
            "periodo": recibo["periodo"] if recibo else None,
            "fecha_limite": recibo["fecha_limite"] if recibo else None,
        }
    elif row["tipo"] == "transferencia":
        banco = row["destino_banco"]
        salida["destino"] = {
            "tipo": row["destino_tipo"],
            "nombre": row["destino_titular"],
            "banco": pagos.BANCOS.get(banco, banco),
            "numero_mask": pagos.enmascarar(row["destino_numero"]),
            "cuenta_propia": row["destino_tipo"] == "cuenta_propia",
            "beneficiary_id": row["beneficiary_id"],
        }
    else:
        salida["destino"] = {
            "tipo": "retiro_sin_tarjeta",
            "nombre": "Retiro sin tarjeta",
            "canal": pagos.CANAL_POR_ID["CAJERO"].nombre,
            "codigo_vence_en": row["codigo_vence_en"],
        }
    return salida


def referencia_publica(row: dict[str, Any]) -> dict[str, Any]:
    canal = pagos.CANAL_POR_ID[row["canal_id"]]
    return {
        "reference_id": row["reference_id"],
        "referencia": row["referencia"],
        "canal_id": row["canal_id"],
        "canal": canal.nombre,
        "como": canal.como,
        "account_id": row["account_id"],
        "comision": row["comision"],
        "monto_maximo": row["monto_maximo"],
        "estado": row["estado"],
        "creada_en": row["creada_en"],
        "vence_en": row["vence_en"],
        "liquidada_en": row["liquidada_en"],
        "monto_liquidado": row["monto_liquidado"],
    }


# ------------------------------------------------------------------- servicios
def get_billers(categoria: str | None = None, client_id: str | None = None) -> dict[str, Any]:
    """Convenios con los que se puede pagar.

    Con `client_id`, el agua se filtra a la ciudad del cliente (su organismo
    operador) y cada convenio dice si ya lo tiene registrado.
    """
    if categoria is not None and categoria not in pagos.CATEGORIAS_SERVICIO:
        raise ServiceError(
            f"{categoria!r} no es una categoría de servicio.",
            sugerencia=f"Categorías: {', '.join(pagos.CATEGORIAS_SERVICIO)}.")
    ciudad = None
    registrados: set[str] = set()
    if client_id is not None:
        with db.session(readonly=True) as conn:
            ciudad = _exigir_cliente(conn, client_id)["ciudad"]
            registrados = {r["biller_id"] for r in db.query(
                conn, "SELECT biller_id FROM saved_services WHERE client_id = ?", (client_id,))}

    convenios = []
    for conv in pagos.CONVENIOS:
        if categoria is not None and conv.categoria != categoria:
            continue
        if client_id is not None and not pagos.cubre(conv, ciudad):
            continue
        fila = convenio_publico(conv)
        if client_id is not None:
            fila["ya_registrado"] = conv.biller_id in registrados
        convenios.append(fila)
    return {
        "categoria": categoria,
        "ciudad": ciudad,
        "total": len(convenios),
        "convenios": convenios,
        "nota": "Formatos `publico` salen de los recibos reales; `simulado` son longitudes "
                "plausibles. Para pagar el agua de otra ciudad, llama sin `client_id`.",
    }


def get_bills(client_id: str) -> dict[str, Any]:
    """Servicios guardados del cliente con su recibo pendiente, lo vencido primero."""
    with db.session(readonly=True) as conn:
        _exigir_cliente(conn, client_id)
        hoy = _fecha_valuacion(conn)
        filas = db.query(
            conn, "SELECT * FROM saved_services WHERE client_id = ? ORDER BY creado_en",
            (client_id,))
        servicios = [servicio_publico(conn, f, hoy) for f in filas]

    def orden(s: dict[str, Any]) -> tuple:
        recibo = s["recibo"]
        return (recibo is None, recibo["fecha_limite"] if recibo else "", s["nombre"])

    servicios.sort(key=orden)
    pendientes = [s for s in servicios if s["recibo"]]
    vigentes = [s for s in pendientes if not s["recibo"]["vencido"]]
    return {
        "client_id": client_id,
        "fecha": hoy.isoformat(),
        "servicios": servicios,
        "recibos_pendientes": len(pendientes),
        "vencidos": sum(1 for s in pendientes if s["recibo"]["vencido"]),
        "total_por_pagar": round(sum(s["recibo"]["total"] for s in pendientes), 2),
        "proximo_vencimiento": (
            {"service_id": vigentes[0]["service_id"], "nombre": vigentes[0]["nombre"],
             "fecha_limite": vigentes[0]["recibo"]["fecha_limite"],
             "total": vigentes[0]["recibo"]["total"]} if vigentes else None),
    }


# --------------------------------------------------------------- transferencias
def get_beneficiaries(client_id: str) -> dict[str, Any]:
    """Contactos guardados para transferir, con su número enmascarado."""
    with db.session(readonly=True) as conn:
        _exigir_cliente(conn, client_id)
        ahora = _ahora(conn)
        filas = db.query(
            conn, "SELECT * FROM beneficiaries WHERE client_id = ? ORDER BY alias", (client_id,))
    return {
        "client_id": client_id,
        "beneficiarios": [beneficiario_publico(f, ahora) for f in filas],
        "tope_destino_nuevo": pagos.TOPE_DESTINO_NUEVO,
        "espera_destino_nuevo_min": pagos.ESPERA_DESTINO_NUEVO_MIN,
    }


# ------------------------------------------------------------------ historiales
def get_payment_history(
    client_id: str,
    tipo: str | None = None,
    estado: str | None = None,
    meses: int = 3,
    limite: int = 50,
) -> dict[str, Any]:
    """Pagos de servicios, transferencias y retiros, lo más reciente primero.

    Sin `estado`, no incluye operaciones pendientes: una operación que nadie
    confirmó todavía no es historia.
    """
    if tipo is not None and tipo not in TIPOS_PAGO:
        raise ServiceError(f"tipo inválido: {tipo!r}.", sugerencia=f"Opciones: {', '.join(TIPOS_PAGO)}.")
    if estado is not None and estado not in ESTADOS_PAGO:
        raise ServiceError(f"estado inválido: {estado!r}.",
                           sugerencia=f"Opciones: {', '.join(ESTADOS_PAGO)}.")
    _validar_ventana(meses, limite)

    with db.session(readonly=True) as conn:
        _exigir_cliente(conn, client_id)
        desde = (_fecha_valuacion(conn) - timedelta(days=31 * meses)).isoformat()
        sql = "SELECT * FROM payments WHERE client_id = ? AND creada_en >= ?"
        params: list[Any] = [client_id, desde]
        if tipo is not None:
            sql += " AND tipo = ?"
            params.append(tipo)
        if estado is not None:
            sql += " AND estado = ?"
            params.append(estado)
        else:
            sql += " AND estado NOT IN ('pendiente', 'ejecutando')"
        sql += " ORDER BY COALESCE(ejecutada_en, creada_en) DESC LIMIT ?"
        params.append(limite)
        filas = db.query(conn, sql, tuple(params))
        operaciones = [pago_publico(conn, f) for f in filas]
        totales = db.query(
            conn, "SELECT tipo, COUNT(*) AS n, SUM(monto + comision) AS total FROM payments"
                  " WHERE client_id = ? AND creada_en >= ? AND estado = 'ejecutada'"
                  " GROUP BY tipo", (client_id, desde))

    por_tipo = [{"tipo": t["tipo"], "operaciones": t["n"], "total": round(t["total"], 2)}
                for t in totales]
    return {
        "client_id": client_id,
        "desde": desde,
        "filtros": {"tipo": tipo, "estado": estado},
        "pagos": operaciones,
        "total": len(operaciones),
        "total_pagado": round(sum(t["total"] for t in por_tipo), 2),
        "por_tipo": sorted(por_tipo, key=lambda t: -t["total"]),
    }


def _canal_de(fila: dict[str, Any]) -> str:
    if fila["canal"]:
        return fila["canal"]
    return {"nomina": "nomina", "traspaso": "traspaso_propio",
            "efectivo": "reembolso"}.get(fila["categoria"], "otro")


def get_received_money(
    client_id: str,
    canal: str | None = None,
    meses: int = 3,
    limite: int = 50,
) -> dict[str, Any]:
    """Todo el dinero que entró: nómina, SPEI, transferencias del mismo banco,
    depósitos en efectivo y traspasos entre cuentas propias.

    `por_canal` se calcula sobre la ventana completa aunque se filtre un canal,
    para que la pantalla pueda mostrar los totales de todos los chips.
    """
    if canal is not None and canal not in CANALES_INGRESO:
        raise ServiceError(f"canal inválido: {canal!r}.",
                           sugerencia=f"Opciones: {', '.join(CANALES_INGRESO)}.")
    _validar_ventana(meses, limite)

    with db.session(readonly=True) as conn:
        _exigir_cliente(conn, client_id)
        desde = (_fecha_valuacion(conn) - timedelta(days=31 * meses)).isoformat()
        filas = db.query(
            conn,
            "SELECT t.txn_id, t.account_id, t.fecha, t.monto, t.categoria, t.descripcion,"
            "       t.comercio, i.canal, i.remitente, i.banco_origen, i.cuenta_origen_mask,"
            "       i.concepto, i.clave_rastreo"
            "  FROM transactions t JOIN accounts a USING (account_id)"
            "  LEFT JOIN incoming_transfers i USING (txn_id)"
            " WHERE a.client_id = ? AND t.tipo = 'abono' AND t.fecha >= ?"
            " ORDER BY t.fecha DESC", (client_id, desde))

    por_canal: dict[str, dict[str, Any]] = {}
    movimientos: list[dict[str, Any]] = []
    for f in filas:
        c = _canal_de(f)
        agregado = por_canal.setdefault(c, {"canal": c, "total": 0.0, "movimientos": 0})
        agregado["total"] += f["monto"]
        agregado["movimientos"] += 1
        if (canal is not None and c != canal) or len(movimientos) >= limite:
            continue
        movimientos.append({
            "txn_id": f["txn_id"],
            "account_id": f["account_id"],
            "fecha": f["fecha"],
            "monto": f["monto"],
            "canal": c,
            "remitente": f["remitente"] or f["comercio"] or f["descripcion"],
            "banco_origen": (pagos.BANCOS.get(f["banco_origen"], f["banco_origen"])
                             if f["banco_origen"] else None),
            "cuenta_origen_mask": f["cuenta_origen_mask"],
            "concepto": f["concepto"] or f["descripcion"],
            "clave_rastreo": f["clave_rastreo"],
        })

    resumen = sorted(({**v, "total": round(v["total"], 2)} for v in por_canal.values()),
                     key=lambda v: -v["total"])
    return {
        "client_id": client_id,
        "desde": desde,
        "canal": canal,
        "movimientos": movimientos,
        "total": len(movimientos),
        "total_recibido": round(sum(v["total"] for v in resumen
                                    if v["canal"] not in CANALES_SIN_DINERO_NUEVO), 2),
        "por_canal": resumen,
        "nota": "`total_recibido` no cuenta traspasos entre cuentas propias ni reembolsos: "
                "no es dinero nuevo.",
    }


# ------------------------------------------------------------- meter y sacar
def get_deposit_options(client_id: str) -> dict[str, Any]:
    """Cómo le entra y le sale dinero al cliente.

    Los datos para recibir un SPEI (CLABE completa, banco y titular), los
    corresponsales donde depositar efectivo con su comisión, las reglas del
    retiro sin tarjeta y las referencias de depósito que siguen vigentes.
    """
    with db.session(readonly=True) as conn:
        cliente = _exigir_cliente(conn, client_id)
        cuentas = db.query(
            conn, "SELECT account_id, tipo, alias, clabe_mock, saldo_disponible FROM accounts"
                  " WHERE client_id = ? ORDER BY tipo", (client_id,))
        referencias = db.query(
            conn, "SELECT * FROM deposit_references WHERE client_id = ? AND estado = 'vigente'"
                  " ORDER BY creada_en DESC", (client_id,))
    return {
        "client_id": client_id,
        "cuentas": [
            {
                "account_id": c["account_id"],
                "tipo": c["tipo"],
                "alias": c["alias"],
                "clabe": c["clabe_mock"],
                "banco": pagos.BANCOS[pagos.BANCO_PROPIO],
                "titular": cliente["nombre"],
                "saldo_disponible": c["saldo_disponible"],
                "transaccional": c["tipo"] in pagos.TIPOS_CUENTA_TRANSACCIONAL,
            }
            for c in cuentas
        ],
        "canales_efectivo": [c._asdict() for c in pagos.CANALES_EFECTIVO],
        "retiro_sin_tarjeta": {
            "monto_minimo": pagos.MONTO_MINIMO_RETIRO,
            "monto_maximo": pagos.TOPE_RETIRO_SIN_TARJETA,
            "multiplo": pagos.MULTIPLO_RETIRO,
            "vigencia_horas": pagos.VIGENCIA_CODIGO_RETIRO_HORAS,
            "canal": pagos.CANAL_POR_ID["CAJERO"].nombre,
            "comision": 0.0,
        },
        "referencias_vigentes": [referencia_publica(r) for r in referencias],
        "nota": "Las comisiones de los corresponsales son estimadas y las cobra la tienda, "
                "no el banco.",
    }
