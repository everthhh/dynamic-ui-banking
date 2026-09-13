"""De habitos a movimientos: la simulacion mes a mes de un cliente.

Recibe una `Persona` (bank/personas.py) y produce lo que un banco guardaria de
ese cliente durante la ventana del seed:

  * movimientos de la cuenta de uso: nomina o depositos, renta, colegiaturas,
    servicios, mensualidades de credito, pagos de tarjeta y barridos;
  * compras con tarjeta de credito, intereses y comisiones, en el MISMO libro
    de movimientos (con `card_id`): el cliente ve un solo historial;
  * estados de cuenta mensuales de la tarjeta: saldo al corte, pago minimo,
    cuanto pago, cuando, y con cuantos dias de atraso.

Es una simulacion por eventos y no una tabla de sorteos independientes porque
los habitos tienen consecuencias que se encadenan: pagar el minimo genera
intereses el mes siguiente; una tarjeta llena rechaza la compra y el cargo se
va a la cuenta; una cuenta vacia no alcanza para pagar la tarjeta y el pago
llega tarde, con comision. Nada de eso esta escrito en la persona: sale de
simular sus habitos en orden cronologico.
"""

from __future__ import annotations

import heapq
import itertools
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

from bank.personas import Persona

DIAS_PARA_PAGAR = 20
PAGO_MINIMO_PCT = 0.05
PAGO_MINIMO_PISO = 300.0
COMISION_PAGO_TARDIO = 450.0
AGUINALDO_DIAS = 15                  # minimo de ley: 15 dias de salario
ACTUALIZACION_RENTA = 0.04           # la renta sube cada enero
TICKET_SIGMA = 0.35                  # dispersion lognormal del ticket

# Un ingreso de negocio no llega parejo: enero y febrero flojos, fin de ano fuerte.
ESTACIONALIDAD_NEGOCIO = {1: 0.75, 2: 0.85, 11: 1.10, 12: 1.20}

ETIQUETA_CREDITO = {
    "auto": "crédito automotriz",
    "hipotecario": "crédito hipotecario",
    "personal": "crédito personal",
    "nomina": "crédito de nómina",
}

# Dentro del mismo instante primero entra el dinero y despues sale.
_ORDEN = {"ingreso": 0, "fijo": 1, "credito": 1, "compra": 2, "corte": 3,
          "pago_tdc": 4, "cierre_mes": 5}


def meses_calendario(n: int, ultimo_mes: date) -> list[date]:
    """Primeros de mes de los `n` meses que terminan en el mes de `ultimo_mes`."""
    y, m = ultimo_mes.year, ultimo_mes.month
    salida: list[date] = []
    for _ in range(n):
        salida.append(date(y, m, 1))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(salida))


def ultimo_dia(mes: date) -> date:
    siguiente = date(mes.year + mes.month // 12, mes.month % 12 + 1, 1)
    return siguiente - timedelta(days=1)


def pago_mensual(monto: float, tasa_anual: float, plazo_meses: int) -> float:
    """Mensualidad fija de un credito amortizable."""
    i = tasa_anual / 12
    return monto * i / (1 - (1 + i) ** -plazo_meses)


def saldo_insoluto(monto: float, tasa_anual: float, plazo_meses: int, pagadas: int) -> float:
    i = tasa_anual / 12
    return monto * ((1 + i) ** plazo_meses - (1 + i) ** pagadas) / ((1 + i) ** plazo_meses - 1)


@dataclass
class Resultado:
    movimientos: list[dict[str, Any]]      # en orden cronologico; `tarjeta` marca los de la TDC
    estados_cuenta: list[dict[str, Any]]
    saldo_cuenta: float
    saldo_tarjeta: float
    barrido_total: float
    compras_rechazadas: int
    cargos_fijos_rechazados: list[str]


class _Simulacion:
    def __init__(self, persona: Persona, *, ingreso_mensual: float, saldo_inicial: float,
                 limite_tdc: float, last4_tdc: str, pago_credito: float | None,
                 meses: list[date], rng: np.random.Generator) -> None:
        self.p = persona
        self.ingreso = ingreso_mensual
        self.limite = limite_tdc
        self.last4 = last4_tdc
        self.pago_credito = pago_credito
        self.meses = meses
        self.rng = rng
        self.fin = datetime.combine(ultimo_dia(meses[-1]), datetime.max.time())

        self.saldo = saldo_inicial
        self.tdc = 0.0
        self.compras_periodo = 0.0
        self.pagos_periodo = 0.0
        self.salidas_mes = 0.0
        self.salidas_mes_anterior = 0.0
        self.barrido_total = 0.0
        self.compras_rechazadas = 0
        self.fijos_rechazados: list[str] = []

        self.movimientos: list[dict[str, Any]] = []
        self.estados: list[dict[str, Any]] = []
        self._cola: list[tuple] = []
        self._seq = itertools.count()

    # ------------------------------------------------------------------ agenda
    def _programar(self, cuando: datetime, tipo: str, **datos: Any) -> None:
        if cuando <= self.fin:
            heapq.heappush(self._cola, (cuando, _ORDEN[tipo], next(self._seq), tipo, datos))

    def _programar_mes(self, idx: int, mes: date) -> None:
        p, rng = self.p, self.rng
        fin_mes = ultimo_dia(mes)

        def el_dia(dia: int, hora: int = 10, minuto: int = 0) -> datetime:
            return datetime(mes.year, mes.month, min(dia, fin_mes.day), hora, minuto)

        if p.tipo_ingreso == "nomina":
            for dia in (15, fin_mes.day):
                self._programar(el_dia(dia, 9), "ingreso",
                                monto=self.ingreso / 2 * (1 + float(rng.normal(0, 0.01))),
                                categoria="nomina", descripcion="Depósito de nómina",
                                comercio="Empleador (sim)")
            if mes.month == 12:
                self._programar(el_dia(18, 9), "ingreso",
                                monto=self.ingreso / 30 * AGUINALDO_DIAS,
                                categoria="nomina", descripcion="Aguinaldo",
                                comercio="Empleador (sim)")
        else:
            sigma = p.variabilidad_ingreso
            factor = float(rng.lognormal(-sigma ** 2 / 2, sigma))
            total = self.ingreso * max(0.3, factor) * ESTACIONALIDAD_NEGOCIO.get(mes.month, 1.0)
            k = int(rng.integers(3, 7))
            for parte in rng.dirichlet(np.full(k, 2.0)):
                self._programar(el_dia(int(rng.integers(1, 29)), int(rng.integers(9, 19))),
                                "ingreso", monto=total * float(parte), categoria="honorarios",
                                descripcion="Depósito de cliente",
                                comercio="Cliente del negocio (sim)")

        anios = mes.year - self.meses[0].year
        for f in p.fijos:
            if mes.month in f.meses_sin_cargo or mes.month % f.cada_meses:
                continue
            monto = f.monto * (1 + float(rng.normal(0, f.variacion))) if f.variacion else f.monto
            if f.categoria == "renta":
                monto *= (1 + ACTUALIZACION_RENTA) ** anios
            self._programar(el_dia(f.dia), "fijo", monto=max(1.0, monto), categoria=f.categoria,
                            descripcion=f.descripcion, comercio=f.comercio, medio=f.medio)

        # La mensualidad solo existe desde que el credito se abrio.
        if p.credito and self.pago_credito and len(self.meses) - idx <= p.credito.meses_pagados:
            self._programar(el_dia(10), "credito", monto=self.pago_credito,
                            descripcion=f"Pago de {ETIQUETA_CREDITO[p.credito.producto]}")

        for v in p.variables:
            factor = v.factor_cambio if v.cambio_desde and mes >= v.cambio_desde else 1.0
            for _ in range(int(rng.poisson(v.compras_mes * factor))):
                cuando = el_dia(int(rng.integers(1, fin_mes.day + 1)),
                                int(rng.integers(8, 23)), int(rng.integers(0, 60)))
                ticket = v.ticket * float(rng.lognormal(-TICKET_SIGMA ** 2 / 2, TICKET_SIGMA))
                self._programar(cuando, "compra", monto=max(15.0, ticket), categoria=v.categoria,
                                comercio=v.comercio,
                                medio="tdc" if rng.random() < p.uso_tdc else "debito")

        self._programar(el_dia(p.tarjeta.dia_corte, 23, 50), "corte")
        self._programar(datetime.combine(fin_mes, datetime.min.time()).replace(hour=23, minute=55),
                        "cierre_mes")

    # ------------------------------------------------------------ libro mayor
    def _asentar(self, cuando: datetime, tipo: str, monto: float, categoria: str,
                 descripcion: str, comercio: str | None, *, tarjeta: bool) -> None:
        # `saldo_posterior` es el del producto que se movio: la cuenta, o lo
        # utilizado de la tarjeta.
        self.movimientos.append({
            "fecha": cuando.isoformat(timespec="seconds"), "tipo": tipo, "monto": monto,
            "categoria": categoria, "descripcion": descripcion, "comercio": comercio,
            "saldo_posterior": round(self.tdc if tarjeta else self.saldo, 2),
            "tarjeta": tarjeta,
        })

    def _cargar_cuenta(self, cuando: datetime, monto: float, categoria: str,
                       descripcion: str, comercio: str | None) -> bool:
        if self.saldo + 1e-9 < monto:
            return False
        self.saldo -= monto
        if categoria != "traspaso":
            self.salidas_mes += monto
        self._asentar(cuando, "cargo", monto, categoria, descripcion, comercio, tarjeta=False)
        return True

    def _cargar_tdc(self, cuando: datetime, monto: float, categoria: str,
                    descripcion: str, comercio: str | None) -> bool:
        if self.tdc + monto > self.limite + 1e-9:
            return False
        self.tdc += monto
        self.compras_periodo += monto
        self._asentar(cuando, "cargo", monto, categoria, descripcion, comercio, tarjeta=True)
        return True

    # ---------------------------------------------------------------- eventos
    def _ingreso(self, cuando: datetime, *, monto: float, categoria: str,
                 descripcion: str, comercio: str) -> None:
        monto = round(monto, 2)
        self.saldo += monto
        self._asentar(cuando, "abono", monto, categoria, descripcion, comercio, tarjeta=False)

    def _fijo(self, cuando: datetime, *, monto: float, categoria: str, descripcion: str,
              comercio: str, medio: str) -> None:
        monto = round(monto, 2)
        intentos = (self._cargar_tdc, self._cargar_cuenta) if medio == "tdc" \
            else (self._cargar_cuenta, self._cargar_tdc)
        if not any(cargar(cuando, monto, categoria, descripcion, comercio) for cargar in intentos):
            self.fijos_rechazados.append(f"{cuando.date()} {descripcion} ${monto:,.2f}")

    def _credito(self, cuando: datetime, *, monto: float, descripcion: str) -> None:
        if not self._cargar_cuenta(cuando, round(monto, 2), "credito", descripcion, "Banco (sim)"):
            self.fijos_rechazados.append(f"{cuando.date()} {descripcion} ${monto:,.2f}")

    def _compra(self, cuando: datetime, *, monto: float, categoria: str, comercio: str,
                medio: str) -> None:
        monto = round(monto, 2)
        credito = ("Compra con tarjeta de crédito", self._cargar_tdc)
        debito = ("Compra con tarjeta de débito", self._cargar_cuenta)
        for descripcion, cargar in ((credito, debito) if medio == "tdc" else (debito, credito)):
            if cargar(cuando, monto, categoria, descripcion, comercio):
                return
        self.compras_rechazadas += 1

    def _corte(self, cuando: datetime) -> None:
        anterior = self.estados[-1] if self.estados else None
        intereses = comisiones = 0.0
        if anterior is not None and anterior["saldo_al_corte"] > 0:
            no_pagado = anterior["saldo_al_corte"] - anterior["pagado"]
            if no_pagado > 0.5:
                intereses = round(no_pagado * self.p.tarjeta.tasa_anual / 12, 2)
            # Para el siguiente corte ya paso la fecha limite: si no hay pago,
            # si llego tarde o si no cubrio el minimo, hay comision.
            if (anterior["fecha_pago"] is None or anterior["dias_atraso"] > 0
                    or anterior["pagado"] + 0.5 < anterior["pago_minimo"]):
                comisiones = COMISION_PAGO_TARDIO
        if intereses:
            self.tdc += intereses
            self._asentar(cuando, "cargo", intereses, "costo_financiero",
                          "Intereses de la tarjeta de crédito", None, tarjeta=True)
        if comisiones:
            self.tdc += comisiones
            self._asentar(cuando, "cargo", comisiones, "costo_financiero",
                          "Comisión por pago tardío", None, tarjeta=True)

        saldo = round(self.tdc, 2)
        minimo = round(min(saldo, max(PAGO_MINIMO_PISO,
                                      saldo * PAGO_MINIMO_PCT + intereses + comisiones)), 2)
        limite_pago = cuando.date() + timedelta(days=DIAS_PARA_PAGAR)
        self.estados.append({
            "fecha_corte": cuando.date().isoformat(),
            "fecha_limite_pago": limite_pago.isoformat(),
            "saldo_anterior": anterior["saldo_al_corte"] if anterior else 0.0,
            "compras": round(self.compras_periodo, 2),
            "intereses": intereses,
            "comisiones": comisiones,
            "pagos_periodo": round(self.pagos_periodo, 2),
            "saldo_al_corte": saldo,
            "pago_minimo": minimo,
            "pago_no_intereses": saldo,
            "pagado": 0.0,
            "fecha_pago": None,
            "dias_atraso": 0,
        })
        self.compras_periodo = self.pagos_periodo = 0.0
        if saldo <= 0.5:
            return

        dias = -int(self.rng.integers(0, 4))            # normalmente, unos dias antes
        if self.p.tarjeta.habito_pago == "atrasado":
            sorteo = self.rng.random()
            if sorteo < 0.12:
                return                                   # ese mes no paga
            if sorteo < 0.60:
                dias = int(self.rng.integers(3, 16))
        pago_en = datetime.combine(limite_pago + timedelta(days=dias), datetime.min.time())
        self._programar(pago_en.replace(hour=13), "pago_tdc", indice=len(self.estados) - 1)

    def _pago_tdc(self, cuando: datetime, *, indice: int) -> None:
        estado = self.estados[indice]
        habito, rng = self.p.tarjeta.habito_pago, self.rng
        total, minimo = estado["saldo_al_corte"], estado["pago_minimo"]
        if habito == "totalero":
            objetivo = total
        elif habito == "parcial":
            objetivo = max(minimo, total * float(rng.uniform(0.40, 0.75)))
        elif habito in ("minimo", "atrasado"):
            objetivo = minimo * float(rng.uniform(1.0, 1.12))
        else:                                            # segun_liquidez
            libre = self.saldo - 0.5 * self.salidas_mes_anterior
            objetivo = total if libre >= total else max(minimo, libre)

        monto = round(min(objetivo, self.tdc, max(0.0, self.saldo)), 2)
        if monto <= 0:
            return
        self.saldo -= monto
        self.tdc -= monto
        self.pagos_periodo += monto
        self.salidas_mes += monto
        self._asentar(cuando, "cargo", monto, "pago_tarjeta",
                      f"Pago tarjeta de crédito •••• {self.last4}", None, tarjeta=False)
        estado["pagado"] = round(estado["pagado"] + monto, 2)
        estado["fecha_pago"] = cuando.date().isoformat()
        estado["dias_atraso"] = max(
            0, (cuando.date() - date.fromisoformat(estado["fecha_limite_pago"])).days)

    def _cierre_mes(self, cuando: datetime) -> None:
        if self.p.barre_excedente:
            # El colchon se mide contra el mes mas caro de los dos ultimos: un
            # mes barato no debe dejar la cuenta corta para la renta del siguiente.
            colchon = self.p.colchon_meses * max(self.salidas_mes, self.salidas_mes_anterior)
            excedente = round(self.saldo - colchon, 2)
            if excedente > 500 and self._cargar_cuenta(
                    cuando, excedente, "traspaso", "Traspaso a cuenta de inversión", None):
                self.barrido_total += excedente
        self.salidas_mes_anterior = self.salidas_mes
        self.salidas_mes = 0.0

    # ------------------------------------------------------------------ correr
    def correr(self) -> Resultado:
        for idx, mes in enumerate(self.meses):
            self._programar_mes(idx, mes)
        while self._cola:
            cuando, _orden, _seq, tipo, datos = heapq.heappop(self._cola)
            getattr(self, f"_{tipo}")(cuando, **datos)
        return Resultado(
            movimientos=self.movimientos,
            estados_cuenta=self.estados,
            saldo_cuenta=round(self.saldo, 2),
            saldo_tarjeta=round(self.tdc, 2),
            barrido_total=round(self.barrido_total, 2),
            compras_rechazadas=self.compras_rechazadas,
            cargos_fijos_rechazados=self.fijos_rechazados,
        )


def simular(persona: Persona, *, ingreso_mensual: float, saldo_inicial: float,
            limite_tdc: float, last4_tdc: str, pago_credito: float | None,
            meses: list[date], rng: np.random.Generator) -> Resultado:
    return _Simulacion(persona, ingreso_mensual=ingreso_mensual, saldo_inicial=saldo_inicial,
                       limite_tdc=limite_tdc, last4_tdc=last4_tdc, pago_credito=pago_credito,
                       meses=meses, rng=rng).correr()
