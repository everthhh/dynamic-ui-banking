"""Catálogos y reglas del dominio de pagos: bancos SPEI, convenios de servicios,
canales de efectivo y validación de CLABE y tarjeta.

Igual que `bank/emisoras.py`, esto es una foto con procedencia, no un feed:

  * Los códigos de banco (los tres primeros dígitos de una CLABE) son los del
    catálogo público de participantes de SPEI.
  * El dígito verificador de la CLABE es el algoritmo público de Banxico
    (pesos 3-7-1, módulo 10). Una CLABE mal tecleada se rechaza aquí, antes de
    que exista una operación pendiente.
  * Los convenios son empresas reales de México. El formato de referencia de
    CFE (número de servicio de 12 dígitos) y el de telefonía e Infinitum (número
    a 10 dígitos) salen de los recibos públicos: `fuente_formato="publico"`. Los
    demás son longitudes plausibles marcadas `fuente_formato="simulado"`.
  * Comisiones y montos máximos de los corresponsales son estimados.

Las reglas del banco simulado (topes, vigencias) viven al final del archivo:
las usan los servicios para hacerlas valer y el seed para no sembrar datos que
las rompan.
"""

from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Any, NamedTuple

# ---------------------------------------------------------------------------
# bancos participantes de SPEI (código de 3 dígitos -> nombre)
# ---------------------------------------------------------------------------
BANCO_PROPIO = "072"

BANCOS: dict[str, str] = {
    "002": "BANAMEX",
    "012": "BBVA MEXICO",
    "014": "SANTANDER",
    "021": "HSBC",
    "030": "BAJIO",
    "036": "INBURSA",
    "044": "SCOTIABANK",
    "058": "BANREGIO",
    "062": "AFIRME",
    "072": "BANORTE",
    "127": "AZTECA",
    "137": "BANCOPPEL",
    "638": "NU MEXICO",
    "646": "STP",
    "722": "MERCADO PAGO W",
}

PESOS_CLABE = (3, 7, 1) * 6


def digito_verificador_clabe(primeros_17: str) -> int:
    """Algoritmo de Banxico: cada dígito por su peso (3, 7, 1, ...), módulo 10."""
    suma = sum((int(d) * p) % 10 for d, p in zip(primeros_17, PESOS_CLABE))
    return (10 - suma % 10) % 10


def clabe_con_digito(banco: str, plaza: str, cuenta_11: str) -> str:
    base = f"{banco}{plaza}{cuenta_11}"
    if len(base) != 17 or not base.isdigit():
        raise ValueError(f"una CLABE lleva 17 dígitos antes del verificador, llegó {base!r}")
    return base + str(digito_verificador_clabe(base))


def problema_clabe(clabe: str) -> str | None:
    """None si la CLABE es válida; si no, qué tiene mal, escrito para el usuario."""
    if len(clabe) != 18 or not clabe.isdigit():
        return f"una CLABE tiene 18 dígitos y llegaron {len(clabe)} caracteres"
    if clabe[:3] not in BANCOS:
        return f"el código de banco {clabe[:3]} no es un participante de SPEI"
    if digito_verificador_clabe(clabe[:17]) != int(clabe[17]):
        return "el dígito verificador no cuadra (casi siempre es un dígito mal tecleado)"
    return None


def luhn_valido(numero: str) -> bool:
    """Dígito verificador de tarjeta (Luhn)."""
    if not numero.isdigit():
        return False
    total = 0
    for i, d in enumerate(reversed(numero)):
        n = int(d)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def tarjeta_con_luhn(primeros_15: str) -> str:
    for d in "0123456789":
        if luhn_valido(primeros_15 + d):
            return primeros_15 + d
    raise ValueError("no existe dígito Luhn")          # pragma: no cover


def enmascarar(numero: str | None) -> str | None:
    """'•••• 1234'. Las CLABEs, tarjetas y referencias no salen completas."""
    if not numero:
        return None
    return f"•••• {numero[-4:]}"


def normalizar_numero(valor: str) -> str:
    """Quita espacios y guiones: '0721 8000 ...' y '072-180-...' son la misma CLABE."""
    return "".join(ch for ch in str(valor) if ch not in " -\t")


def digitos_deterministas(semilla: str, n: int) -> str:
    """`n` dígitos derivados de `semilla` con SHA-256.

    Sin `rng`: el seed los usa para CLABEs y referencias sin mover la secuencia
    aleatoria de la que dependen las inversiones, y los servicios para que
    consultar dos veces el mismo recibo dé el mismo adeudo.
    """
    salida = ""
    contador = 0
    while len(salida) < n:
        h = hashlib.sha256(f"{semilla}#{contador}".encode("utf-8")).hexdigest()
        salida += "".join(str(int(c, 16) % 10) for c in h)
        contador += 1
    return salida[:n]


# ---------------------------------------------------------------------------
# convenios de pago de servicios
# ---------------------------------------------------------------------------
CATEGORIAS_SERVICIO = ("luz", "agua", "internet", "telefonia", "gas", "television")


class Convenio(NamedTuple):
    biller_id: str
    nombre: str
    categoria: str
    referencia_etiqueta: str           # lo que ve el cliente en el formulario
    digitos_min: int
    digitos_max: int
    fuente_formato: str                # publico | simulado
    cobertura: tuple[str, ...]         # vacía = nacional
    periodicidad: str                  # mensual | bimestral
    comision: float
    monto_tipico: tuple[float, float]  # rango de un recibo, para simular adeudos
    descripcion: str

    @property
    def referencia_regex(self) -> str:
        if self.digitos_min == self.digitos_max:
            return rf"^\d{{{self.digitos_min}}}$"
        return rf"^\d{{{self.digitos_min},{self.digitos_max}}}$"


def referencia_valida(conv: Convenio, referencia: str) -> bool:
    return referencia.isdigit() and conv.digitos_min <= len(referencia) <= conv.digitos_max


CONVENIOS: tuple[Convenio, ...] = (
    Convenio("CFE", "CFE", "luz", "Número de servicio (12 dígitos)", 12, 12,
             "publico", (), "bimestral", 0.0, (280, 2_400),
             "Comisión Federal de Electricidad. El número de servicio viene arriba del recibo."),
    Convenio("TELMEX", "Telmex (Infinitum)", "internet", "Número telefónico a 10 dígitos",
             10, 10, "publico", (), "mensual", 0.0, (389, 1_099),
             "Internet y línea fija. Se paga con el teléfono de la línea."),
    Convenio("IZZI", "izzi", "internet", "Número de cuenta (8 a 10 dígitos)", 8, 10,
             "simulado", (), "mensual", 0.0, (449, 1_199), "Internet, TV y telefonía por cable."),
    Convenio("TOTALPLAY", "Totalplay", "internet", "Número de cuenta (10 dígitos)", 10, 10,
             "simulado", (), "mensual", 0.0, (499, 1_399), "Internet por fibra óptica y TV."),
    Convenio("MEGACABLE", "Megacable", "internet", "Número de suscriptor (8 dígitos)", 8, 8,
             "simulado", (), "mensual", 0.0, (399, 999), "Internet, TV y telefonía por cable."),
    Convenio("TELCEL", "Telcel", "telefonia", "Número celular a 10 dígitos", 10, 10,
             "publico", (), "mensual", 0.0, (299, 1_199), "Plan de renta de telefonía celular."),
    Convenio("ATT", "AT&T México", "telefonia", "Número celular a 10 dígitos", 10, 10,
             "publico", (), "mensual", 0.0, (249, 999), "Plan de renta de telefonía celular."),
    Convenio("SKY", "SKY", "television", "Número de cuenta (12 dígitos)", 12, 12,
             "simulado", (), "mensual", 0.0, (299, 899), "Televisión satelital."),
    Convenio("NATURGY", "Naturgy", "gas", "Número de contrato (10 dígitos)", 10, 10,
             "simulado", (), "mensual", 0.0, (180, 750), "Gas natural por red."),
    # organismos de agua: uno por ciudad de los clientes sintéticos
    Convenio("AYD_MTY", "Agua y Drenaje de Monterrey", "agua", "Número de cuenta (9 dígitos)",
             9, 9, "simulado", ("Monterrey",), "mensual", 0.0, (160, 900),
             "Servicios de Agua y Drenaje de Monterrey."),
    Convenio("SIAPA", "SIAPA", "agua", "Número de cuenta (10 dígitos)", 10, 10, "simulado",
             ("Guadalajara",), "mensual", 0.0, (150, 850), "Agua potable del área metropolitana de Guadalajara."),
    Convenio("SACMEX", "Sistema de Aguas de la Ciudad de México", "agua",
             "Número de cuenta (16 dígitos)", 16, 16, "simulado", ("CDMX",), "bimestral", 0.0,
             (120, 1_100), "Derechos por suministro de agua en la CDMX."),
    Convenio("CEA_QRO", "CEA Querétaro", "agua", "Número de contrato (8 dígitos)", 8, 8,
             "simulado", ("Queretaro",), "mensual", 0.0, (150, 800),
             "Comisión Estatal de Aguas de Querétaro."),
    Convenio("JAPAY", "JAPAY", "agua", "Número de contrato (10 dígitos)", 10, 10, "simulado",
             ("Merida",), "bimestral", 0.0, (120, 700), "Junta de Agua Potable y Alcantarillado de Yucatán."),
    Convenio("AGUA_PUEBLA", "Agua de Puebla", "agua", "Número de cuenta (10 dígitos)", 10, 10,
             "simulado", ("Puebla",), "mensual", 0.0, (150, 850), "Agua potable de la zona metropolitana de Puebla."),
    Convenio("CESPT", "CESPT", "agua", "Número de cuenta (9 dígitos)", 9, 9, "simulado",
             ("Tijuana",), "mensual", 0.0, (180, 950), "Comisión Estatal de Servicios Públicos de Tijuana."),
    Convenio("SAPAL", "SAPAL", "agua", "Número de contrato (8 dígitos)", 8, 8, "simulado",
             ("Leon",), "mensual", 0.0, (150, 800), "Sistema de Agua Potable y Alcantarillado de León."),
)

CONVENIO_POR_ID: dict[str, Convenio] = {c.biller_id: c for c in CONVENIOS}

AGUA_POR_CIUDAD: dict[str, str] = {
    ciudad: c.biller_id for c in CONVENIOS if c.categoria == "agua" for ciudad in c.cobertura
}

# LADA de cada ciudad: los números de teléfono sembrados son de 10 dígitos
# empezando por la clave real de la ciudad.
LADAS: dict[str, str] = {
    "Monterrey": "81", "Guadalajara": "33", "CDMX": "55", "Queretaro": "442",
    "Merida": "999", "Puebla": "222", "Tijuana": "664", "Leon": "477",
}


def cubre(conv: Convenio, ciudad: str | None) -> bool:
    return not conv.cobertura or (ciudad is not None and ciudad in conv.cobertura)


MESES_CORTOS = ("ene", "feb", "mar", "abr", "may", "jun",
                "jul", "ago", "sep", "oct", "nov", "dic")


def _mes_antes(anio: int, mes: int, n: int) -> tuple[int, int]:
    total = anio * 12 + (mes - 1) - n
    return total // 12, total % 12 + 1


def periodo_de(conv: Convenio, hoy: date) -> str:
    """Lo que cubre el recibo vigente: el mes anterior o el bimestre anterior."""
    anio, mes = _mes_antes(hoy.year, hoy.month, 1)
    if conv.periodicidad == "mensual":
        return f"{MESES_CORTOS[mes - 1]} {anio}"
    _, mes_inicio = _mes_antes(hoy.year, hoy.month, 2)
    return f"{MESES_CORTOS[mes_inicio - 1]}–{MESES_CORTOS[mes - 1]} {anio}"


def recibo_simulado(conv: Convenio, referencia: str, hoy: date) -> dict[str, Any]:
    """El adeudo que "responde" el convenio al consultar una referencia.

    Determinista: la misma referencia el mismo día da el mismo recibo. Es lo
    que hace que registrar dos veces un servicio no invente dos adeudos, y que
    el seed no dependa del generador aleatorio.
    """
    d = digitos_deterministas(f"recibo-{conv.biller_id}-{referencia}-{hoy.isoformat()}", 10)
    minimo, maximo = conv.monto_tipico
    return {
        "periodo": periodo_de(conv, hoy),
        "monto": round(minimo + int(d[:6]) / 1_000_000 * (maximo - minimo), 2),
        "fecha_emision": (hoy - timedelta(days=5 + int(d[6:8]) % 10)).isoformat(),
        "fecha_limite": (hoy + timedelta(days=3 + int(d[8:10]) % 18)).isoformat(),
    }


# ---------------------------------------------------------------------------
# canales para meter y sacar efectivo
# ---------------------------------------------------------------------------
class CanalEfectivo(NamedTuple):
    canal_id: str
    nombre: str
    operaciones: tuple[str, ...]       # deposito | retiro
    comision_deposito: float
    monto_maximo_deposito: float
    requiere_referencia: bool          # True: el cliente lleva una referencia a la caja
    como: str
    fuente: str = "estimado"


CANALES_EFECTIVO: tuple[CanalEfectivo, ...] = (
    CanalEfectivo("CAJERO", "Cajeros del banco", ("deposito", "retiro"), 0.0, 30_000, False,
                  "Depósito con tu tarjeta de débito; retiro sin tarjeta con el código de la app."),
    CanalEfectivo("SUCURSAL", "Ventanilla en sucursal", ("deposito",), 0.0, 50_000, False,
                  "Depósito con tu número de cuenta o tarjeta."),
    CanalEfectivo("OXXO", "OXXO", ("deposito",), 15.0, 10_000, True,
                  "Dile al cajero que es un depósito a banco y dale la referencia."),
    CanalEfectivo("SEVEN_ELEVEN", "7-Eleven", ("deposito",), 12.0, 8_000, True,
                  "Depósito a cuenta con la referencia."),
    CanalEfectivo("WALMART", "Walmart, Bodega Aurrera y Sam's Club", ("deposito",), 10.0, 8_000,
                  True, "En cualquier caja, con la referencia."),
    CanalEfectivo("FARMACIAS_AHORRO", "Farmacias del Ahorro", ("deposito",), 10.0, 5_000, True,
                  "Depósito en caja con la referencia."),
    CanalEfectivo("TELECOMM", "Telecomm", ("deposito",), 8.0, 10_000, True,
                  "Depósito en ventanilla con la referencia."),
)

CANAL_POR_ID: dict[str, CanalEfectivo] = {c.canal_id: c for c in CANALES_EFECTIVO}

# ---------------------------------------------------------------------------
# reglas del banco simulado
# ---------------------------------------------------------------------------
# Tope diario de dinero que SALE del patrimonio del cliente (servicios,
# transferencias a terceros, retiros). Los traspasos entre cuentas propias no
# cuentan: el dinero no se va a ningún lado.
TOPE_DIARIO_POR_SEGMENTO: dict[str, float] = {
    "nomina": 50_000, "preferente": 150_000, "patrimonial": 1_000_000, "pyme": 500_000,
}
# Una CLABE que el cliente nunca registró, o que registró hace menos de
# `ESPERA_DESTINO_NUEVO_MIN`, no puede recibir más que esto por operación. Es
# el control contra el fraude más común: "agrega esta cuenta y mándame todo".
TOPE_DESTINO_NUEVO = 20_000.0
ESPERA_DESTINO_NUEVO_MIN = 30
MONTO_MINIMO_TRANSFERENCIA = 1.0
MONTO_MAXIMO_TRANSFERENCIA = 500_000.0
CONCEPTO_LARGO_MAXIMO = 40             # el campo de concepto de SPEI
TITULAR_LARGO_MAXIMO = 60

MULTIPLO_RETIRO = 100                  # los cajeros entregan billetes
MONTO_MINIMO_RETIRO = 100.0
TOPE_RETIRO_SIN_TARJETA = 9_000.0
VIGENCIA_CODIGO_RETIRO_HORAS = 24

VIGENCIA_REFERENCIA_DEPOSITO_HORAS = 72

# Cuentas de las que puede salir un pago, una transferencia a terceros o un
# retiro. La de inversión solo puede traspasar a una cuenta propia.
TIPOS_CUENTA_TRANSACCIONAL = ("cheques", "nomina", "ahorro")
