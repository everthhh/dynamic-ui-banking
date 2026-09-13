"""Generador de la base simulada del banco. Determinista: semilla fija.

    python -m bank.seed            # escribe data/bank.sqlite + data/series.parquet
    python -m bank.seed --check    # solo verifica que lo generado sea consistente

Lo que produce:
  * 24 instrumentos (bank/instrumentos.py)
  * 120 meses de series por instrumento, GBM con correlacion entre clases
  * 8 clientes con cuentas, 18 meses de movimientos, tarjetas y creditos
  * perfiles de riesgo: algunos vigentes, algunos vencidos, uno inexistente
  * posiciones de inversion y un historial corto de ordenes ejecutadas

Invariante del demo: CLI-0001 no tiene perfil de riesgo vigente. Es lo que
hace que el agente genere el perfilador en lugar de proponer de entrada.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from bank import carteras, db, emisoras, mercado, pagos
from bank.finance import fiscal
from bank.instrumentos import (
    INSTRUMENTOS,
    correlacion_instrumentos,
    duracion_anios,
    sensibilidad_reinversion,
)

MESES_SERIE = 120          # 10 anos
MESES_MOVIMIENTOS = 18
FECHA_VALUACION = date(2026, 9, 1)
# Los parametros de mercado ya no se inventan aqui: viven en bank/mercado.py
# con su procedencia. Estos alias existen para no romper a quien los importa.
TASA_LIBRE_RIESGO = mercado.TASA_LIBRE_RIESGO
INFLACION_ANUAL = mercado.INFLACION_ANUAL

CIUDADES = ("Monterrey", "Guadalajara", "CDMX", "Queretaro",
            "Merida", "Puebla", "Tijuana", "Leon")

# ---------------------------------------------------------------------------
# clientes sinteticos
# ---------------------------------------------------------------------------
# (id, nombre, segmento, ingreso_mensual, horizonte_meses, perfil_sembrado)
# perfil_sembrado = None  -> no tiene perfil en la base
#                 = ("vencido", score) -> perfil existente pero fuera de vigencia
#                 = ("vigente", score) -> perfil usable
CLIENTES = (
    ("CLI-0001", "Ana Sofia Reyes",     "preferente",  48_000,  60, None),
    ("CLI-0002", "Javier Montemayor",   "patrimonial", 180_000, 120, ("vigente", 72)),
    ("CLI-0003", "Luis Fernando Quiroz", "nomina",      21_500,  24, ("vigente", 28)),
    ("CLI-0004", "Mariana Elizondo",    "preferente",  62_000,  36, ("vencido", 55)),
    ("CLI-0005", "Diego Alcantara",     "nomina",      18_200,  12, ("vigente", 18)),
    ("CLI-0006", "Paulina Cervantes",   "patrimonial", 240_000, 180, ("vigente", 88)),
    ("CLI-0007", "Rodrigo Nava",        "pyme",        95_000,  48, ("vencido", 64)),
    ("CLI-0008", "Gabriela Ontiveros",  "preferente",  55_000,  84, ("vigente", 45)),
)

PERFILES = (
    (0, 20, "conservador"),
    (21, 40, "moderado"),
    (41, 60, "balanceado"),
    (61, 80, "crecimiento"),
    (81, 100, "agresivo"),
)

CATEGORIAS_CARGO = (
    ("super", "Supermercado", 900, 3_200),
    ("restaurantes", "Restaurante", 250, 1_400),
    ("transporte", "Transporte", 120, 800),
    ("servicios", "Servicios del hogar", 400, 1_900),
    ("renta", "Renta", 8_000, 18_000),
    ("salud", "Farmacia", 180, 1_100),
    ("entretenimiento", "Suscripciones y salidas", 150, 1_200),
    ("educacion", "Colegiaturas", 2_500, 9_000),
)


def perfil_de_score(score: int) -> str:
    for lo, hi, nombre in PERFILES:
        if lo <= score <= hi:
            return nombre
    return "balanceado"


def _fines_de_mes(n: int, hasta: date) -> list[date]:
    """n fechas de fin de mes terminando en el mes de `hasta`."""
    fechas: list[date] = []
    y, m = hasta.year, hasta.month
    for _ in range(n):
        siguiente = date(y + (m // 12), (m % 12) + 1, 1)
        fechas.append(siguiente - timedelta(days=1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(fechas))


# ---------------------------------------------------------------------------
# series de precios
# ---------------------------------------------------------------------------
def generar_series(rng: np.random.Generator) -> dict[str, list[tuple[date, float, float]]]:
    """GBM mensual por instrumento, correlacionado a traves de la clase de activo.

    Construye la matriz de correlacion a nivel instrumento desde la de clases,
    la factoriza con Cholesky y mapea ruido gaussiano independiente a ruido
    correlacionado. La diagonal se infla un poco para que la matriz quede
    definida positiva aunque dos clases esten muy correlacionadas.
    """
    n = len(INSTRUMENTOS)
    corr = np.empty((n, n))
    for i, a in enumerate(INSTRUMENTOS):
        for j, b in enumerate(INSTRUMENTOS):
            # `correlacion_instrumentos` usa el modelo de indice unico entre
            # dos acciones (beta y sector) y la matriz de clases para el
            # resto. Antes aqui habia un promedio de clase que ponia a CEMEX
            # y a WALMEX al 0.94 por ser las dos "renta variable".
            corr[i, j] = 1.0 if i == j else correlacion_instrumentos(
                a.instrument_id, b.instrument_id)
    corr = (corr + corr.T) / 2
    corr += np.eye(n) * 1e-6
    try:
        L = np.linalg.cholesky(corr)
    except np.linalg.LinAlgError:
        # proyeccion a la matriz definida positiva mas cercana
        vals, vecs = np.linalg.eigh(corr)
        vals = np.clip(vals, 1e-8, None)
        corr = vecs @ np.diag(vals) @ vecs.T
        d = np.sqrt(np.diag(corr))
        corr = corr / np.outer(d, d)
        L = np.linalg.cholesky(corr + np.eye(n) * 1e-9)

    z = rng.standard_normal((MESES_SERIE, n))
    shocks = z @ L.T
    # Centramos los shocks en el horizonte: asi el historial realizado no se
    # aleja del rendimiento declarado por puro azar de la muestra. Es una
    # decision consciente de datos sinteticos -- estas series son ilustrativas,
    # no un backtest. La correlacion entre instrumentos se conserva.
    shocks = shocks - shocks.mean(axis=0, keepdims=True)

    mu = np.array([i.rend_esperado_anual for i in INSTRUMENTOS])
    sigma = np.array([i.volatilidad_anual for i in INSTRUMENTOS])
    dt = 1 / 12
    # `rend_esperado_anual` es rendimiento ARITMETICO anual esperado, por eso
    # log1p(mu) y no mu. El -sigma^2/2 es el arrastre por volatilidad: la
    # trayectoria mediana rinde menos que la media, y eso es correcto.
    drift = (np.log1p(mu) - 0.5 * sigma**2) * dt
    difusion = sigma * np.sqrt(dt)

    log_ret = drift + difusion * shocks          # (meses, instrumentos)
    fechas = _fines_de_mes(MESES_SERIE, FECHA_VALUACION)

    salida: dict[str, list[tuple[date, float, float]]] = {}
    for j, inst in enumerate(INSTRUMENTOS):
        valor = 100.0
        filas: list[tuple[date, float, float]] = []
        for t, fecha in enumerate(fechas):
            r = float(np.expm1(log_ret[t, j]))
            valor *= 1 + r
            filas.append((fecha, round(valor, 6), round(r, 8)))
        salida[inst.instrument_id] = filas
    return salida


# ---------------------------------------------------------------------------
# pagos: servicios guardados, contactos y dinero que entra y sale
# ---------------------------------------------------------------------------
# Nada de lo que siembra pagos sale de `rng`: sale de `rng_pagos` (semilla
# aparte) o de `pagos.digitos_deterministas`. Así abrir el dominio no movió ni
# un número de las inversiones, que dependen de la secuencia de `rng`.
CONTACTOS_SEMILLA = (
    # (alias, titular, banco). NU se siembra como tarjeta; los demás, como CLABE.
    ("Mamá", "María Guadalupe Torres", "012"),
    ("Casero", "Inmobiliaria Cumbres (sim)", "014"),
    ("Hermano", "Carlos Iván Ruiz", "638"),
    ("Tanda", "Rosa Elena Garza", "002"),
    ("Taller", "Refaccionaria El Pistón (sim)", "021"),
    ("Colegio", "Colegio Montessori del Valle (sim)", "044"),
)
REMITENTES_SEMILLA = (
    ("Laura Méndez Cantú", "012", "Reembolso de comida"),
    ("Servicios Profesionales Norte (sim)", "014", "Pago de proyecto"),
    ("Jorge Alberto Salinas", "002", "Tanda"),
    ("Fernanda Ibarra", "638", "Préstamo"),
    ("Tienda en línea (sim)", "722", "Venta en línea"),
    ("Luis Ángel Treviño", "127", "Regalo"),
)
CONCEPTOS_ENVIO = ("Renta", "Cooperación", "Tanda", "Préstamo", "Regalo", "Mantenimiento")
ALIAS_SERVICIO = {"luz": "Luz de la casa", "telefonia": "Mi celular"}
SERVICIOS_CON_TELEFONO = ("TELMEX", "TELCEL", "ATT")


def _clabe_de_cuenta(idx: int, inversion: bool) -> str:
    """CLABE mock con dígito verificador válido: banco 072, plaza 180 o 181."""
    return pagos.clabe_con_digito(pagos.BANCO_PROPIO, "181" if inversion else "180", f"{idx:011d}")


def _convenios_de(idx: int, ciudad: str, segmento: str) -> list[str]:
    ids = ["CFE", pagos.AGUA_POR_CIUDAD[ciudad],
           ("TELMEX", "IZZI", "TOTALPLAY", "MEGACABLE")[idx % 4],
           ("TELCEL", "ATT")[idx % 2]]
    if segmento == "patrimonial":
        ids.append("SKY")
    if idx % 3 == 0:
        ids.append("NATURGY")
    return ids


def _referencia_semilla(conv: pagos.Convenio, cid: str, ciudad: str) -> str:
    semilla = f"ref-{cid}-{conv.biller_id}"
    if conv.biller_id in SERVICIOS_CON_TELEFONO:
        lada = pagos.LADAS[ciudad]
        return lada + pagos.digitos_deterministas(semilla, 10 - len(lada))
    return pagos.digitos_deterministas(semilla, conv.digitos_max)


def _sembrar_servicios(conn: sqlite3.Connection, cid: str, idx: int, ciudad: str,
                       segmento: str) -> list[tuple[str, pagos.Convenio]]:
    alta = (FECHA_VALUACION - timedelta(days=31 * MESES_MOVIMIENTOS)).isoformat() + "T08:00:00"
    servicios = []
    for k, biller_id in enumerate(_convenios_de(idx, ciudad, segmento)):
        conv = pagos.CONVENIO_POR_ID[biller_id]
        service_id = f"SRV-{idx:04d}-{k}"
        conn.execute(
            "INSERT INTO saved_services (service_id, client_id, biller_id, referencia, alias,"
            " creado_en) VALUES (?,?,?,?,?,?)",
            (service_id, cid, biller_id, _referencia_semilla(conv, cid, ciudad),
             ALIAS_SERVICIO.get(conv.categoria), alta))
        servicios.append((service_id, conv))
    return servicios


def _sembrar_contactos(conn: sqlite3.Connection, cid: str, idx: int) -> list[dict]:
    """Dos contactos de otros bancos y uno del mismo banco (la cuenta de uso del
    siguiente cliente). Guardados hace meses: ya no cuentan como destino nuevo."""
    creado = (FECHA_VALUACION - timedelta(days=200 + idx)).isoformat() + "T12:00:00"
    contactos = []
    for k in range(2):
        alias, titular, banco = CONTACTOS_SEMILLA[(idx + k) % len(CONTACTOS_SEMILLA)]
        semilla = f"contacto-{cid}-{k}"
        if banco == "638":
            tipo = "tarjeta"
            numero = pagos.tarjeta_con_luhn("4" + pagos.digitos_deterministas(semilla, 14))
        else:
            tipo = "clabe"
            numero = pagos.clabe_con_digito(banco, pagos.digitos_deterministas(semilla + "-plaza", 3),
                                            pagos.digitos_deterministas(semilla, 11))
        contactos.append({"beneficiary_id": f"BEN-{idx:04d}-{k}", "alias": alias,
                          "titular": titular, "tipo_destino": tipo, "numero": numero,
                          "banco_codigo": banco})
    siguiente = (idx + 1) % len(CLIENTES)
    contactos.append({"beneficiary_id": f"BEN-{idx:04d}-2",
                      "alias": CLIENTES[siguiente][1].split()[0],
                      "titular": CLIENTES[siguiente][1], "tipo_destino": "clabe",
                      "numero": _clabe_de_cuenta(siguiente, inversion=False),
                      "banco_codigo": pagos.BANCO_PROPIO})
    for c in contactos:
        conn.execute(
            "INSERT INTO beneficiaries (beneficiary_id, client_id, alias, titular, tipo_destino,"
            " numero, banco_codigo, creado_en) VALUES (?,?,?,?,?,?,?,?)",
            (c["beneficiary_id"], cid, c["alias"], c["titular"], c["tipo_destino"],
             c["numero"], c["banco_codigo"], creado))
    return contactos


def _momento_del_mes(base: date, rng_pagos: np.random.Generator) -> datetime:
    dia = base + timedelta(days=int(rng_pagos.integers(1, 28)))
    return datetime.combine(dia, datetime.min.time()) + timedelta(
        hours=int(rng_pagos.integers(7, 22)), minutes=int(rng_pagos.integers(0, 60)))


def _insertar_movimiento(conn: sqlite3.Connection, txn_id: str, account_id: str,
                         momento: datetime, tipo: str, monto: float, categoria: str,
                         descripcion: str, comercio: str | None, saldo: float) -> None:
    conn.execute(
        "INSERT INTO transactions (txn_id, account_id, fecha, tipo, monto,"
        " categoria, descripcion, comercio, saldo_posterior) VALUES (?,?,?,?,?,?,?,?,?)",
        (txn_id, account_id, momento.isoformat(), tipo, monto, categoria, descripcion,
         comercio, round(saldo, 2)))


def _insertar_pago_historico(conn: sqlite3.Connection, **columnas) -> None:
    """Una operación ya ejecutada del historial. El token de semilla solo existe hasheado."""
    folio = columnas["folio"]
    columnas.update({
        "estado": "ejecutada",
        "idempotency_key": f"seed-{columnas['client_id']}-{folio}",
        "confirmation_token_hash": hashlib.sha256(f"tok-{folio}-seed".encode("utf-8")).hexdigest(),
    })
    conn.execute(
        f"INSERT INTO payments ({', '.join(columnas)}) VALUES ({', '.join('?' for _ in columnas)})",
        tuple(columnas.values()))


def _sembrar_recibos(conn: sqlite3.Connection, cid: str, idx: int, ciudad: str,
                     servicios: list[tuple[str, pagos.Convenio]]) -> None:
    """El recibo vigente de cada servicio, consultado igual que lo haría `register_service`.

    Algunos quedan vencidos a propósito (el último servicio de un cliente de
    cada tres) para que el panel tenga los dos casos. El CFE de CLI-0001 vence
    en cuatro días: es el recibo del guion de pagos.
    """
    for k, (service_id, conv) in enumerate(servicios):
        referencia = _referencia_semilla(conv, cid, ciudad)
        recibo = pagos.recibo_simulado(conv, referencia, FECHA_VALUACION)
        if idx % 3 == 1 and k == len(servicios) - 1:
            recibo["fecha_limite"] = (FECHA_VALUACION - timedelta(days=2)).isoformat()
        if cid == "CLI-0001" and conv.biller_id == "CFE":
            recibo["fecha_limite"] = (FECHA_VALUACION + timedelta(days=4)).isoformat()
        conn.execute(
            "INSERT INTO bills (bill_id, service_id, periodo, monto, fecha_emision, fecha_limite)"
            " VALUES (?,?,?,?,?,?)",
            (f"BIL-{idx:04d}-{k}", service_id, recibo["periodo"], recibo["monto"],
             recibo["fecha_emision"], recibo["fecha_limite"]))


# ---------------------------------------------------------------------------
# core bancario
# ---------------------------------------------------------------------------
def sembrar_core(conn: sqlite3.Connection, rng: np.random.Generator,
                 rng_pagos: np.random.Generator) -> None:
    txn_n = 0
    pago_n = 0
    for idx, (cid, nombre, segmento, ingreso, horizonte, _perfil) in enumerate(CLIENTES):
        alta = date(2017 + idx % 6, 1 + (idx * 3) % 12, 1 + (idx * 5) % 27)
        conn.execute(
            "INSERT INTO clients (client_id, nombre, fecha_alta, segmento, ciudad,"
            " rfc_mock, ingreso_mensual, horizonte_meses) VALUES (?,?,?,?,?,?,?,?)",
            (cid, nombre, alta.isoformat(), segmento, CIUDADES[idx],
             f"XXXX{alta.strftime('%y%m%d')}{chr(65 + idx)}{idx}A", float(ingreso), horizonte),
        )

        # una cuenta de uso diario y una de inversion
        uso = f"ACC-{idx * 2 + 1:04d}"
        inv = f"ACC-{idx * 2 + 2:04d}"
        saldo_uso = round(float(ingreso) * rng.uniform(0.4, 2.2), 2)
        conn.execute(
            "INSERT INTO accounts (account_id, client_id, tipo, clabe_mock, moneda,"
            " saldo_disponible, saldo_liquidado, abierta_en) VALUES (?,?,?,?,?,?,?,?)",
            (uso, cid, "nomina" if segmento == "nomina" else "cheques",
             _clabe_de_cuenta(idx, inversion=False), "MXN", saldo_uso, saldo_uso,
             alta.isoformat()),
        )
        # Efectivo SIN invertir dentro de la cuenta de inversion. Lo que ya se
        # invirtio vive en `positions`, no aqui. Quien no tiene perfil tampoco
        # tiene posiciones, asi que le dejamos un piso de efectivo: es el
        # cliente del guion ("tengo 80 mil parados").
        tiene_perfil = CLIENTES[idx][5] is not None
        saldo_inv = float(ingreso) * float(rng.uniform(0.5, 4.0))
        if not tiene_perfil:
            saldo_inv = max(saldo_inv, float(ingreso) * 2.5)
        saldo_inv = round(saldo_inv, 2)
        conn.execute(
            "INSERT INTO accounts (account_id, client_id, tipo, clabe_mock, moneda,"
            " saldo_disponible, saldo_liquidado, abierta_en) VALUES (?,?,?,?,?,?,?,?)",
            (inv, cid, "inversion", _clabe_de_cuenta(idx, inversion=True), "MXN",
             saldo_inv, saldo_inv, alta.isoformat()),
        )

        ciudad = CIUDADES[idx]
        servicios = _sembrar_servicios(conn, cid, idx, ciudad, segmento)
        contactos_externos = [c for c in _sembrar_contactos(conn, cid, idx)
                              if c["banco_codigo"] != pagos.BANCO_PROPIO]

        # movimientos de los ultimos 18 meses en la cuenta de uso
        saldo = saldo_uso
        inicio = FECHA_VALUACION - timedelta(days=30 * MESES_MOVIMIENTOS)
        for mes in range(MESES_MOVIMIENTOS):
            base = inicio + timedelta(days=30 * mes)
            # abono de nomina, quincenal
            for quincena in (0, 15):
                txn_n += 1
                monto = round(float(ingreso) / 2 * rng.uniform(0.97, 1.03), 2)
                saldo += monto
                conn.execute(
                    "INSERT INTO transactions (txn_id, account_id, fecha, tipo, monto,"
                    " categoria, descripcion, comercio, saldo_posterior)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (f"TXN-{txn_n:06d}", uso,
                     (base + timedelta(days=quincena)).isoformat() + "T09:00:00",
                     "abono", monto, "nomina", "Deposito de nomina", "Empleador (sim)",
                     round(saldo, 2)),
                )
            # cargos del mes
            for k in range(int(rng.integers(9, 17))):
                categoria, desc, lo, hi = CATEGORIAS_CARGO[int(rng.integers(0, len(CATEGORIAS_CARGO)))]
                if categoria in ("renta", "educacion") and k > 0:
                    continue            # esos son una vez al mes
                monto = round(float(rng.uniform(lo, hi)), 2)
                fecha_cargo = ((base + timedelta(days=int(rng.integers(1, 28)))).isoformat() + "T"
                               f"{int(rng.integers(8, 22)):02d}:{int(rng.integers(0, 60)):02d}:00")
                if categoria == "servicios":
                    # Los servicios ya no son un cargo genérico: son pagos a CFE,
                    # al agua o al internet del cliente (abajo). Los números de
                    # `rng` se consumen igual, para no mover su secuencia.
                    continue
                txn_n += 1
                saldo -= monto
                conn.execute(
                    "INSERT INTO transactions (txn_id, account_id, fecha, tipo, monto,"
                    " categoria, descripcion, comercio, saldo_posterior)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (f"TXN-{txn_n:06d}", uso, fecha_cargo,
                     "cargo", monto, categoria, desc, f"{desc} (sim)", round(saldo, 2)),
                )

            # pagos de servicios: los bimestrales, un mes sí y uno no
            for service_id, conv in servicios:
                if conv.periodicidad == "bimestral" and mes % 2:
                    continue
                txn_n += 1
                pago_n += 1
                momento = _momento_del_mes(base, rng_pagos)
                minimo, maximo = conv.monto_tipico
                monto = round(float(rng_pagos.uniform(minimo, maximo)), 2)
                folio = f"PG-{momento.year}-{pago_n:06d}"
                saldo -= monto
                _insertar_movimiento(conn, f"TXN-{txn_n:06d}", uso, momento, "cargo", monto,
                                     "servicios", f"Pago {conv.nombre} · folio {folio}",
                                     conv.nombre, saldo)
                _insertar_pago_historico(
                    conn, payment_id=f"PAY-SEED-{pago_n:06d}", folio=folio, client_id=cid,
                    account_id=uso, tipo="servicio", monto=monto, comision=0.0,
                    concepto=f"Pago {conv.nombre}", service_id=service_id,
                    creada_en=momento.isoformat(),
                    ejecutada_en=(momento + timedelta(minutes=1)).isoformat())

            # una transferencia a un contacto, algunos meses
            if contactos_externos and rng_pagos.random() < 0.45:
                contacto = contactos_externos[int(rng_pagos.integers(0, len(contactos_externos)))]
                concepto = CONCEPTOS_ENVIO[int(rng_pagos.integers(0, len(CONCEPTOS_ENVIO)))]
                momento = _momento_del_mes(base, rng_pagos)
                tope = min(15_000.0, max(600.0, float(ingreso) * 0.12))
                monto = round(float(rng_pagos.uniform(300, tope)), 2)
                txn_n += 1
                pago_n += 1
                folio = f"PG-{momento.year}-{pago_n:06d}"
                clave = f"BNTE{momento:%Y%m%d}{pago_n:010d}"
                saldo -= monto
                _insertar_movimiento(
                    conn, f"TXN-{txn_n:06d}", uso, momento, "cargo", monto, "transferencia",
                    f"SPEI enviado · {concepto} · rastreo {clave}",
                    f"{contacto['titular']} ({pagos.BANCOS[contacto['banco_codigo']]})", saldo)
                _insertar_pago_historico(
                    conn, payment_id=f"PAY-SEED-{pago_n:06d}", folio=folio, client_id=cid,
                    account_id=uso, tipo="transferencia", monto=monto, comision=0.0,
                    concepto=concepto, destino_tipo=contacto["tipo_destino"],
                    destino_numero=contacto["numero"], destino_banco=contacto["banco_codigo"],
                    destino_titular=contacto["titular"],
                    beneficiary_id=contacto["beneficiary_id"], clave_rastreo=clave,
                    creada_en=momento.isoformat(),
                    ejecutada_en=(momento + timedelta(minutes=1)).isoformat())

            # dinero que entra además de la nómina: un SPEI o un depósito en tienda
            if rng_pagos.random() < 0.40:
                remitente, banco, concepto = REMITENTES_SEMILLA[
                    int(rng_pagos.integers(0, len(REMITENTES_SEMILLA)))]
                momento = _momento_del_mes(base, rng_pagos)
                monto = round(float(rng_pagos.uniform(250, max(500.0, float(ingreso) * 0.15))), 2)
                txn_n += 1
                saldo += monto
                _insertar_movimiento(conn, f"TXN-{txn_n:06d}", uso, momento, "abono", monto,
                                     "transferencia", f"SPEI recibido · {concepto}", remitente, saldo)
                conn.execute(
                    "INSERT INTO incoming_transfers (txn_id, canal, remitente, banco_origen,"
                    " cuenta_origen_mask, concepto, clave_rastreo) VALUES (?,?,?,?,?,?,?)",
                    (f"TXN-{txn_n:06d}", "spei", remitente, banco,
                     pagos.enmascarar(pagos.digitos_deterministas(f"origen-{remitente}", 18)),
                     concepto, f"SPEI{momento:%Y%m%d}{txn_n:010d}"))
            if rng_pagos.random() < 0.15:
                tiendas = [c for c in pagos.CANALES_EFECTIVO if c.requiere_referencia]
                tienda = tiendas[int(rng_pagos.integers(0, len(tiendas)))]
                momento = _momento_del_mes(base, rng_pagos)
                monto = round(float(rng_pagos.uniform(500, 4_000)), 2)
                txn_n += 1
                saldo += monto
                _insertar_movimiento(conn, f"TXN-{txn_n:06d}", uso, momento, "abono", monto,
                                     "deposito", f"Depósito en efectivo · {tienda.nombre}",
                                     tienda.nombre, saldo)
                conn.execute(
                    "INSERT INTO incoming_transfers (txn_id, canal, remitente, banco_origen,"
                    " cuenta_origen_mask, concepto, clave_rastreo) VALUES (?,?,?,?,?,?,?)",
                    (f"TXN-{txn_n:06d}", "deposito_efectivo", "Depósito en efectivo", None,
                     None, tienda.nombre, None))

            # Barrido de fin de mes: lo que sobra se va a la cuenta de inversion.
            # Sin esto la cuenta de uso acumula 18 meses de excedente y un
            # cliente de 48 mil de ingreso termina con un millon parado ahi,
            # que es justo el tipo de dato absurdo que un juez nota.
            colchon = float(ingreso) * float(rng.uniform(0.6, 1.6))
            excedente = saldo - colchon
            if excedente > 500:
                txn_n += 1
                saldo -= excedente
                conn.execute(
                    "INSERT INTO transactions (txn_id, account_id, fecha, tipo, monto,"
                    " categoria, descripcion, comercio, saldo_posterior)"
                    " VALUES (?,?,?,?,?,?,?,?,?)",
                    (f"TXN-{txn_n:06d}", uso,
                     (base + timedelta(days=28)).isoformat() + "T23:00:00",
                     "cargo", round(excedente, 2), "traspaso",
                     "Traspaso a cuenta de inversión", None, round(saldo, 2)),
                )
        conn.execute("UPDATE accounts SET saldo_disponible = ?, saldo_liquidado = ?"
                     " WHERE account_id = ?", (round(saldo, 2), round(saldo, 2), uso))
        _sembrar_recibos(conn, cid, idx, ciudad, servicios)

        # tarjetas
        conn.execute(
            "INSERT INTO cards (card_id, client_id, account_id, tipo, last4, limite_credito,"
            " saldo_utilizado, tasa_anual, dia_corte, dia_pago) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (f"CRD-{idx * 2 + 1:04d}", cid, uso, "debito", f"{int(rng.integers(1000, 9999))}",
             None, 0.0, None, None, None),
        )
        if segmento != "nomina" or rng.random() < 0.6:
            limite = round(float(ingreso) * rng.uniform(1.5, 5.0), -3)
            # La tasa es lo que convierte a la tarjeta en un origen de fondos
            # evaluable: sin ella no se puede comparar contra el rendimiento
            # esperado del portafolio.
            tasa_tdc = round(float(rng.uniform(0.32, 0.52)), 4)
            conn.execute(
                "INSERT INTO cards (card_id, client_id, account_id, tipo, last4, limite_credito,"
                " saldo_utilizado, tasa_anual, dia_corte, dia_pago) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"CRD-{idx * 2 + 2:04d}", cid, None, "credito",
                 f"{int(rng.integers(1000, 9999))}", limite,
                 round(limite * float(rng.uniform(0.05, 0.55)), 2), tasa_tdc,
                 int(rng.integers(1, 28)), int(rng.integers(1, 28))),
            )

        # credito vigente para la mitad de los clientes
        if idx % 2 == 0:
            producto = ("auto", "hipotecario", "personal", "nomina")[idx % 4]
            monto = {"auto": 380_000, "hipotecario": 2_400_000,
                     "personal": 120_000, "nomina": 80_000}[producto]
            plazo = {"auto": 60, "hipotecario": 240, "personal": 36, "nomina": 24}[producto]
            tasa = {"auto": 0.135, "hipotecario": 0.1075, "personal": 0.289, "nomina": 0.215}[producto]
            i = tasa / 12
            pago = monto * i / (1 - (1 + i) ** -plazo)
            pagadas = int(rng.integers(4, max(5, plazo // 2)))
            saldo_insoluto = monto * ((1 + i) ** plazo - (1 + i) ** pagadas) / ((1 + i) ** plazo - 1)
            conn.execute(
                "INSERT INTO loans (loan_id, client_id, producto, monto_original, saldo_insoluto,"
                " tasa_anual, plazo_meses, pago_mensual, mensualidades_pagadas, abierto_en)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"LON-{idx:04d}", cid, producto, float(monto), round(saldo_insoluto, 2),
                 tasa, plazo, round(pago, 2), pagadas,
                 (FECHA_VALUACION - timedelta(days=30 * pagadas)).isoformat()),
            )

        # Presupuestos: solo para el cliente del guion (CLI-0001), a propósito
        # sin tocar los demás — así el demo muestra tanto el caso "ya configuró
        # presupuestos" como el caso "todavía no", que es el más común.
        if cid == "CLI-0001":
            hoy_iso = FECHA_VALUACION.isoformat()
            for cat_idx, (categoria, monto_presupuesto) in enumerate(
                (("super", 3000.0), ("restaurantes", 1200.0), ("entretenimiento", 500.0))
            ):
                conn.execute(
                    "INSERT INTO budgets (budget_id, client_id, categoria, monto_mensual,"
                    " creado_en, actualizado_en) VALUES (?,?,?,?,?,?)",
                    (f"BUD-{idx:04d}-{cat_idx}", cid, categoria, monto_presupuesto,
                     hoy_iso, hoy_iso),
                )


# ---------------------------------------------------------------------------
# inversiones
# ---------------------------------------------------------------------------
def sembrar_inversiones(
    conn: sqlite3.Connection,
    rng: np.random.Generator,
    series: dict[str, list[tuple[date, float, float]]],
) -> None:
    for idx, (cid, _n, _seg, ingreso, horizonte, perfil) in enumerate(CLIENTES):
        inv = f"ACC-{idx * 2 + 2:04d}"

        if perfil is not None:
            estado, score = perfil
            respondido = FECHA_VALUACION - timedelta(days=540 if estado == "vencido" else 45)
            vigente = respondido + timedelta(days=365)
            answers = [
                {"id": "horizonte", "value": min(5, max(1, horizonte // 24 + 1))},
                {"id": "reaccion_caida", "value": 1 + score // 25},
                {"id": "experiencia", "value": 1 + score // 30},
                {"id": "proposito", "value": 1 + (score // 20) % 5},
            ]
            conn.execute(
                "INSERT INTO risk_profiles (profile_id, client_id, score, perfil,"
                " horizonte_meses, respondido_en, vigente_hasta, answers_json)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (f"RSK-{idx:04d}", cid, score, perfil_de_score(score), horizonte,
                 respondido.isoformat(), vigente.isoformat(), json.dumps(answers)),
            )

        # posiciones: solo los que ya invirtieron
        if perfil is None or rng.random() < 0.2:
            continue
        score = perfil[1]
        candidatos = [i for i in INSTRUMENTOS if i.riesgo_1a5 <= max(1, score // 20 + 1)]
        elegidos = rng.choice(len(candidatos), size=int(rng.integers(2, 5)), replace=False)
        capital = float(ingreso) * float(rng.uniform(3, 20))
        pesos = rng.dirichlet(np.ones(len(elegidos)) * 2.5)
        for k, pos_idx in enumerate(elegidos):
            inst = candidatos[int(pos_idx)]
            serie = series[inst.instrument_id]
            meses_atras = int(rng.integers(6, 48))
            precio_entrada = serie[-meses_atras][1]
            monto = capital * float(pesos[k])
            titulos = monto / precio_entrada
            conn.execute(
                "INSERT INTO positions (position_id, client_id, account_id, instrument_id,"
                " titulos, costo_promedio, abierta_en) VALUES (?,?,?,?,?,?,?)",
                (f"POS-{idx:04d}-{k}", cid, inv, inst.instrument_id,
                 round(titulos, 6), round(precio_entrada, 6),
                 serie[-meses_atras][0].isoformat()),
            )

        # una orden historica ya ejecutada, para que `get_orders` no venga vacio
        oid = str(uuid.UUID(bytes=rng.integers(0, 256, size=16, dtype=np.uint8).tobytes()))
        creada = datetime.combine(
            FECHA_VALUACION - timedelta(days=int(rng.integers(30, 300))),
            datetime.min.time(),
        )
        monto_orden = round(capital * float(rng.uniform(0.2, 0.6)), 2)
        token_semilla = f"tok-{cid}-seed"
        conn.execute(
            "INSERT INTO orders (order_id, folio, client_id, account_id, estado, monto,"
            " creada_en, ejecutada_en, idempotency_key, confirmation_token_hash)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (oid, f"BN-{creada.year}-{100000 + idx * 37:06d}", cid, inv, "ejecutada",
             monto_orden, creada.isoformat(), (creada + timedelta(minutes=3)).isoformat(),
             f"seed-{cid}-1", hashlib.sha256(token_semilla.encode("utf-8")).hexdigest()),
        )
        inst = candidatos[int(elegidos[0])]
        precio = series[inst.instrument_id][-1][1]
        conn.execute(
            "INSERT INTO order_legs (order_id, instrument_id, peso, monto, titulos)"
            " VALUES (?,?,?,?,?)",
            (oid, inst.instrument_id, 1.0, monto_orden, round(monto_orden / precio, 6)),
        )


# ---------------------------------------------------------------------------
# emisoras
# ---------------------------------------------------------------------------
def sembrar_emisoras(conn: sqlite3.Connection) -> None:
    """Vuelca los fundamentales y el riesgo CALCULADO de cada emisora.

    Lo que se guarda en `issuers.score_riesgo` y `issuers.riesgo_1a5` es el
    resultado de `emisoras.perfil_riesgo()`, no un numero tecleado. El
    desglose por factor va a `issuer_risk_factors` para que la cifra se pueda
    auditar sin volver a correr Python.
    """
    for e in emisoras.EMISORAS:
        perfil = emisoras.perfil_riesgo(e)
        conn.execute(
            "INSERT INTO issuers (ticker, nombre, sector, precio, fuente_precio,"
            " fecha_precio, acciones_circulacion, capitalizacion_mdp, float_pct,"
            " beta, volatilidad_anual, dividend_yield, calificacion,"
            " deuda_neta_ebitda, cobertura_intereses, indice_capitalizacion,"
            " importe_operado_mdp, r_cuadrada, score_riesgo, riesgo_1a5, descripcion)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (e.ticker, e.nombre, e.sector, e.precio, e.fuente,
             emisoras.FECHA_PRECIOS.isoformat(), e.acciones_circulacion,
             round(emisoras.capitalizacion(e), 2), e.float_pct, e.beta,
             e.volatilidad_anual, e.dividend_yield, e.calificacion,
             e.deuda_neta_ebitda, e.cobertura_intereses, e.indice_capitalizacion,
             e.importe_operado_diario, emisoras.r_cuadrada(e), perfil["score"],
             perfil["riesgo_1a5"], e.descripcion),
        )
        conn.executemany(
            "INSERT INTO issuer_risk_factors (ticker, factor, valor, peso, aporte)"
            " VALUES (?,?,?,?,?)",
            [(e.ticker, f["factor"], f["valor"], f["peso"], f["aporte"])
             for f in perfil["desglose"]],
        )


# ---------------------------------------------------------------------------
def construir(path: Path | None = None) -> Path:
    rng = np.random.default_rng(db.SEED)
    target = db.reset(path)
    series = generar_series(rng)

    with db.session(target) as conn:
        conn.execute(
            "INSERT INTO market_params (id, fecha_valuacion, fecha_mercado,"
            " tasa_libre_riesgo, tasa_referencia, tasa_larga, inflacion_anual,"
            " ipc_nivel, volatilidad_mercado, prima_riesgo_mercado,"
            " isr_retencion_capital, isr_ganancia_capital, isr_dividendos, seed)"
            " VALUES (1,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (FECHA_VALUACION.isoformat(), mercado.FECHA_MERCADO.isoformat(),
             mercado.TASA_LIBRE_RIESGO, mercado.TASA_REFERENCIA, mercado.TASA_LARGA,
             mercado.INFLACION_ANUAL, mercado.IPC_NIVEL, mercado.VOLATILIDAD_MERCADO,
             mercado.PRIMA_RIESGO_MERCADO, mercado.ISR_RETENCION_CAPITAL,
             mercado.ISR_GANANCIA_CAPITAL, mercado.ISR_DIVIDENDOS, db.SEED),
        )
        for fila in mercado.ficha()["parametros"]:
            conn.execute(
                "INSERT INTO market_sources (clave, valor, tipo, fuente, tomado_en)"
                " VALUES (?,?,?,?,?)",
                (fila["clave"], fila["valor"], fila["tipo"], fila["fuente"],
                 fila["tomado_en"])),
        sembrar_emisoras(conn)
        for inst in INSTRUMENTOS:
            conn.execute(
                "INSERT INTO instruments (instrument_id, nombre, clase, emisor, moneda,"
                " rend_esperado_anual, volatilidad_anual, comision_anual, plazo_dias,"
                " liquidez, monto_minimo, riesgo_1a5, isin_mock, descripcion,"
                " regimen_fiscal, duracion_anios, sens_reinversion, riesgo_derivado)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (inst.instrument_id, inst.nombre, inst.clase, inst.emisor, inst.moneda,
                 inst.rend_esperado_anual, inst.volatilidad_anual, inst.comision_anual,
                 inst.plazo_dias, inst.liquidez, inst.monto_minimo, inst.riesgo_1a5,
                 f"MX0MOCK{abs(hash(inst.instrument_id)) % 10**6:06d}", inst.descripcion,
                 fiscal.regimen_de(inst.instrument_id),
                 duracion_anios(inst.instrument_id),
                 sensibilidad_reinversion(inst.instrument_id),
                 int(carteras.tiene_desglose(inst.instrument_id))),
            )
        # Las carteras van DESPUES de los instrumentos: la llave foranea las
        # ata a `instruments`, no al reves.
        for fondo, pesos in carteras.COMPOSICION.items():
            conn.executemany(
                "INSERT INTO fund_holdings (instrument_id, ticker, peso)"
                " VALUES (?,?,?)",
                [(fondo, ticker, peso) for ticker, peso in pesos.items()])
        conn.executemany(
            "INSERT INTO instrument_series (instrument_id, fecha, valor_unitario, rend_mensual)"
            " VALUES (?,?,?,?)",
            [(iid, f.isoformat(), v, r) for iid, filas in series.items() for f, v, r in filas],
        )
        # Convenios de pago antes que el core: los servicios guardados los referencian.
        conn.executemany(
            "INSERT INTO billers (biller_id, nombre, categoria, referencia_etiqueta,"
            " referencia_regex, fuente_formato, cobertura, periodicidad, comision)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            [(c.biller_id, c.nombre, c.categoria, c.referencia_etiqueta, c.referencia_regex,
              c.fuente_formato, ",".join(c.cobertura) or "nacional", c.periodicidad, c.comision)
             for c in pagos.CONVENIOS])
        # Semilla aparte para pagos: `rng` sigue exactamente la misma secuencia
        # que antes de abrir ese dominio, así que las inversiones no cambian.
        sembrar_core(conn, rng, np.random.default_rng(db.SEED + 1))
        sembrar_inversiones(conn, rng, series)

    _exportar_parquet(series)
    return target


def _exportar_parquet(series: dict[str, list[tuple[date, float, float]]]) -> None:
    """El .parquet es el entregable de datos; la base es lo que consultan los servicios."""
    try:
        import pandas as pd
    except ImportError:           # pragma: no cover
        print("  (pandas no instalado: me salto el parquet)")
        return
    filas = [
        {"instrument_id": iid, "fecha": f.isoformat(), "valor_unitario": v, "rend_mensual": r}
        for iid, datos in series.items()
        for f, v, r in datos
    ]
    df = pd.DataFrame(filas)
    db.SERIES_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_parquet(db.SERIES_PARQUET, index=False)
    except ImportError:           # pragma: no cover
        df.to_csv(db.SERIES_PARQUET.with_suffix(".csv"), index=False)
        print("  (pyarrow no instalado: exporte CSV en lugar de parquet)")


def verificar(path: Path | None = None) -> list[str]:
    """Invariantes que el resto del repo da por ciertas."""
    problemas: list[str] = []
    with db.session(path, readonly=True) as conn:
        def uno(sql: str) -> int:
            return int(conn.execute(sql).fetchall()[0]["n"])

        if (n := uno("SELECT COUNT(*) n FROM instruments")) != len(INSTRUMENTOS):
            problemas.append(f"instruments: esperaba {len(INSTRUMENTOS)}, hay {n}")
        esperado = len(INSTRUMENTOS) * MESES_SERIE
        if (n := uno("SELECT COUNT(*) n FROM instrument_series")) != esperado:
            problemas.append(f"instrument_series: esperaba {esperado}, hay {n}")
        if (n := uno("SELECT COUNT(*) n FROM clients")) != len(CLIENTES):
            problemas.append(f"clients: esperaba {len(CLIENTES)}, hay {n}")
        if uno("SELECT COUNT(*) n FROM transactions") < 8 * MESES_MOVIMIENTOS * 10:
            problemas.append("transactions: muy pocos movimientos")
        if (n := uno("SELECT COUNT(*) n FROM issuers")) != len(emisoras.EMISORAS):
            problemas.append(f"issuers: esperaba {len(emisoras.EMISORAS)}, hay {n}")
        esperado_factores = len(emisoras.EMISORAS) * len(emisoras.PESOS_RIESGO)
        if (n := uno("SELECT COUNT(*) n FROM issuer_risk_factors")) != esperado_factores:
            problemas.append(
                f"issuer_risk_factors: esperaba {esperado_factores}, hay {n}")
        # El riesgo guardado tiene que seguir siendo el que calcula el modelo.
        # Si alguien toca un fundamental y no vuelve a sembrar, esto lo caza.
        for fila in conn.execute(
                "SELECT ticker, score_riesgo, riesgo_1a5 FROM issuers").fetchall():
            vivo = emisoras.perfil_riesgo(emisoras.POR_TICKER[fila["ticker"]])
            if abs(vivo["score"] - fila["score_riesgo"]) > 0.01 or                     vivo["riesgo_1a5"] != fila["riesgo_1a5"]:
                problemas.append(
                    f"{fila['ticker']}: el riesgo guardado ya no coincide con el "
                    f"calculado ({fila['score_riesgo']} vs {vivo['score']}). "
                    "Corre `make seed`.")
        # Los precios son una foto con fecha. Si envejece demasiado hay que
        # volver a consultarlos, no seguir presentandolos como actuales.
        dias = (FECHA_VALUACION - emisoras.FECHA_PRECIOS).days
        if dias > 90:
            problemas.append(
                f"issuers: la foto de precios tiene {dias} dias. Actualiza "
                "bank/emisoras.py y vuelve a sembrar.")
        if uno("SELECT COUNT(*) n FROM market_sources") == 0:
            problemas.append("market_sources: sin procedencia de los parametros")
        esperado_holdings = sum(len(v) for v in carteras.COMPOSICION.values())
        if (n := uno("SELECT COUNT(*) n FROM fund_holdings")) != esperado_holdings:
            problemas.append(
                f"fund_holdings: esperaba {esperado_holdings}, hay {n}")
        # Este es un producto de fondos: ninguna emisora puede ser contratable.
        contratables = conn.execute(
            "SELECT COUNT(*) n FROM instruments WHERE instrument_id IN"
            " (SELECT ticker FROM issuers)").fetchall()[0]["n"]
        if contratables:
            problemas.append(
                f"{contratables} emisora(s) aparecen como instrumento contratable. "
                "Las acciones sueltas no se venden en este producto.")
        problemas += emisoras.validar_catalogo()
        problemas += carteras.validar()
        vigentes = conn.execute(
            "SELECT COUNT(*) n FROM risk_profiles WHERE client_id='CLI-0001'"
            " AND vigente_hasta >= ?", (FECHA_VALUACION.isoformat(),)
        ).fetchall()[0]["n"]
        if vigentes != 0:
            problemas.append("CLI-0001 no debe tener perfil vigente (rompe el guion del demo)")

        # -------------------------------------------------------------- pagos
        if (n := uno("SELECT COUNT(*) n FROM billers")) != len(pagos.CONVENIOS):
            problemas.append(f"billers: esperaba {len(pagos.CONVENIOS)}, hay {n}")
        for fila in conn.execute("SELECT account_id, clabe_mock FROM accounts").fetchall():
            if (problema := pagos.problema_clabe(fila["clabe_mock"])) is not None:
                problemas.append(f"{fila['account_id']}: CLABE inválida ({problema})")
        for fila in conn.execute(
                "SELECT beneficiary_id, tipo_destino, numero FROM beneficiaries").fetchall():
            valido = (pagos.problema_clabe(fila["numero"]) is None
                      if fila["tipo_destino"] == "clabe"
                      else len(fila["numero"]) == 16 and pagos.luhn_valido(fila["numero"]))
            if not valido:
                problemas.append(f"{fila['beneficiary_id']}: número de destino inválido")
        for fila in conn.execute(
                "SELECT service_id, biller_id, referencia FROM saved_services").fetchall():
            if not pagos.referencia_valida(pagos.CONVENIO_POR_ID[fila["biller_id"]],
                                           fila["referencia"]):
                problemas.append(
                    f"{fila['service_id']}: referencia fuera del formato de {fila['biller_id']}")
        sin_recibo = conn.execute(
            "SELECT client_id FROM clients c WHERE NOT EXISTS (SELECT 1 FROM bills b"
            " JOIN saved_services s USING (service_id)"
            " WHERE s.client_id = c.client_id AND b.estado = 'pendiente')").fetchall()
        if sin_recibo:
            problemas.append("clientes sin recibo pendiente: "
                             + ", ".join(f["client_id"] for f in sin_recibo))
        cfe_guion = conn.execute(
            "SELECT b.fecha_limite FROM bills b JOIN saved_services s USING (service_id)"
            " WHERE s.client_id = 'CLI-0001' AND s.biller_id = 'CFE'"
            " AND b.estado = 'pendiente'").fetchall()
        if not cfe_guion or cfe_guion[0]["fecha_limite"] < FECHA_VALUACION.isoformat():
            problemas.append("CLI-0001 debe tener su recibo de CFE pendiente y sin vencer "
                             "(guion de pagos)")
        if (n := uno("SELECT COUNT(*) n FROM accounts WHERE saldo_disponible < 0")):
            problemas.append(f"{n} cuenta(s) con saldo negativo")
        for row in conn.execute("SELECT instrument_id, MIN(valor_unitario) m FROM"
                                " instrument_series GROUP BY instrument_id").fetchall():
            if row["m"] <= 0:
                problemas.append(f"{row['instrument_id']}: serie con valor no positivo")
    return problemas


def main() -> int:
    ap = argparse.ArgumentParser(description="Genera la base simulada del banco.")
    ap.add_argument("--check", action="store_true", help="solo verificar invariantes")
    args = ap.parse_args()

    if not args.check:
        target = construir()
        print(f"Base simulada escrita en {target}")
        if db.SERIES_PARQUET.exists():
            print(f"Series exportadas a {db.SERIES_PARQUET}")

    problemas = verificar()
    if problemas:
        print("\nInvariantes roto:")
        for p in problemas:
            print(f"  - {p}")
        return 1
    print("Invariantes OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
