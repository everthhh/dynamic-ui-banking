"""Doble de prueba del cliente de Anthropic.

Replica la superficie minima que usa `agent/loop.py`:

    async with cliente.messages.stream(...) as s:
        final = await s.get_final_message()

Recibe una lista de "turnos del modelo" ya escritos y los va entregando en
orden. Asi el ciclo completo --intencion, tools, blueprint, validacion,
reintento, fallback-- se prueba sin gastar un token ni depender de la red.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BloqueTexto:
    text: str
    type: str = "text"


@dataclass
class BloqueToolUse:
    name: str
    input: dict[str, Any]
    id: str = field(default_factory=lambda: f"toolu_{uuid.uuid4().hex[:12]}")
    type: str = "tool_use"


@dataclass
class Uso:
    input_tokens: int = 100
    output_tokens: int = 50
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class MensajeFinal:
    content: list[Any]
    stop_reason: str
    usage: Uso = field(default_factory=Uso)


class _Stream:
    def __init__(self, mensaje: MensajeFinal) -> None:
        self._mensaje = mensaje

    async def __aenter__(self) -> "_Stream":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def get_final_message(self) -> MensajeFinal:
        return self._mensaje


class _Messages:
    def __init__(self, padre: "FakeAnthropic") -> None:
        self._padre = padre

    def stream(self, **kwargs: Any) -> _Stream:
        self._padre.llamadas.append(kwargs)
        if not self._padre.guion:
            raise AssertionError(
                "El guion del modelo falso se acabó y el loop pidió otra llamada. "
                "Agrega un turno o revisa por qué el loop no terminó."
            )
        turno = self._padre.guion.pop(0)
        # Un turno normal es solo la lista de bloques; para forzar un
        # `stop_reason` explícito (ej. "max_tokens" al simular un corte a
        # media respuesta) se pasa la tupla (bloques, stop_reason).
        if isinstance(turno, tuple):
            bloques, stop = turno
        else:
            bloques = turno
            stop = "tool_use" if any(getattr(b, "type", "") == "tool_use" for b in bloques) \
                else "end_turn"
        return _Stream(MensajeFinal(content=list(bloques), stop_reason=stop))


class FakeAnthropic:
    """`guion`: lista de turnos; cada turno es una lista de bloques, o la tupla
    `(bloques, stop_reason)` para forzar un `stop_reason` explícito."""

    def __init__(self, guion: list[list[Any]]) -> None:
        self.guion = [tuple(t) if isinstance(t, tuple) else list(t) for t in guion]
        self.llamadas: list[dict[str, Any]] = []
        self.messages = _Messages(self)

    @property
    def agotado(self) -> bool:
        return not self.guion
