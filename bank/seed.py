"""Generador de la base simulada del banco. Determinista: semilla fija.

    python -m bank.seed            # escribe data/bank.sqlite + data/series.parquet
    python -m bank.seed --check    # solo verifica que lo generado sea consistente

Lo que produce:
  * 24 instrumentos (bank/instrumentos.py)
  * 120 meses de series por instrumento, GBM con correlacion entre clases
  * 8 clientes con cuentas, tarjetas y creditos, y 18 meses de movimientos y
    estados de cuenta de tarjeta simulados desde sus habitos
    (bank/personas.py + bank/comportamiento.py)
  * perfiles de riesgo: algunos vigentes, algunos vencidos, uno inexistente
  * posiciones de inversion y un historial corto de ordenes ejecutadas
  * pagos: convenios, servicios con su recibo, contactos y el historial de
    pagos derivado de los cargos de servicios que ya produce la simulacion

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

from bank import carteras, comportamiento, db, emisoras, mercado, pagos, personas
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
# Los habitos de cada uno (en que gasta, como paga la tarjeta) viven en
# bank/personas.py, con el mismo client_id.
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

# Tasa por producto de credito. Son las mismas que usa bank/finance/origen.py
# como costo del dinero prestado.
TASA_POR_PRODUCTO = {"auto": 0.135, "hipotecario": 0.1075, "personal": 0.289, "nomina": 0.215}

# Presupuestos del cliente del guion. Solo CLI-0001, a proposito: asi el demo
# muestra el caso "ya configuro presupuestos" y el caso "todavia no", que es
# el mas comun.
PRESUPUESTOS_CLI_0001 = (("super", 5_000.0), ("restaurantes", 3_000.0),
                         ("entretenimiento", 3_000.0))


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
# pagos: servicios guardados, recibos, contactos e historial de pagos
# ---------------------------------------------------------------------------
# Pagos no agrega movimientos: los cargos de servicios ya los produce la
# simulacion de habitos (bank/comportamiento.py). Lo que se siembra aqui es lo
# que un banco guarda ALREDEDOR de esos cargos: el convenio y la referencia de
# cada servicio, su recibo vigente, los contactos para transferir y la
# operacion de pago de cada cargo de servicio que salio de la cuenta. Nada de
# eso usa `rng`: sale de `pagos.digitos_deterministas`, asi que ni el perfil
# financiero ni las inversiones cambian.
CONTACTOS_SEMILLA = (
    # (alias, titular, banco). NU se siembra como tarjeta; los demas, como CLABE.
    ("Mamá", "María Guadalupe Torres", "012"),
    ("Casero", "Inmobiliaria Cumbres (sim)", "014"),
    ("Hermano", "Carlos Iván Ruiz", "638"),
    ("Tanda", "Rosa Elena Garza", "002"),
    ("Taller", "Refaccionaria El Pistón (sim)", "021"),
    ("Colegio", "Colegio Montessori del Valle (sim)", "044"),
)
ALIAS_SERVICIO = {"luz": "Luz de la casa", "telefonia": "Mi celular"}
SERVICIOS_CON_TELEFONO = ("TELMEX", "TELCEL", "ATT")
# Cargo fijo de servicios de una persona (bank/personas.py:_servicios) -> la
# categoria de convenio que lo cobra.
CATEGORIA_CONVENIO_POR_CARGO = {
    "Luz": "luz",
    "Internet y TV": "internet",
    "Telefonía móvil": "telefonia",
    "Agua y gas": "agua",
}


def _clabe_de_cuenta(idx: int, inversion: bool) -> str:
    """CLABE mock con digito verificador valido: banco 072, plaza 180 o 181."""
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


def _sembrar_contactos(conn: sqlite3.Connection, cid: str, idx: int) -> None:
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
        contactos.append((f"BEN-{idx:04d}-{k}", alias, titular, tipo, numero, banco))
    siguiente = (idx + 1) % len(CLIENTES)
    contactos.append((f"BEN-{idx:04d}-2", CLIENTES[siguiente][1].split()[0], CLIENTES[siguiente][1],
                      "clabe", _clabe_de_cuenta(siguiente, inversion=False), pagos.BANCO_PROPIO))
    conn.executemany(
        "INSERT INTO beneficiaries (beneficiary_id, client_id, alias, titular, tipo_destino,"
        " numero, banco_codigo, creado_en) VALUES (?,?,?,?,?,?,?,?)",
        [(b, cid, alias, titular, tipo, numero, banco, creado)
         for b, alias, titular, tipo, numero, banco in contactos])


def _sembrar_recibos(conn: sqlite3.Connection, cid: str, idx: int, ciudad: str,
                     servicios: list[tuple[str, pagos.Convenio]]) -> None:
    """El recibo vigente de cada servicio, consultado igual que lo haria `register_service`.

    Algunos quedan vencidos a proposito (el ultimo servicio de un cliente de
    cada tres) para que el panel tenga los dos casos. El CFE de CLI-0001 vence
    en cuatro dias: es el recibo del guion de pagos.
    """
    for k, (service_id, conv) in enumerate(servicios):
        recibo = pagos.recibo_simulado(conv, _referencia_semilla(conv, cid, ciudad), FECHA_VALUACION)
        if idx % 3 == 1 and k == len(servicios) - 1:
            recibo["fecha_limite"] = (FECHA_VALUACION - timedelta(days=2)).isoformat()
        if cid == "CLI-0001" and conv.biller_id == "CFE":
            recibo["fecha_limite"] = (FECHA_VALUACION + timedelta(days=4)).isoformat()
        conn.execute(
            "INSERT INTO bills (bill_id, service_id, periodo, monto, fecha_emision, fecha_limite)"
            " VALUES (?,?,?,?,?,?)",
            (f"BIL-{idx:04d}-{k}", service_id, recibo["periodo"], recibo["monto"],
             recibo["fecha_emision"], recibo["fecha_limite"]))


def _sembrar_pagos_historicos(conn: sqlite3.Connection, cid: str, uso: str,
                              servicios: list[tuple[str, pagos.Convenio]],
                              movimientos: list[dict], pago_n: int) -> int:
    """Una operacion `ejecutada` por cada cargo de servicio que salio de la cuenta.

    Se deriva de los movimientos que ya simulo `bank/comportamiento.py`, sin
    tocarlos. Los cargos que fueron a la tarjeta de credito no generan
    operacion: esos no salieron de la cuenta. Devuelve el ultimo folio usado.
    """
    por_categoria = {conv.categoria: (service_id, conv) for service_id, conv in servicios}
    for mov in movimientos:
        if mov["tarjeta"] or mov["tipo"] != "cargo" or mov["categoria"] != "servicios":
            continue
        servicio = por_categoria.get(CATEGORIA_CONVENIO_POR_CARGO.get(mov["descripcion"], ""))
        if servicio is None:
            continue
        service_id, conv = servicio
        pago_n += 1
        momento = mov["fecha"]
        folio = f"PG-{momento[:4]}-{pago_n:06d}"
        conn.execute(
            "INSERT INTO payments (payment_id, folio, client_id, account_id, tipo, estado, monto,"
            " comision, concepto, service_id, creada_en, ejecutada_en, idempotency_key,"
            " confirmation_token_hash) VALUES (?,?,?,?,'servicio','ejecutada',?,0,?,?,?,?,?,?)",
            (f"PAY-SEED-{pago_n:06d}", folio, cid, uso, mov["monto"], f"Pago {conv.nombre}",
             service_id, momento, momento, f"seed-{cid}-{folio}",
             hashlib.sha256(f"tok-{folio}-seed".encode("utf-8")).hexdigest()))
    return pago_n


# ---------------------------------------------------------------------------
# core bancario
# ---------------------------------------------------------------------------
def sembrar_core(
    conn: sqlite3.Connection, rng: np.random.Generator
) -> tuple[dict[str, list[str]], dict[str, float]]:
    """Clientes, cuentas, tarjetas y creditos; los movimientos salen de simular.

    El `rng` global solo decide lo que no es habito (saldos iniciales y
    terminaciones de tarjeta). Los movimientos usan una semilla propia por
    cliente, `[SEED, idx]`: recalibrar una persona no reacomoda a las demas.

    Devuelve dos cosas por cliente: los cargos fijos que sus habitos no
    alcanzaron a pagar (vacio es lo correcto; `construir` decide que hacer si
    no lo es) y lo que barrio a sus fondos, que `sembrar_inversiones` suma a
    sus posiciones.
    """
    rechazos: dict[str, list[str]] = {}
    a_fondos: dict[str, float] = {}
    txn_n = 0
    pago_n = 0
    meses = comportamiento.meses_calendario(
        MESES_MOVIMIENTOS, FECHA_VALUACION - timedelta(days=1))

    for idx, (cid, nombre, segmento, ingreso, _horizonte, perfil) in enumerate(CLIENTES):
        persona = personas.POR_CLIENTE[cid]
        ingreso = float(ingreso)
        alta = date(2017 + idx % 6, 1 + (idx * 3) % 12, 1 + (idx * 5) % 27)
        conn.execute(
            "INSERT INTO clients (client_id, nombre, fecha_alta, segmento, ciudad,"
            " rfc_mock, ingreso_mensual, horizonte_meses, fecha_nacimiento, ocupacion,"
            " dependientes) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (cid, nombre, alta.isoformat(), segmento, CIUDADES[idx],
             f"XXXX{persona.fecha_nacimiento.strftime('%y%m%d')}{chr(65 + idx)}{idx}A",
             ingreso, _horizonte, persona.fecha_nacimiento.isoformat(), persona.ocupacion,
             persona.dependientes),
        )

        uso = f"ACC-{idx * 2 + 1:04d}"
        inv = f"ACC-{idx * 2 + 2:04d}"
        saldo_uso_inicial = round(ingreso * float(rng.uniform(0.4, 2.2)), 2)
        # Efectivo SIN invertir en la cuenta de inversion al inicio de la
        # ventana; los barridos de fin de mes se le suman. Quien no tiene
        # perfil lleva un piso: es el cliente del guion ("tengo 80 mil parados").
        saldo_inv = ingreso * persona.efectivo_inversion_meses * float(rng.uniform(0.9, 1.1))
        if perfil is None:
            saldo_inv = max(saldo_inv, ingreso * 2.5)
        last4_debito = f"{int(rng.integers(1000, 9999))}"
        last4_credito = f"{int(rng.integers(1000, 9999))}"

        tipo_uso = "nomina" if segmento == "nomina" else "cheques"
        for account_id, tipo, clabe in ((uso, tipo_uso, _clabe_de_cuenta(idx, inversion=False)),
                                        (inv, "inversion", _clabe_de_cuenta(idx, inversion=True))):
            conn.execute(
                "INSERT INTO accounts (account_id, client_id, tipo, clabe_mock, moneda,"
                " saldo_disponible, saldo_liquidado, abierta_en) VALUES (?,?,?,?,?,?,?,?)",
                (account_id, cid, tipo, clabe, "MXN", 0.0, 0.0, alta.isoformat()),
            )

        # Tarjetas. El limite nunca pasa de 3x el ingreso: es la misma regla que
        # aplica `set_card_limit`, y antes el seed la rompia.
        tarjeta = persona.tarjeta
        limite = round(ingreso * tarjeta.limite_x_ingreso, -3)
        card_debito = f"CRD-{idx * 2 + 1:04d}"
        card_credito = f"CRD-{idx * 2 + 2:04d}"
        conn.executemany(
            "INSERT INTO cards (card_id, client_id, account_id, tipo, last4, limite_credito,"
            " saldo_utilizado, tasa_anual, dia_corte, dia_pago) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [(card_debito, cid, uso, "debito", last4_debito, None, 0.0, None, None, None),
             (card_credito, cid, uso, "credito", last4_credito, limite, 0.0,
              tarjeta.tasa_anual, tarjeta.dia_corte,
              (tarjeta.dia_corte + comportamiento.DIAS_PARA_PAGAR - 1) % 28 + 1)],
        )

        # Credito: va antes de simular porque su mensualidad sale de la cuenta.
        pago_credito: float | None = None
        if persona.credito is not None:
            c = persona.credito
            tasa = TASA_POR_PRODUCTO[c.producto]
            pago_credito = round(comportamiento.pago_mensual(c.monto, tasa, c.plazo_meses), 2)
            conn.execute(
                "INSERT INTO loans (loan_id, client_id, producto, monto_original, saldo_insoluto,"
                " tasa_anual, plazo_meses, pago_mensual, mensualidades_pagadas, abierto_en)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"LON-{idx:04d}", cid, c.producto, float(c.monto),
                 round(comportamiento.saldo_insoluto(c.monto, tasa, c.plazo_meses,
                                                     c.meses_pagados), 2),
                 tasa, c.plazo_meses, pago_credito, c.meses_pagados,
                 (FECHA_VALUACION - timedelta(days=30 * c.meses_pagados)).isoformat()),
            )

        sim = comportamiento.simular(
            persona, ingreso_mensual=ingreso, saldo_inicial=saldo_uso_inicial,
            limite_tdc=limite, last4_tdc=last4_credito, pago_credito=pago_credito,
            meses=meses, rng=np.random.default_rng([db.SEED, idx]))
        if sim.cargos_fijos_rechazados:
            rechazos[cid] = sim.cargos_fijos_rechazados

        filas = []
        for mov in sim.movimientos:
            txn_n += 1
            filas.append((f"TXN-{txn_n:06d}", uso, card_credito if mov["tarjeta"] else None,
                          mov["fecha"], mov["tipo"], mov["monto"], mov["categoria"],
                          mov["descripcion"], mov["comercio"], mov["saldo_posterior"]))
        conn.executemany(
            "INSERT INTO transactions (txn_id, account_id, card_id, fecha, tipo, monto,"
            " categoria, descripcion, comercio, saldo_posterior)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)", filas)

        conn.executemany(
            "INSERT INTO card_statements (statement_id, card_id, client_id, fecha_corte,"
            " fecha_limite_pago, saldo_anterior, compras, intereses, comisiones,"
            " pagos_periodo, saldo_al_corte, pago_minimo, pago_no_intereses, pagado,"
            " fecha_pago, dias_atraso) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(f"EDC-{card_credito[4:]}-{e['fecha_corte'][:7]}", card_credito, cid,
              e["fecha_corte"], e["fecha_limite_pago"], e["saldo_anterior"], e["compras"],
              e["intereses"], e["comisiones"], e["pagos_periodo"], e["saldo_al_corte"],
              e["pago_minimo"], e["pago_no_intereses"], e["pagado"], e["fecha_pago"],
              e["dias_atraso"])
             for e in sim.estados_cuenta])

        if persona.invierte_barrido:
            a_fondos[cid] = sim.barrido_total
            saldo_inv_final = round(saldo_inv, 2)
        else:
            saldo_inv_final = round(saldo_inv + sim.barrido_total, 2)
        conn.executemany(
            "UPDATE accounts SET saldo_disponible = ?, saldo_liquidado = ? WHERE account_id = ?",
            [(sim.saldo_cuenta, sim.saldo_cuenta, uso),
             (saldo_inv_final, saldo_inv_final, inv)])
        conn.execute("UPDATE cards SET saldo_utilizado = ? WHERE card_id = ?",
                     (sim.saldo_tarjeta, card_credito))

        if cid == "CLI-0001":
            hoy_iso = FECHA_VALUACION.isoformat()
            conn.executemany(
                "INSERT INTO budgets (budget_id, client_id, categoria, monto_mensual,"
                " creado_en, actualizado_en) VALUES (?,?,?,?,?,?)",
                [(f"BUD-{idx:04d}-{k}", cid, categoria, monto, hoy_iso, hoy_iso)
                 for k, (categoria, monto) in enumerate(PRESUPUESTOS_CLI_0001)])
        ciudad = CIUDADES[idx]
        servicios = _sembrar_servicios(conn, cid, idx, ciudad, segmento)
        _sembrar_contactos(conn, cid, idx)
        _sembrar_recibos(conn, cid, idx, ciudad, servicios)
        pago_n = _sembrar_pagos_historicos(conn, cid, uso, servicios, sim.movimientos, pago_n)
    return rechazos, a_fondos


# ---------------------------------------------------------------------------
# inversiones
# ---------------------------------------------------------------------------
def sembrar_inversiones(
    conn: sqlite3.Connection,
    rng: np.random.Generator,
    series: dict[str, list[tuple[date, float, float]]],
    a_fondos: dict[str, float] | None = None,
) -> None:
    for idx, (cid, _n, _seg, ingreso, horizonte, perfil) in enumerate(CLIENTES):
        inv = f"ACC-{idx * 2 + 2:04d}"
        barrido = (a_fondos or {}).get(cid, 0.0)

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
            if barrido:
                # Iba a sus fondos, pero no tiene: se queda como efectivo.
                conn.execute(
                    "UPDATE accounts SET saldo_disponible = saldo_disponible + ?,"
                    " saldo_liquidado = saldo_liquidado + ? WHERE account_id = ?",
                    (barrido, barrido, inv))
            continue
        score = perfil[1]
        candidatos = [i for i in INSTRUMENTOS if i.riesgo_1a5 <= max(1, score // 20 + 1)]
        elegidos = rng.choice(len(candidatos), size=int(rng.integers(2, 5)), replace=False)
        capital = float(ingreso) * personas.POR_CLIENTE[cid].invertido_meses \
            * float(rng.uniform(0.8, 1.2)) + barrido
        if capital <= 0:
            continue
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
def construir(path: Path | None = None, *, estricto: bool = True,
              rechazos: dict[str, list[str]] | None = None) -> Path:
    """Escribe la base completa.

    `estricto=False` es para calibrar personas: en lugar de fallar cuando un
    cliente no alcanza a pagar sus cargos fijos, deja la base escrita y reporta
    los rechazos en `rechazos`.
    """
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
        sin_pagar, a_fondos = sembrar_core(conn, rng)
        if rechazos is not None:
            rechazos.update(sin_pagar)
        if sin_pagar and estricto:
            detalle = "; ".join(f"{cid}: {', '.join(v[:2])}" for cid, v in sin_pagar.items())
            raise ValueError(
                "Con sus habitos, estos clientes no alcanzan a pagar sus cargos fijos "
                f"({detalle}). Recalibra sus personas en bank/personas.py.")
        sembrar_inversiones(conn, rng, series, a_fondos)

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
        def uno(sql: str, params: tuple = ()) -> int:
            return int(conn.execute(sql, params).fetchall()[0]["n"])

        if (n := uno("SELECT COUNT(*) n FROM instruments")) != len(INSTRUMENTOS):
            problemas.append(f"instruments: esperaba {len(INSTRUMENTOS)}, hay {n}")
        esperado = len(INSTRUMENTOS) * MESES_SERIE
        if (n := uno("SELECT COUNT(*) n FROM instrument_series")) != esperado:
            problemas.append(f"instrument_series: esperaba {esperado}, hay {n}")
        if (n := uno("SELECT COUNT(*) n FROM clients")) != len(CLIENTES):
            problemas.append(f"clients: esperaba {len(CLIENTES)}, hay {n}")
        if uno("SELECT COUNT(*) n FROM transactions") < 8 * MESES_MOVIMIENTOS * 10:
            problemas.append("transactions: muy pocos movimientos")

        # --------------------------------------------- habitos y su simulacion
        problemas += personas.validar()
        sin_persona = [c[0] for c in CLIENTES if c[0] not in personas.POR_CLIENTE]
        if sin_persona:
            problemas.append(f"clientes sin persona en bank/personas.py: {', '.join(sin_persona)}")
        negativos = uno("SELECT COUNT(*) n FROM transactions"
                        " WHERE card_id IS NULL AND saldo_posterior < -0.005")
        if negativos:
            problemas.append(f"{negativos} movimientos dejan una cuenta en negativo")
        for fila in conn.execute(
                "SELECT card_id FROM cards WHERE tipo = 'credito'"
                " AND saldo_utilizado > limite_credito * 1.10").fetchall():
            problemas.append(f"{fila['card_id']}: utilizado muy por encima del limite")
        for fila in conn.execute(
                "SELECT c.card_id, (SELECT COUNT(*) FROM card_statements s"
                "  WHERE s.card_id = c.card_id) n"
                " FROM cards c WHERE c.tipo = 'credito'").fetchall():
            if fila["n"] < MESES_MOVIMIENTOS - 1:
                problemas.append(f"{fila['card_id']}: solo {fila['n']} estados de cuenta")
        # El saldo de la cuenta de uso es exactamente donde termino su libro.
        for fila in conn.execute(
                "SELECT a.account_id, a.saldo_disponible,"
                " (SELECT t.saldo_posterior FROM transactions t"
                "   WHERE t.account_id = a.account_id AND t.card_id IS NULL"
                "   ORDER BY t.fecha DESC, t.txn_id DESC LIMIT 1) ultimo"
                " FROM accounts a WHERE a.tipo IN ('cheques', 'nomina')").fetchall():
            if fila["ultimo"] is not None and abs(fila["ultimo"] - fila["saldo_disponible"]) > 0.01:
                problemas.append(
                    f"{fila['account_id']}: el saldo no coincide con su ultimo movimiento")
        if (n := uno("SELECT COUNT(*) n FROM transactions WHERE categoria = 'renta'"
                     " AND account_id = 'ACC-0003'")) < MESES_MOVIMIENTOS:
            problemas.append(f"CLI-0002 deberia pagar renta cada mes (hay {n} pagos)")

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
        if uno("SELECT COUNT(*) n FROM payments WHERE tipo = 'servicio'") == 0:
            problemas.append("payments: no se derivó ningún pago de servicio de la simulación")
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
