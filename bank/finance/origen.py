"""De donde sale el dinero, y por que cambia el calculo.

No es lo mismo invertir un excedente de la cuenta de ahorro que invertir con
una tarjeta de credito, y hasta ahora el sistema trataba los dos casos igual.
Dos diferencias, y las dos entran a la formula:

  1. **Costo financiero.** Con dinero prestado la deuda crece sola. La
     referencia contra la que se mide "ganar" deja de ser lo aportado y pasa
     a ser lo que vas a deber. Un portafolio que rinde 9% financiado con una
     tarjeta al 42% pierde en el 100% de las trayectorias, y la simulacion
     tiene que decirlo.

  2. **Capacidad de perdida.** Con recursos propios, una caida se aguanta
     esperando. Con deuda no: la mensualidad sigue llegando. Por eso el
     origen apalancado topa el perfil en conservador, sin importar que haya
     contestado el cliente en el perfilador.

La regla dura es una condicion de arbitraje, no un capricho: si el
rendimiento esperado neto del portafolio no supera el costo del credito, la
operacion tiene valor esperado negativo y `bank/finance/idoneidad.py` la
bloquea. Con el catalogo actual el instrumento mas rentable espera 14.9% y el
credito mas barato cuesta 10.75%, asi que casi todo credito queda bloqueado.
Eso es el resultado correcto, no un efecto secundario.
"""

from __future__ import annotations

from typing import Any, NamedTuple


class Origen(NamedTuple):
    clave: str
    etiqueta: str
    apalancado: bool
    costo_anual: float              # tasa del credito; 0 si es dinero propio
    tasa_referencia_anual: float    # lo que ese dinero rinde donde esta hoy
    tope_riesgo_1a5: int
    nota: str


# Perfil maximo admisible cuando el dinero es prestado. Aunque el cliente
# salga agresivo en el perfilador, con deuda encima no lo es.
TOPE_PERFIL_APALANCADO = "conservador"

ORIGENES: tuple[Origen, ...] = (
    Origen("inversion", "Cuenta de inversión", False, 0.0, 0.0, 5,
           "Efectivo que ya está en la cuenta de inversión sin rendimiento."),
    Origen("ahorro", "Cuenta de ahorro", False, 0.0, 0.0250, 5,
           "Dinero propio. La referencia es lo poco que ya gana en la cuenta."),
    Origen("cheques", "Cuenta de cheques", False, 0.0, 0.0, 5,
           "Dinero propio sin rendimiento: cualquier cosa le gana a estar parado."),
    Origen("nomina", "Cuenta de nómina", False, 0.0, 0.0, 5,
           "Dinero propio. Ojo con el colchón de emergencia antes de invertirlo."),
    Origen("credito_hipotecario", "Crédito hipotecario", True, 0.1075, 0.0, 1,
           "Deuda garantizada y barata, pero sigue siendo deuda."),
    Origen("credito_auto", "Crédito automotriz", True, 0.1350, 0.0, 1,
           "El activo financiado se deprecia; invertir encima duplica el riesgo."),
    Origen("credito_nomina", "Crédito de nómina", True, 0.2150, 0.0, 1,
           "Se descuenta directo del sueldo: la mensualidad no es negociable."),
    Origen("credito_personal", "Crédito personal", True, 0.2890, 0.0, 1,
           "Tasa muy por encima de lo que espera rendir cualquier portafolio."),
    Origen("tarjeta_credito", "Tarjeta de crédito", True, 0.4200, 0.0, 1,
           "El financiamiento más caro del banco. Invertir con esto destruye valor."),
)

POR_CLAVE: dict[str, Origen] = {o.clave: o for o in ORIGENES}

# tipo de cuenta en `accounts.tipo` -> clave de origen
TIPO_CUENTA_A_ORIGEN = {
    "inversion": "inversion",
    "ahorro": "ahorro",
    "cheques": "cheques",
    "nomina": "nomina",
}

# producto en `loans.producto` -> clave de origen
PRODUCTO_CREDITO_A_ORIGEN = {
    "hipotecario": "credito_hipotecario",
    "auto": "credito_auto",
    "nomina": "credito_nomina",
    "personal": "credito_personal",
}

ORIGEN_POR_DEFECTO = "inversion"


class OrigenInvalido(ValueError):
    pass


def resolver(clave: str | None) -> Origen:
    if clave is None:
        return POR_CLAVE[ORIGEN_POR_DEFECTO]
    if clave not in POR_CLAVE:
        raise OrigenInvalido(
            f"origen desconocido: {clave!r}. Opciones: {', '.join(POR_CLAVE)}."
        )
    return POR_CLAVE[clave]


def desde_cuenta(tipo_cuenta: str) -> Origen:
    """Traduce el `tipo` de una cuenta bancaria a un origen."""
    return resolver(TIPO_CUENTA_A_ORIGEN.get(tipo_cuenta, ORIGEN_POR_DEFECTO))


def desde_credito(producto: str, tasa_anual: float | None = None) -> Origen:
    """Origen a partir de un credito real del cliente.

    Si viene la tasa contratada se usa esa y no la generica: dos clientes con
    credito personal no pagan lo mismo.
    """
    base = resolver(PRODUCTO_CREDITO_A_ORIGEN.get(producto, "credito_personal"))
    if tasa_anual is None:
        return base
    return base._replace(costo_anual=float(tasa_anual))


def umbral_rentabilidad(origen: Origen) -> float:
    """Rendimiento anual que el portafolio debe superar para que valga la pena."""
    return origen.costo_anual if origen.apalancado else origen.tasa_referencia_anual


def ficha(origen: Origen) -> dict[str, Any]:
    return {
        "origen": origen.clave,
        "etiqueta": origen.etiqueta,
        "apalancado": origen.apalancado,
        "costo_anual": round(origen.costo_anual, 6),
        "tasa_referencia_anual": round(origen.tasa_referencia_anual, 6),
        "umbral_rentabilidad": round(umbral_rentabilidad(origen), 6),
        "tope_riesgo_1a5": origen.tope_riesgo_1a5,
        "tope_perfil": TOPE_PERFIL_APALANCADO if origen.apalancado else None,
        "nota": origen.nota,
    }
