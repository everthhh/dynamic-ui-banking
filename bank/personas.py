"""Personas sinteticas: los habitos que hay DETRAS de los movimientos.

Antes, `bank/seed.py` sorteaba de 9 a 16 cargos al mes entre ocho categorias
con la misma probabilidad para todos. Un cliente de 18 mil al mes gastaba lo
mismo que uno de 240 mil, la renta aparecia dos meses de dieciocho, ningun
credito se pagaba nunca y ninguna tarjeta tenia historial de pagos. Un perfil
financiero calculado sobre eso dice «tasa de ahorro 93%», y un juez lo nota.

Aqui cada cliente declara HABITOS: como le llega el ingreso, que paga fijo,
en que se le va lo variable, como paga la tarjeta y si barre su excedente a
la cuenta de inversion. `bank/comportamiento.py` los convierte en
movimientos, estados de cuenta y saldos, con una semilla propia por cliente
para que tocar una persona no reacomode a las demas.

Lo que NO hay aqui son conclusiones. Ninguna persona dice «es revolvente»,
«tiene gasto hormiga» o «le sobra efectivo». Eso lo DESCUBRE
`bank/finance/perfil.py` leyendo los movimientos, igual que con un cliente
real. La persona declara que pide delivery ocho veces al mes; el perfil mide
cuanto le cuesta.
"""

from __future__ import annotations

from datetime import date
from typing import NamedTuple

HABITOS_PAGO_TDC = ("totalero", "parcial", "minimo", "atrasado", "segun_liquidez")


class Fijo(NamedTuple):
    """Cargo recurrente: renta, colegiatura, servicios, suscripciones."""
    categoria: str
    descripcion: str
    comercio: str
    monto: float
    dia: int
    medio: str = "debito"                   # debito | tdc
    cada_meses: int = 1                     # 2 = bimestral (luz)
    meses_sin_cargo: tuple[int, ...] = ()   # (7,) = no se cobra en julio
    variacion: float = 0.0                  # desviacion relativa del monto


class Variable(NamedTuple):
    """Compras de frecuencia y ticket variables en un tipo de comercio."""
    categoria: str
    comercio: str
    compras_mes: float                      # promedio mensual (Poisson)
    ticket: float                           # ticket medio (lognormal alrededor)
    cambio_desde: date | None = None        # desde aqui cambia la frecuencia...
    factor_cambio: float = 1.0              # ...por este factor: un habito nuevo


class Credito(NamedTuple):
    producto: str                           # auto | hipotecario | personal | nomina
    monto: float
    plazo_meses: int
    meses_pagados: int                      # a la fecha de valuacion


class Tarjeta(NamedTuple):
    limite_x_ingreso: float                 # nunca mas de 3x: regla de services/banking.py
    tasa_anual: float
    dia_corte: int
    habito_pago: str                        # uno de HABITOS_PAGO_TDC


class Persona(NamedTuple):
    client_id: str
    fecha_nacimiento: date
    ocupacion: str
    dependientes: int
    tipo_ingreso: str                       # nomina | negocio
    variabilidad_ingreso: float             # desviacion relativa mensual (negocio)
    fijos: tuple[Fijo, ...]
    variables: tuple[Variable, ...]
    tarjeta: Tarjeta
    uso_tdc: float                          # parte de lo variable que va a la TDC
    credito: Credito | None
    barre_excedente: bool
    colchon_meses: float                    # meses de gasto que deja en la cuenta de uso
    # Patrimonio previo a la ventana, en meses de ingreso. Antes salia de un
    # sorteo igual para todos y un auxiliar de 18 mil al mes aparecia con un
    # cuarto de millon en fondos.
    efectivo_inversion_meses: float = 1.0   # parado en la cuenta de inversion
    invertido_meses: float = 5.0            # ya invertido en fondos (si tiene perfil)
    # True: lo que barre termina en sus fondos. False: se queda parado en la
    # cuenta de inversion, que es el caso comun y el que el perfil detecta.
    invierte_barrido: bool = False


# ---------------------------------------------------------------------------
# atajos para no repetir los mismos cargos en ocho personas
# ---------------------------------------------------------------------------
def _servicios(internet: float, movil: float, luz_bimestral: float, agua_gas: float,
               *, variacion_luz: float = 0.15) -> tuple[Fijo, ...]:
    return (
        Fijo("servicios", "Internet y TV", "Proveedor de internet (sim)", internet, 8),
        Fijo("servicios", "Telefonía móvil", "Operador móvil (sim)", movil, 12, medio="tdc"),
        Fijo("servicios", "Luz", "Comisión de electricidad (sim)", luz_bimestral, 20,
             cada_meses=2, variacion=variacion_luz),
        Fijo("servicios", "Agua y gas", "Servicios municipales (sim)", agua_gas, 22,
             variacion=0.10),
    )


def _sub(descripcion: str, comercio: str, monto: float, dia: int) -> Fijo:
    """Suscripcion digital: siempre a la tarjeta de credito, siempre el mismo monto."""
    return Fijo("entretenimiento", descripcion, comercio, monto, dia, medio="tdc")


JUNIO_2026 = date(2026, 6, 1)

PERSONAS: tuple[Persona, ...] = (
    # Ahorra, pero no invierte: lo que le sobra se barre a la cuenta de
    # inversion y ahi se queda. Desde junio sale mas a comer. Es el cliente
    # del guion («tengo 80 mil pesos parados»).
    Persona(
        "CLI-0001", date(1992, 4, 17), "Gerente de mercadotecnia", 0, "nomina", 0.0,
        fijos=(
            Fijo("renta", "Renta de departamento", "Arrendador (sim)", 14_500, 2),
            *_servicios(749, 399, 780, 420),
            _sub("Streaming de video", "Plataforma de video (sim)", 219, 3),
            _sub("Música en streaming", "Plataforma de música (sim)", 129, 7),
            _sub("Gimnasio", "Cadena de gimnasios (sim)", 890, 5),
            _sub("Almacenamiento en la nube", "Nube personal (sim)", 49, 15),
        ),
        variables=(
            Variable("super", "Supermercado (sim)", 5, 820),
            Variable("super", "Tienda de conveniencia (sim)", 4, 95),
            Variable("restaurantes", "Restaurante (sim)", 4, 520, JUNIO_2026, 1.5),
            Variable("restaurantes", "Cafetería (sim)", 8, 78),
            Variable("restaurantes", "Delivery de comida (sim)", 5, 230, JUNIO_2026, 2.2),
            Variable("transporte", "Gasolinera (sim)", 4, 750),
            Variable("transporte", "Caseta de peaje (sim)", 3, 120),
            Variable("salud", "Farmacia (sim)", 2, 380),
            Variable("entretenimiento", "Cine (sim)", 1.5, 320),
            Variable("entretenimiento", "Boletos para eventos (sim)", 0.5, 1_600),
        ),
        tarjeta=Tarjeta(2.0, 0.389, 12, "totalero"),
        uso_tdc=0.60,
        credito=Credito("auto", 380_000, 60, 22),
        barre_excedente=True, colchon_meses=1.2,
        efectivo_inversion_meses=2.5, invertido_meses=0.0,
    ),

    # Gana bien y paga renta y colegiaturas. Usa mucho la tarjeta y la paga
    # a medias aunque le sobra liquidez: intereses por descuido.
    Persona(
        "CLI-0002", date(1978, 9, 3), "Director comercial", 2, "nomina", 0.0,
        fijos=(
            Fijo("renta", "Renta de casa", "Arrendador (sim)", 38_000, 1),
            Fijo("educacion", "Colegiaturas", "Colegio (sim)", 16_500, 5, meses_sin_cargo=(7,)),
            *_servicios(1_299, 1_100, 2_400, 900),
            Fijo("servicios", "Servicio doméstico", "Servicio doméstico (sim)", 6_000, 28),
            Fijo("salud", "Seguro de gastos médicos", "Aseguradora (sim)", 3_200, 10, medio="tdc"),
            _sub("Streaming de video", "Plataforma de video (sim)", 299, 3),
            _sub("Música en streaming", "Plataforma de música (sim)", 179, 7),
            _sub("Club deportivo", "Club deportivo (sim)", 2_400, 4),
        ),
        variables=(
            Variable("super", "Supermercado (sim)", 6, 2_100),
            Variable("super", "Club de precios (sim)", 2, 3_800),
            Variable("restaurantes", "Restaurante (sim)", 8, 1_450),
            Variable("restaurantes", "Cafetería (sim)", 6, 95),
            Variable("transporte", "Gasolinera (sim)", 6, 1_100),
            Variable("transporte", "App de movilidad (sim)", 6, 180),
            Variable("salud", "Farmacia (sim)", 3, 650),
            Variable("entretenimiento", "Boletos para eventos (sim)", 1, 4_500),
            Variable("entretenimiento", "Agencia de viajes (sim)", 0.25, 28_000),
        ),
        tarjeta=Tarjeta(2.5, 0.329, 20, "parcial"),
        uso_tdc=0.70,
        credito=None,
        barre_excedente=True, colchon_meses=1.5,
        efectivo_inversion_meses=1.0, invertido_meses=20.0, invierte_barrido=True,
    ),

    # Primer empleo formal. Cuarto compartido, credito de nomina, y una
    # tarjeta que paga al minimo. Muchas compras chicas: cafe, conveniencia,
    # apps de transporte y delivery.
    Persona(
        "CLI-0003", date(1999, 1, 22), "Analista de soporte técnico", 0, "nomina", 0.0,
        fijos=(
            Fijo("renta", "Renta de cuarto", "Arrendador (sim)", 6_200, 3),
            *_servicios(399, 249, 260, 180),
            _sub("Streaming de video", "Plataforma de video (sim)", 219, 3),
            _sub("Videojuegos en línea", "Plataforma de videojuegos (sim)", 179, 9),
            _sub("Música en streaming", "Plataforma de música (sim)", 129, 7),
        ),
        variables=(
            Variable("super", "Supermercado (sim)", 3, 650),
            Variable("super", "Tienda de conveniencia (sim)", 10, 65),
            Variable("restaurantes", "Cafetería (sim)", 12, 62),
            Variable("restaurantes", "Delivery de comida (sim)", 7, 190),
            Variable("restaurantes", "Restaurante (sim)", 1, 350),
            Variable("transporte", "App de movilidad (sim)", 14, 95),
            Variable("salud", "Farmacia (sim)", 1, 280),
            Variable("entretenimiento", "Bar (sim)", 2, 420),
            Variable("entretenimiento", "Cine (sim)", 1, 190),
        ),
        tarjeta=Tarjeta(1.6, 0.469, 5, "minimo"),
        uso_tdc=0.75,
        credito=Credito("nomina", 60_000, 24, 9),
        barre_excedente=True, colchon_meses=1.0,
        efectivo_inversion_meses=0.5, invertido_meses=1.5,
    ),

    # Hipoteca y una hija en la escuela. Totalera, ordenada. Su perfil de
    # inversion vencio y ya no puede mover lo que tiene invertido.
    Persona(
        "CLI-0004", date(1987, 6, 9), "Arquitecta", 1, "nomina", 0.0,
        fijos=(
            Fijo("educacion", "Colegiatura", "Colegio (sim)", 5_800, 5, meses_sin_cargo=(7,)),
            *_servicios(699, 450, 900, 520),
            _sub("Streaming de video", "Plataforma de video (sim)", 219, 3),
        ),
        variables=(
            Variable("super", "Supermercado (sim)", 5, 1_300),
            Variable("super", "Club de precios (sim)", 1, 2_600),
            Variable("restaurantes", "Restaurante (sim)", 3, 700),
            Variable("restaurantes", "Cafetería (sim)", 3, 85),
            Variable("transporte", "Gasolinera (sim)", 5, 850),
            Variable("salud", "Farmacia (sim)", 2, 450),
            Variable("salud", "Consulta médica (sim)", 0.4, 1_200),
            Variable("entretenimiento", "Cine (sim)", 1, 480),
            Variable("entretenimiento", "Boletos para eventos (sim)", 0.3, 1_800),
        ),
        tarjeta=Tarjeta(2.2, 0.359, 18, "totalero"),
        uso_tdc=0.65,
        credito=Credito("hipotecario", 1_600_000, 240, 38),
        barre_excedente=True, colchon_meses=1.4,
        efectivo_inversion_meses=1.0, invertido_meses=10.0,
    ),

    # Vive al dia. Desde junio pide mas delivery y sale mas de noche. Paga la
    # tarjeta tarde o al minimo, y a veces no la paga.
    Persona(
        "CLI-0005", date(2001, 11, 30), "Auxiliar administrativo", 0, "nomina", 0.0,
        fijos=(
            Fijo("renta", "Renta de departamento", "Arrendador (sim)", 5_200, 2),
            *_servicios(349, 199, 900, 120, variacion_luz=0.30),
            _sub("Streaming de video", "Plataforma de video (sim)", 219, 3),
            _sub("Música en streaming", "Plataforma de música (sim)", 129, 7),
            _sub("Streaming de deportes", "Plataforma de deportes (sim)", 299, 11),
        ),
        variables=(
            Variable("super", "Supermercado (sim)", 3, 520),
            Variable("super", "Tienda de conveniencia (sim)", 12, 70),
            Variable("restaurantes", "Delivery de comida (sim)", 8, 175, JUNIO_2026, 2.0),
            Variable("restaurantes", "Cafetería (sim)", 6, 60),
            Variable("restaurantes", "Restaurante (sim)", 1, 380),
            Variable("transporte", "App de movilidad (sim)", 12, 85),
            Variable("salud", "Farmacia (sim)", 1, 220),
            Variable("entretenimiento", "Bar (sim)", 3, 450, JUNIO_2026, 1.5),
            Variable("entretenimiento", "Tienda en línea (sim)", 2, 650),
        ),
        tarjeta=Tarjeta(1.4, 0.499, 25, "atrasado"),
        uso_tdc=0.60,
        credito=Credito("personal", 45_000, 36, 11),
        barre_excedente=False, colchon_meses=0.0,
        efectivo_inversion_meses=1.3, invertido_meses=0.8,
    ),

    # Patrimonio alto, totalera, cero deuda. No barre nada: el excedente de
    # 18 meses se le acumula en la cuenta de cheques sin rendir.
    Persona(
        "CLI-0006", date(1974, 2, 14), "Socia directora de despacho legal", 2, "nomina", 0.0,
        fijos=(
            Fijo("educacion", "Colegiaturas universitarias", "Universidad (sim)", 32_000, 5,
                 meses_sin_cargo=(7,)),
            Fijo("servicios", "Mantenimiento residencial", "Administración del condominio (sim)",
                 3_500, 4),
            Fijo("servicios", "Servicio doméstico", "Servicio doméstico (sim)", 8_000, 28),
            *_servicios(1_499, 1_400, 3_200, 1_300),
            Fijo("salud", "Seguro de gastos médicos", "Aseguradora (sim)", 6_800, 10, medio="tdc"),
            _sub("Streaming de video", "Plataforma de video (sim)", 299, 3),
            _sub("Música familiar", "Plataforma de música (sim)", 229, 7),
            _sub("Club deportivo", "Club deportivo (sim)", 3_800, 4),
        ),
        variables=(
            Variable("super", "Supermercado (sim)", 6, 2_600),
            Variable("super", "Club de precios (sim)", 2, 5_200),
            Variable("restaurantes", "Restaurante (sim)", 10, 1_700),
            Variable("transporte", "Gasolinera (sim)", 6, 1_300),
            Variable("salud", "Farmacia (sim)", 3, 900),
            Variable("salud", "Consulta médica (sim)", 0.5, 2_500),
            Variable("entretenimiento", "Boletos para eventos (sim)", 1, 5_000),
            Variable("entretenimiento", "Agencia de viajes (sim)", 0.35, 45_000),
        ),
        tarjeta=Tarjeta(2.8, 0.319, 8, "totalero"),
        uso_tdc=0.80,
        credito=None,
        barre_excedente=False, colchon_meses=0.0,
        efectivo_inversion_meses=1.5, invertido_meses=25.0,
    ),

    # Dueno de taller: el ingreso llega en depositos de clientes y cambia
    # mucho de un mes a otro. Paga la tarjeta completa cuando le alcanza.
    Persona(
        "CLI-0007", date(1981, 8, 5), "Dueño de taller mecánico", 3, "negocio", 0.32,
        fijos=(
            Fijo("renta", "Renta de casa", "Arrendador (sim)", 16_000, 3),
            Fijo("educacion", "Colegiaturas", "Colegio (sim)", 9_600, 5, meses_sin_cargo=(7,)),
            *_servicios(699, 900, 2_800, 900, variacion_luz=0.25),
            _sub("Streaming de video", "Plataforma de video (sim)", 219, 3),
        ),
        variables=(
            Variable("super", "Supermercado (sim)", 5, 1_500),
            Variable("super", "Club de precios (sim)", 1, 3_200),
            Variable("restaurantes", "Restaurante (sim)", 4, 800),
            Variable("transporte", "Gasolinera (sim)", 8, 900),
            Variable("transporte", "Caseta de peaje (sim)", 4, 150),
            Variable("salud", "Farmacia (sim)", 2, 500),
            Variable("salud", "Consulta médica (sim)", 0.3, 900),
            Variable("entretenimiento", "Cine (sim)", 1, 900),
        ),
        tarjeta=Tarjeta(1.8, 0.409, 15, "segun_liquidez"),
        uso_tdc=0.55,
        credito=Credito("personal", 150_000, 36, 14),
        barre_excedente=True, colchon_meses=1.2,
        efectivo_inversion_meses=1.0, invertido_meses=4.0,
    ),

    # Sin deudas y con buen margen. Acumula suscripciones digitales sin
    # darse cuenta.
    Persona(
        "CLI-0008", date(1995, 3, 28), "Ingeniera de software", 0, "nomina", 0.0,
        fijos=(
            Fijo("renta", "Renta de departamento", "Arrendador (sim)", 12_500, 2),
            *_servicios(599, 399, 600, 350),
            _sub("Streaming de video", "Plataforma de video (sim)", 299, 3),
            _sub("Música en streaming", "Plataforma de música (sim)", 129, 7),
            _sub("Plataforma de series", "Plataforma de series (sim)", 179, 10),
            _sub("Videojuegos en línea", "Plataforma de videojuegos (sim)", 249, 9),
            _sub("Almacenamiento en la nube", "Nube personal (sim)", 49, 15),
            _sub("Gimnasio", "Cadena de gimnasios (sim)", 650, 5),
            _sub("App de idiomas", "App de idiomas (sim)", 199, 18),
        ),
        variables=(
            Variable("super", "Supermercado (sim)", 4, 1_000),
            Variable("super", "Tienda de conveniencia (sim)", 6, 80),
            Variable("restaurantes", "Restaurante (sim)", 4, 650),
            Variable("restaurantes", "Cafetería (sim)", 10, 85),
            Variable("restaurantes", "Delivery de comida (sim)", 5, 210),
            Variable("transporte", "App de movilidad (sim)", 10, 110),
            Variable("salud", "Farmacia (sim)", 1, 400),
            Variable("entretenimiento", "Cine (sim)", 2, 260),
            Variable("entretenimiento", "Boletos para eventos (sim)", 0.5, 1_500),
            Variable("entretenimiento", "Tienda en línea (sim)", 2, 900),
        ),
        tarjeta=Tarjeta(2.0, 0.369, 22, "totalero"),
        uso_tdc=0.70,
        credito=None,
        barre_excedente=True, colchon_meses=1.5,
        efectivo_inversion_meses=1.0, invertido_meses=5.0, invierte_barrido=True,
    ),
)

POR_CLIENTE: dict[str, Persona] = {p.client_id: p for p in PERSONAS}


def validar() -> list[str]:
    """Lo que una persona tiene que cumplir para que el seed tenga sentido."""
    problemas: list[str] = []
    for p in PERSONAS:
        if p.tarjeta.habito_pago not in HABITOS_PAGO_TDC:
            problemas.append(f"{p.client_id}: habito de pago desconocido {p.tarjeta.habito_pago!r}")
        if not 0 < p.tarjeta.limite_x_ingreso <= 3:
            problemas.append(f"{p.client_id}: el limite de la TDC rebasa 3x el ingreso")
        if not 1 <= p.tarjeta.dia_corte <= 28:
            problemas.append(f"{p.client_id}: dia de corte fuera de 1-28")
        if p.tipo_ingreso not in ("nomina", "negocio"):
            problemas.append(f"{p.client_id}: tipo de ingreso desconocido {p.tipo_ingreso!r}")
        if not 0 <= p.uso_tdc <= 1:
            problemas.append(f"{p.client_id}: uso_tdc fuera de 0-1")
        for f in p.fijos:
            if not 1 <= f.dia <= 28:
                problemas.append(f"{p.client_id}: {f.descripcion} con dia {f.dia} fuera de 1-28")
    return problemas
