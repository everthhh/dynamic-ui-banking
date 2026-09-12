"""Errores de la capa de servicios.

El mensaje de un `ServiceError` va de vuelta al modelo como `tool_result` con
`is_error=true`. Por eso se escriben para que el modelo pueda corregirse solo:
que dicen que estuvo mal y cuales son las opciones validas, no solo que fallo.
"""

from __future__ import annotations


class ServiceError(Exception):
    """Falla esperada y explicable. Nunca un bug."""

    def __init__(self, mensaje: str, *, codigo: str = "invalid_request",
                 sugerencia: str | None = None) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo
        self.sugerencia = sugerencia

    def to_dict(self) -> dict[str, str]:
        d = {"error": self.codigo, "mensaje": self.mensaje}
        if self.sugerencia:
            d["sugerencia"] = self.sugerencia
        return d

    def __str__(self) -> str:         # lo que ve el modelo
        return self.mensaje + (f" {self.sugerencia}" if self.sugerencia else "")


class NotFound(ServiceError):
    def __init__(self, mensaje: str, *, sugerencia: str | None = None) -> None:
        super().__init__(mensaje, codigo="not_found", sugerencia=sugerencia)


class ReglaDeNegocio(ServiceError):
    """La peticion es valida sintacticamente pero el banco la rechaza."""

    def __init__(self, mensaje: str, *, sugerencia: str | None = None) -> None:
        super().__init__(mensaje, codigo="rechazada", sugerencia=sugerencia)
