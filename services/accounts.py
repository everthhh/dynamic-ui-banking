"""Servicios de lectura del core bancario."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from bank import db
from bank.categorias import (
    CATEGORIAS_ESENCIALES,
    CATEGORIAS_GASTO,
    CATEGORIAS_NO_GASTO,
    COSTO_FINANCIERO,
    PAGO_CREDITO,
)
from bank.finance.risk import perfil_de_score
from services.errors import NotFound, ServiceError

__all__ = ["CATEGORIAS_ESENCIALES", "CATEGORIAS_GASTO", "CATEGORIAS_NO_GASTO"]


def _fecha_valuacion(conn) -> date:
    row = db.query_one(conn, "SELECT fecha_valuacion FROM market_params WHERE id = 1")
    return date.fromisoformat(row["fecha_valuacion"]) if row else date.today()


def _exigir_cliente(conn, client_id: str) -> dict[str, Any]:
    row = db.query_one(conn, "SELECT * FROM clients WHERE client_id = ?", (client_id,))
    if row is None:
        validos = [r["client_id"] for r in db.query(
            conn, "SELECT client_id FROM clients ORDER BY client_id")]
        raise NotFound(
            f"No existe el cliente {client_id!r}.",
            sugerencia=f"Clientes disponibles: {', '.join(validos)}.",
        )
    return row


def _exigir_cuenta_del_cliente(conn, client_id: str, account_id: str) -> dict[str, Any]:
    """Ownership check: una cuenta solo se toca si es del cliente en sesión.

    El mensaje NO dice qué cuentas sí existen (a diferencia de
    `_exigir_cliente`, donde enumerar client_ids es información pública del
    demo): una cuenta o tarjeta ajena no debe ni confirmarse que existe.
    """
    row = db.query_one(
        conn, "SELECT * FROM accounts WHERE account_id = ? AND client_id = ?",
        (account_id, client_id))
    if row is None:
        raise NotFound(
            f"La cuenta {account_id!r} no existe o no pertenece a {client_id}.",
            sugerencia="Usa `get_accounts` para ver las cuentas de este cliente.",
        )
    return row


def _resumen_credito(conn, client_id: str, ingreso: float) -> dict[str, Any]:
    """Version compacta del panorama de credito, para embutir en el snapshot."""
    prestamos = db.query(
        conn, "SELECT producto, saldo_insoluto, pago_mensual, tasa_anual,"
              " plazo_meses, mensualidades_pagadas FROM loans WHERE client_id = ?",
        (client_id,))
    tarjetas = db.query(
        conn, "SELECT limite_credito, saldo_utilizado FROM cards"
              " WHERE client_id = ? AND tipo = 'credito'", (client_id,))
    pago = sum(p["pago_mensual"] for p in prestamos)
    limite = sum(t["limite_credito"] or 0 for t in tarjetas)
    utilizado = sum(t["saldo_utilizado"] for t in tarjetas)
    return {
        "prestamos": prestamos,
        "deuda_total": round(sum(p["saldo_insoluto"] for p in prestamos) + utilizado, 2),
        "pago_mensual_total": round(pago, 2),
        "uso_linea_revolvente": round(utilizado / limite, 4) if limite else 0.0,
        "carga_sobre_ingreso": round(pago / ingreso, 4) if ingreso else 0.0,
    }


def get_client_snapshot(client_id: str) -> dict[str, Any]:
    """Foto completa del cliente: quien es, cuanto tiene, que perfil trae.

    Es la primera tool de casi cualquier conversacion. Incluye explicitamente
    `perfil_vigente: false` cuando no hay perfil usable, que es la senal que
    hace que el agente genere el perfilador en vez de proponer a ciegas.
    """
    with db.session(readonly=True) as conn:
        cliente = _exigir_cliente(conn, client_id)
        hoy = _fecha_valuacion(conn)

        cuentas = db.query(
            conn,
            "SELECT account_id, tipo, moneda, saldo_disponible, abierta_en"
            " FROM accounts WHERE client_id = ? ORDER BY tipo", (client_id,))

        perfil_row = db.query_one(
            conn,
            "SELECT * FROM risk_profiles WHERE client_id = ?"
            " ORDER BY respondido_en DESC LIMIT 1", (client_id,))
        perfil: dict[str, Any] | None = None
        if perfil_row:
            vigente = date.fromisoformat(perfil_row["vigente_hasta"]) >= hoy
            nombre, descripcion = perfil_de_score(perfil_row["score"])
            perfil = {
                "score": perfil_row["score"],
                "perfil": nombre,
                "descripcion": descripcion,
                "horizonte_meses": perfil_row["horizonte_meses"],
                "respondido_en": perfil_row["respondido_en"],
                "vigente_hasta": perfil_row["vigente_hasta"],
                "vigente": vigente,
            }

        posiciones = db.query(
            conn,
            "SELECT p.instrument_id, i.nombre, i.clase, i.riesgo_1a5, p.titulos,"
            "       p.costo_promedio, p.abierta_en,"
            "       (SELECT valor_unitario FROM instrument_series s"
            "         WHERE s.instrument_id = p.instrument_id"
            "         ORDER BY s.fecha DESC LIMIT 1) AS valor_actual"
            "  FROM positions p JOIN instruments i USING (instrument_id)"
            " WHERE p.client_id = ?", (client_id,))

        total_invertido = 0.0
        total_mercado = 0.0
        detalle = []
        for p in posiciones:
            # Se redondea PRIMERO y se resta después. Al revés, las tres cifras
            # que van juntas en pantalla pueden no cuadrar por un centavo, y un
            # centavo que no cuadra en un estado de cuenta se nota.
            costo = round(p["titulos"] * p["costo_promedio"], 2)
            mercado = round(p["titulos"] * p["valor_actual"], 2)
            total_invertido += costo
            total_mercado += mercado
            detalle.append({
                "instrument_id": p["instrument_id"],
                "instrumento": p["nombre"],
                "clase": p["clase"],
                "riesgo_1a5": p["riesgo_1a5"],
                "titulos": round(p["titulos"], 6),
                "costo_total": costo,
                "valor_mercado": mercado,
                "rendimiento": round(mercado - costo, 2),
                "rendimiento_pct": round((mercado / costo - 1) if costo else 0.0, 6),
                "abierta_en": p["abierta_en"],
            })
        detalle.sort(key=lambda d: -d["valor_mercado"])

        efectivo = round(sum(c["saldo_disponible"] for c in cuentas), 2)
        total_invertido = round(total_invertido, 2)
        total_mercado = round(total_mercado, 2)
        credito = _resumen_credito(conn, client_id, cliente["ingreso_mensual"])

        return {
            "client_id": client_id,
            "nombre": cliente["nombre"],
            "segmento": cliente["segmento"],
            "ciudad": cliente["ciudad"],
            "cliente_desde": cliente["fecha_alta"],
            "ingreso_mensual": cliente["ingreso_mensual"],
            "horizonte_declarado_meses": cliente["horizonte_meses"],
            "fecha_valuacion": hoy.isoformat(),
            "cuentas": cuentas,
            "efectivo_total": efectivo,
            "perfil_riesgo": perfil,
            "perfil_vigente": bool(perfil and perfil["vigente"]),
            "posiciones": detalle,
            "inversion": {
                "costo_total": total_invertido,
                "valor_mercado": total_mercado,
                "rendimiento": round(total_mercado - total_invertido, 2),
            },
            "patrimonio_total": round(efectivo + total_mercado, 2),
            "credito": credito,
        }


def get_accounts(client_id: str) -> dict[str, Any]:
    """Cuentas del cliente con saldos."""
    with db.session(readonly=True) as conn:
        _exigir_cliente(conn, client_id)
        cuentas = db.query(
            conn, "SELECT * FROM accounts WHERE client_id = ? ORDER BY tipo", (client_id,))
        tarjetas = db.query(
            conn, "SELECT card_id, tipo, alias, last4, estado, limite_credito, saldo_utilizado,"
                  " dia_corte, dia_pago FROM cards WHERE client_id = ?", (client_id,))
    return {
        "client_id": client_id,
        "cuentas": cuentas,
        "tarjetas": tarjetas,
        "efectivo_total": round(sum(c["saldo_disponible"] for c in cuentas), 2),
    }


def get_transactions(
    client_id: str,
    meses: int = 3,
    categoria: str | None = None,
    limite: int = 50,
) -> dict[str, Any]:
    """Movimientos recientes, el mas nuevo primero."""
    if not 1 <= meses <= 18:
        raise ServiceError("`meses` debe estar entre 1 y 18.",
                           sugerencia="La base simulada tiene 18 meses de historia.")
    if not 1 <= limite <= 300:
        raise ServiceError("`limite` debe estar entre 1 y 300.")

    with db.session(readonly=True) as conn:
        _exigir_cliente(conn, client_id)
        desde = (_fecha_valuacion(conn) - timedelta(days=31 * meses)).isoformat()
        sql = (
            "SELECT t.* FROM transactions t JOIN accounts a USING (account_id)"
            " WHERE a.client_id = ? AND t.fecha >= ?"
        )
        params: list[Any] = [client_id, desde]
        if categoria:
            sql += " AND t.categoria = ?"
            params.append(categoria)
        sql += " ORDER BY t.fecha DESC LIMIT ?"
        params.append(limite)
        filas = db.query(conn, sql, tuple(params))
    return {
        "client_id": client_id,
        "desde": desde,
        "categoria": categoria,
        "movimientos": filas,
        "total": len(filas),
    }


def get_spending_summary(client_id: str, meses: int = 6) -> dict[str, Any]:
    """Gasto por categoria y capacidad de ahorro estimada.

    `capacidad_ahorro_mensual` es lo que alimenta la sugerencia de aportacion
    mensual en el simulador: ingreso menos consumo, menos mensualidades de
    credito, menos intereses y comisiones, con piso en cero. Antes restaba solo
    el consumo, y un cliente con un auto financiado al 48% de su sueldo salia
    con capacidad de ahorro de sobra.

    Las compras con tarjeta de credito cuentan como consumo (viven en el mismo
    libro con `card_id`); el pago de la tarjeta no, porque paga compras que ya
    se contaron.
    """
    if not 1 <= meses <= 18:
        raise ServiceError("`meses` debe estar entre 1 y 18.")

    with db.session(readonly=True) as conn:
        cliente = _exigir_cliente(conn, client_id)
        desde = (_fecha_valuacion(conn) - timedelta(days=31 * meses)).isoformat()
        filas = db.query(
            conn,
            "SELECT t.categoria, t.tipo, SUM(t.monto) total, COUNT(*) n"
            "  FROM transactions t JOIN accounts a USING (account_id)"
            " WHERE a.client_id = ? AND t.fecha >= ?"
            " GROUP BY t.categoria, t.tipo", (client_id, desde))

    gasto: dict[str, dict[str, Any]] = {}
    ingreso_observado = 0.0
    pagos_credito = 0.0
    costo_financiero = 0.0
    for f in filas:
        if f["tipo"] == "abono":
            ingreso_observado += f["total"]
            continue
        if f["categoria"] == PAGO_CREDITO:
            pagos_credito += f["total"]
        elif f["categoria"] == COSTO_FINANCIERO:
            costo_financiero += f["total"]
        if f["categoria"] in CATEGORIAS_NO_GASTO:
            continue
        gasto[f["categoria"]] = {
            "categoria": f["categoria"],
            "total": round(f["total"], 2),
            "promedio_mensual": round(f["total"] / meses, 2),
            "movimientos": f["n"],
            "esencial": f["categoria"] in CATEGORIAS_ESENCIALES,
        }

    gasto_total = sum(g["total"] for g in gasto.values())
    # Se redondea PRIMERO y se resta despues, igual que en `get_client_snapshot`.
    # Al reves, las tres cifras que van juntas en pantalla (ingreso, gasto y
    # capacidad) pueden no cuadrar por un centavo por doble redondeo, y la
    # capacidad de ahorro es justo la que alimenta el tope del slider de
    # aportacion: tiene que ser la resta de lo que el usuario esta viendo.
    prom_gasto = round(gasto_total / meses, 2)
    prom_ingreso = round(ingreso_observado / meses, 2)
    prom_credito = round(pagos_credito / meses, 2)
    prom_costo = round(costo_financiero / meses, 2)
    capacidad = round(max(0.0, prom_ingreso - prom_gasto - prom_credito - prom_costo), 2)

    return {
        "client_id": client_id,
        "meses": meses,
        "desde": desde,
        "ingreso_mensual_declarado": cliente["ingreso_mensual"],
        "ingreso_mensual_observado": prom_ingreso,
        "gasto_mensual_promedio": prom_gasto,
        "pagos_credito_mensual": prom_credito,
        "costo_financiero_mensual": prom_costo,
        "capacidad_ahorro_mensual": capacidad,
        "tasa_ahorro": round(capacidad / prom_ingreso, 4) if prom_ingreso else 0.0,
        "por_categoria": sorted(gasto.values(), key=lambda g: -g["total"]),
    }


def search_transactions(
    client_id: str,
    fecha_desde: str | None = None,
    fecha_hasta: str | None = None,
    categoria: str | None = None,
    comercio: str | None = None,
    tipo: str | None = None,
    monto_min: float | None = None,
    monto_max: float | None = None,
    account_id: str | None = None,
    limite: int = 100,
) -> dict[str, Any]:
    """Búsqueda de movimientos con filtros combinables.

    A diferencia de `get_transactions` (los últimos N, para el caso común),
    esta es para "¿cuánto gasté en restaurantes en agosto?" o "movimientos
    de más de 2000 pesos en Amazon". Todos los filtros son opcionales y se
    combinan con AND.
    """
    if not 1 <= limite <= 300:
        raise ServiceError("`limite` debe estar entre 1 y 300.")
    if tipo is not None and tipo not in ("cargo", "abono"):
        raise ServiceError("`tipo` debe ser 'cargo' o 'abono'.")
    for etiqueta, valor in (("fecha_desde", fecha_desde), ("fecha_hasta", fecha_hasta)):
        if valor is not None:
            try:
                date.fromisoformat(valor[:10])
            except ValueError:
                raise ServiceError(
                    f"`{etiqueta}` debe ser una fecha ISO ('YYYY-MM-DD'), llegó {valor!r}."
                ) from None
    if monto_min is not None and monto_min < 0:
        raise ServiceError("`monto_min` no puede ser negativo.")
    if monto_max is not None and monto_max < 0:
        raise ServiceError("`monto_max` no puede ser negativo.")
    if monto_min is not None and monto_max is not None and monto_min > monto_max:
        raise ServiceError("`monto_min` no puede ser mayor que `monto_max`.")
    if comercio is not None and len(comercio) > 80:
        raise ServiceError("`comercio` es demasiado largo (máximo 80 caracteres).")

    with db.session(readonly=True) as conn:
        _exigir_cliente(conn, client_id)
        if account_id is not None:
            _exigir_cuenta_del_cliente(conn, client_id, account_id)

        sql = (
            "SELECT t.* FROM transactions t JOIN accounts a USING (account_id)"
            " WHERE a.client_id = ?"
        )
        params: list[Any] = [client_id]
        if account_id is not None:
            sql += " AND t.account_id = ?"
            params.append(account_id)
        if fecha_desde is not None:
            sql += " AND t.fecha >= ?"
            params.append(fecha_desde)
        if fecha_hasta is not None:
            sql += " AND t.fecha <= ?"
            params.append(fecha_hasta + "T23:59:59")
        if categoria is not None:
            sql += " AND t.categoria = ?"
            params.append(categoria)
        if tipo is not None:
            sql += " AND t.tipo = ?"
            params.append(tipo)
        if comercio is not None:
            sql += " AND (t.comercio LIKE ? OR t.descripcion LIKE ?)"
            comodin = f"%{comercio}%"
            params.extend([comodin, comodin])
        if monto_min is not None:
            sql += " AND t.monto >= ?"
            params.append(monto_min)
        if monto_max is not None:
            sql += " AND t.monto <= ?"
            params.append(monto_max)
        sql += " ORDER BY t.fecha DESC LIMIT ?"
        params.append(limite)
        filas = db.query(conn, sql, tuple(params))

    cargos = sum(f["monto"] for f in filas if f["tipo"] == "cargo")
    abonos = sum(f["monto"] for f in filas if f["tipo"] == "abono")
    return {
        "client_id": client_id,
        "filtros": {
            "fecha_desde": fecha_desde, "fecha_hasta": fecha_hasta,
            "categoria": categoria, "comercio": comercio, "tipo": tipo,
            "monto_min": monto_min, "monto_max": monto_max, "account_id": account_id,
        },
        "movimientos": filas,
        "total": len(filas),
        "total_cargos": round(cargos, 2),
        "total_abonos": round(abonos, 2),
    }


def get_budgets(client_id: str) -> dict[str, Any]:
    """Presupuestos por categoría que el cliente ya configuró."""
    with db.session(readonly=True) as conn:
        _exigir_cliente(conn, client_id)
        filas = db.query(
            conn, "SELECT categoria, monto_mensual, actualizado_en FROM budgets"
                  " WHERE client_id = ? ORDER BY categoria", (client_id,))
    return {"client_id": client_id, "presupuestos": filas}


def get_spending_alerts(client_id: str) -> dict[str, Any]:
    """Compara el gasto de los últimos 30 días contra los presupuestos vigentes.

    Solo evalúa categorías con presupuesto configurado: sin un límite que el
    usuario haya puesto, no hay "exceso" que señalar, solo gasto.
    """
    with db.session(readonly=True) as conn:
        _exigir_cliente(conn, client_id)
        presupuestos = db.query(
            conn, "SELECT categoria, monto_mensual FROM budgets WHERE client_id = ?",
            (client_id,))
        if not presupuestos:
            return {"client_id": client_id, "alertas": [], "nota": "Sin presupuestos configurados."}

        desde = (_fecha_valuacion(conn) - timedelta(days=30)).isoformat()
        gasto_filas = db.query(
            conn,
            "SELECT t.categoria, SUM(t.monto) total FROM transactions t"
            " JOIN accounts a USING (account_id)"
            " WHERE a.client_id = ? AND t.tipo = 'cargo' AND t.fecha >= ?"
            " GROUP BY t.categoria", (client_id, desde))
    gasto_por_categoria = {f["categoria"]: f["total"] for f in gasto_filas}

    alertas = []
    for p in presupuestos:
        gastado = round(gasto_por_categoria.get(p["categoria"], 0.0), 2)
        presupuesto = p["monto_mensual"]
        porcentaje = round(gastado / presupuesto, 4) if presupuesto else 0.0
        alertas.append({
            "categoria": p["categoria"],
            "presupuesto": presupuesto,
            "gastado": gastado,
            "restante": round(presupuesto - gastado, 2),
            "porcentaje": porcentaje,
            "excedido": gastado > presupuesto,
        })
    alertas.sort(key=lambda a: -a["porcentaje"])
    return {"client_id": client_id, "ventana_dias": 30, "alertas": alertas}


def get_credit_overview(client_id: str) -> dict[str, Any]:
    """Creditos y tarjetas: saldo, pago mensual y que tanto pesa sobre el ingreso."""
    with db.session(readonly=True) as conn:
        cliente = _exigir_cliente(conn, client_id)
        prestamos = db.query(
            conn, "SELECT * FROM loans WHERE client_id = ?", (client_id,))
        tarjetas = db.query(
            conn, "SELECT card_id, tipo, last4, limite_credito, saldo_utilizado,"
                  " dia_corte, dia_pago FROM cards WHERE client_id = ? AND tipo = 'credito'",
            (client_id,))

    pago_mensual = sum(p["pago_mensual"] for p in prestamos)
    deuda = sum(p["saldo_insoluto"] for p in prestamos) + sum(
        t["saldo_utilizado"] for t in tarjetas)
    limite = sum(t["limite_credito"] or 0 for t in tarjetas)
    utilizado = sum(t["saldo_utilizado"] for t in tarjetas)
    ingreso = cliente["ingreso_mensual"]

    return {
        "client_id": client_id,
        "prestamos": [
            {**p, "mensualidades_restantes": p["plazo_meses"] - p["mensualidades_pagadas"]}
            for p in prestamos
        ],
        "tarjetas_credito": tarjetas,
        "deuda_total": round(deuda, 2),
        "pago_mensual_total": round(pago_mensual, 2),
        "uso_linea_revolvente": round(utilizado / limite, 4) if limite else 0.0,
        "carga_sobre_ingreso": round(pago_mensual / ingreso, 4) if ingreso else 0.0,
    }
