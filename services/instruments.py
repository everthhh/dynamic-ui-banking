"""Servicios de catalogo de instrumentos."""

from __future__ import annotations

from typing import Any

from bank import db
from bank.instrumentos import BY_ID
from services.errors import NotFound, ServiceError

CLASES_VALIDAS = ("deuda_gub", "deuda_corp", "renta_variable",
                  "fondo_deuda", "fondo_rv", "etf", "pagare")
LIQUIDEZ_VALIDA = ("diaria", "24h", "48h", "al_vencimiento")
ORDEN_VALIDO = ("rendimiento", "riesgo", "volatilidad", "comision", "minimo", "nombre")


def list_instruments(
    clase: str | None = None,
    riesgo_max: int | None = None,
    riesgo_min: int | None = None,
    liquidez: str | None = None,
    monto_disponible: float | None = None,
    ordenar_por: str = "rendimiento",
    limite: int = 24,
) -> dict[str, Any]:
    """Catalogo filtrado. Lo que alimenta `inv.InstrumentTable`.

    `monto_disponible` filtra por monto minimo de inversion: no tiene sentido
    mostrarle al cliente un bono de 100 mil si trae 20 mil.
    """
    if clase is not None and clase not in CLASES_VALIDAS:
        raise ServiceError(f"clase inválida: {clase!r}.",
                           sugerencia=f"Clases válidas: {', '.join(CLASES_VALIDAS)}.")
    if liquidez is not None and liquidez not in LIQUIDEZ_VALIDA:
        raise ServiceError(f"liquidez inválida: {liquidez!r}.",
                           sugerencia=f"Valores válidos: {', '.join(LIQUIDEZ_VALIDA)}.")
    if ordenar_por not in ORDEN_VALIDO:
        raise ServiceError(f"`ordenar_por` inválido: {ordenar_por!r}.",
                           sugerencia=f"Opciones: {', '.join(ORDEN_VALIDO)}.")
    for nombre, valor in (("riesgo_max", riesgo_max), ("riesgo_min", riesgo_min)):
        if valor is not None and not 1 <= valor <= 5:
            raise ServiceError(f"`{nombre}` debe estar entre 1 y 5.")
    if not 1 <= limite <= 100:
        raise ServiceError("`limite` debe estar entre 1 y 100.")

    sql = ["SELECT * FROM instruments WHERE 1 = 1"]
    params: list[Any] = []
    if clase:
        sql.append("AND clase = ?"); params.append(clase)
    if riesgo_max is not None:
        sql.append("AND riesgo_1a5 <= ?"); params.append(riesgo_max)
    if riesgo_min is not None:
        sql.append("AND riesgo_1a5 >= ?"); params.append(riesgo_min)
    if liquidez:
        sql.append("AND liquidez = ?"); params.append(liquidez)
    if monto_disponible is not None:
        sql.append("AND monto_minimo <= ?"); params.append(monto_disponible)

    orden = {
        "rendimiento": "(rend_esperado_anual - comision_anual) DESC",
        "riesgo": "riesgo_1a5 ASC, rend_esperado_anual DESC",
        "volatilidad": "volatilidad_anual ASC",
        "comision": "comision_anual ASC",
        "minimo": "monto_minimo ASC",
        "nombre": "nombre ASC",
    }[ordenar_por]
    sql.append(f"ORDER BY {orden} LIMIT ?")
    params.append(limite)

    with db.session(readonly=True) as conn:
        filas = db.query(conn, " ".join(sql), tuple(params))

    return {
        "filtros": {"clase": clase, "riesgo_max": riesgo_max, "riesgo_min": riesgo_min,
                    "liquidez": liquidez, "monto_disponible": monto_disponible,
                    "ordenar_por": ordenar_por},
        "total": len(filas),
        "instrumentos": [
            {
                "instrument_id": f["instrument_id"],
                "nombre": f["nombre"],
                "clase": f["clase"],
                "emisor": f["emisor"],
                "rend_esperado_anual": f["rend_esperado_anual"],
                "rend_neto_anual": round(f["rend_esperado_anual"] - f["comision_anual"], 6),
                "volatilidad_anual": f["volatilidad_anual"],
                "comision_anual": f["comision_anual"],
                "riesgo_1a5": f["riesgo_1a5"],
                "liquidez": f["liquidez"],
                "plazo_dias": f["plazo_dias"],
                "monto_minimo": f["monto_minimo"],
                "descripcion": f["descripcion"],
            }
            for f in filas
        ],
    }


def get_instrument_factsheet(instrument_id: str, meses_historia: int = 60) -> dict[str, Any]:
    """Detalle de un instrumento + su serie. Lo que alimenta `inv.FactSheet`."""
    if instrument_id not in BY_ID:
        raise NotFound(
            f"No existe el instrumento {instrument_id!r}.",
            sugerencia="Usa `list_instruments` para ver los IDs disponibles.",
        )
    if not 12 <= meses_historia <= 120:
        raise ServiceError("`meses_historia` debe estar entre 12 y 120.")

    with db.session(readonly=True) as conn:
        inst = db.query_one(
            conn, "SELECT * FROM instruments WHERE instrument_id = ?", (instrument_id,))
        serie = db.query(
            conn,
            "SELECT fecha, valor_unitario, rend_mensual FROM instrument_series"
            " WHERE instrument_id = ? ORDER BY fecha DESC LIMIT ?",
            (instrument_id, meses_historia))
    serie.reverse()

    inicio, fin = serie[0]["valor_unitario"], serie[-1]["valor_unitario"]
    anios = len(serie) / 12
    cagr = (fin / inicio) ** (1 / anios) - 1 if anios > 0 else 0.0
    peores = sorted(serie, key=lambda s: s["rend_mensual"])[:3]

    return {
        **inst,
        "historia": {
            "meses": len(serie),
            "desde": serie[0]["fecha"],
            "hasta": serie[-1]["fecha"],
            "serie": serie,
            "cagr_realizado": round(cagr, 6),
            "peores_meses": [
                {"fecha": p["fecha"], "rend_mensual": round(p["rend_mensual"], 6)}
                for p in peores
            ],
        },
        "disclaimer": "Serie sintética generada con semilla fija. No es historia real.",
    }
