"""El loop del agente, sobre el SDK nativo de Anthropic.

Sin frameworks de agentes. `anthropic.AsyncAnthropic` + `messages.stream` +
un while propio. La razon es control: necesitamos interceptar `render_surface`
antes de que llegue al cliente, validarlo contra el catalogo y devolverle el
error al modelo para que se corrija dentro del mismo turno. Un framework que
resuelve el loop por ti no te deja meter ese paso.

Anatomia de un turno:

    usuario / accion
        │
        ▼
    messages.stream ──► texto  ──────────────────────────────► evento texto
        │              tool_use
        ├── tool de datos  ► services.REGISTRO ► tool_result ──┐
        │                                                      │ vuelve al modelo
        └── render_surface ► validate_a2ui ──► ok ─► eventos a2ui
                                    └──► error ─► tool_result is_error ──┘
                                                   (hasta MAX_REINTENTOS,
                                                    luego plantilla estatica)

El turno termina cuando el modelo deja de pedir tools (`stop_reason != tool_use`).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

from a2ui.models import validate_a2ui
from agent.fallback import plantilla_fallback
from agent.prompts import construir_system, contexto_de_sesion
from agent.tools import NOMBRE_RENDER, NOMBRES_DATOS, tools_para_el_modelo
from services import CON_EFECTO, REGISTRO, ServiceError

log = logging.getLogger("agent.loop")

MODELO_DEFAULT = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
MAX_TOKENS = 8192
MAX_REINTENTOS_RENDER = 2
MAX_VUELTAS = 12                 # corta un encadenado de tools que se fue de las manos
TIMEOUT_TOOL_S = 20.0


# ---------------------------------------------------------------------------
@dataclass
class Evento:
    tipo: str
    datos: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({"type": self.tipo, **self.datos}, ensure_ascii=False)


@dataclass
class Sesion:
    """Estado de una conversacion. Vive en el gateway, no en el cliente.

    Tener el historial del lado del servidor es lo que permite la bitacora, la
    reconexion del SSE y la auditoria de que tools se llamaron en cada turno.
    """
    session_id: str
    client_id: str = "CLI-0001"
    surface_id: str = "inv-main"
    turno: int = 0
    historial: list[dict[str, Any]] = field(default_factory=list)
    tools_del_turno: list[dict[str, Any]] = field(default_factory=list)
    a2ui_del_turno: list[dict[str, Any]] = field(default_factory=list)
    uso: dict[str, int] = field(default_factory=lambda: {
        "input_tokens": 0, "output_tokens": 0,
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0})


def _resumir(valor: Any, limite: int = 220) -> str:
    texto = json.dumps(valor, ensure_ascii=False, default=str)
    return texto if len(texto) <= limite else texto[:limite] + "…"


def ejecutar_tool_de_datos(nombre: str, argumentos: dict[str, Any]) -> tuple[bool, Any]:
    """Llama un servicio del banco. Devuelve (ok, payload).

    Un `ServiceError` NO es una excepcion que haya que propagar: es informacion
    para el modelo. Se convierte en `tool_result` con `is_error=true` y el texto
    explica como corregir.
    """
    fn = REGISTRO.get(nombre)
    if fn is None:
        return False, {
            "error": "tool_desconocida",
            "mensaje": f"No existe la tool {nombre!r}.",
            "sugerencia": f"Tools disponibles: {', '.join(sorted(REGISTRO))}.",
        }
    try:
        return True, fn(**argumentos)
    except ServiceError as exc:
        log.info("servicio rechazo %s: %s", nombre, exc)
        return False, exc.to_dict()
    except TypeError as exc:
        return False, {
            "error": "argumentos_invalidos",
            "mensaje": f"{nombre}: {exc}",
            "sugerencia": "Revisa el input_schema de la tool.",
        }
    except Exception as exc:                       # noqa: BLE001 - nunca tumbar el turno
        log.exception("falla inesperada en %s", nombre)
        return False, {
            "error": "falla_interna",
            "mensaje": f"{nombre} falló de forma inesperada: {type(exc).__name__}.",
            "sugerencia": "Intenta con otros argumentos o continúa sin esa información.",
        }


class AgenteUIGenerativa:
    """Un turno de conversacion = una llamada a `run_turn`."""

    def __init__(
        self,
        cliente: Any | None = None,
        *,
        modelo: str = MODELO_DEFAULT,
        registrar_superficie: Callable[..., None] | None = None,
    ) -> None:
        if cliente is None:
            import anthropic                       # import tardio: los tests no lo necesitan
            cliente = anthropic.AsyncAnthropic()
        self.cliente = cliente
        self.modelo = modelo
        self.tools = tools_para_el_modelo()
        self._registrar = registrar_superficie

    # ------------------------------------------------------------------ publico
    async def run_turn(
        self, sesion: Sesion, entrada: str | dict[str, Any]
    ) -> AsyncIterator[Evento]:
        """Procesa un mensaje del usuario o una accion de la UI."""
        sesion.turno += 1
        sesion.tools_del_turno = []
        sesion.a2ui_del_turno = []

        sesion.historial.append({"role": "user", "content": self._texto_de_entrada(entrada)})
        reintentos_render = 0
        render_ok = False

        for vuelta in range(MAX_VUELTAS):
            bloques, stop_reason = await self._una_llamada(sesion)

            for bloque in bloques:
                if bloque["type"] == "text" and bloque["text"].strip():
                    yield Evento("text", {"text": bloque["text"]})

            usos = [b for b in bloques if b["type"] == "tool_use"]
            sesion.historial.append({"role": "assistant", "content": bloques})

            if not usos:
                break

            resultados: list[dict[str, Any]] = []
            for uso in usos:
                nombre, args, uso_id = uso["name"], uso["input"], uso["id"]

                if nombre == NOMBRE_RENDER:
                    resultado, eventos, ok = self._procesar_render(
                        sesion, args, reintentos_render)
                    for ev in eventos:
                        yield ev
                    if ok:
                        render_ok = True
                    else:
                        reintentos_render += 1
                    resultados.append({"type": "tool_result", "tool_use_id": uso_id,
                                       "content": resultado["content"],
                                       **({"is_error": True} if not ok else {})})
                    continue

                yield Evento("tool_call", {"name": nombre, "input": args,
                                           "efecto": nombre in CON_EFECTO})
                ok, payload = await asyncio.get_running_loop().run_in_executor(
                    None, ejecutar_tool_de_datos, nombre, args)
                sesion.tools_del_turno.append({
                    "name": nombre, "input": args, "ok": ok,
                    "output_resumen": _resumir(payload)})
                yield Evento("tool_result", {"name": nombre, "ok": ok,
                                             "resumen": _resumir(payload)})
                resultados.append({
                    "type": "tool_result", "tool_use_id": uso_id,
                    "content": json.dumps(payload, ensure_ascii=False, default=str),
                    **({"is_error": True} if not ok else {})})

            sesion.historial.append({"role": "user", "content": resultados})

            if reintentos_render > MAX_REINTENTOS_RENDER:
                for ev in self._emitir_fallback(sesion):
                    yield ev
                render_ok = True
                break
        else:
            log.warning("turno %s: corte por MAX_VUELTAS", sesion.turno)
            yield Evento("warning", {
                "mensaje": "Corté el encadenado de tools por seguridad. "
                           "La pantalla puede estar incompleta."})

        if sesion.a2ui_del_turno and self._registrar is not None:
            try:
                self._registrar(sesion.session_id, sesion.turno, sesion.surface_id,
                                sesion.a2ui_del_turno, sesion.tools_del_turno)
            except Exception:                      # noqa: BLE001 - la bitacora no tumba el turno
                log.exception("no pude escribir la bitácora")

        yield Evento("done", {"turno": sesion.turno, "render_ok": render_ok,
                              "uso": dict(sesion.uso)})

    # ------------------------------------------------------------------ interno
    @staticmethod
    def _texto_de_entrada(entrada: str | dict[str, Any]) -> str:
        if isinstance(entrada, str):
            return entrada
        nombre = entrada.get("name", "?")
        contexto = entrada.get("context", {})
        return (
            f"[acción de la interfaz] `{nombre}` en la superficie "
            f"`{entrada.get('surfaceId', '?')}`.\n"
            f"Contexto que el usuario ya movió en pantalla:\n"
            f"{json.dumps(contexto, ensure_ascii=False, indent=2)}"
        )

    async def _una_llamada(self, sesion: Sesion) -> tuple[list[dict[str, Any]], str | None]:
        """Una llamada a messages.create con streaming. Devuelve bloques normalizados."""
        system = construir_system(
            contexto_de_sesion(sesion.client_id, sesion.surface_id, sesion.turno))

        async with self.cliente.messages.stream(
            model=self.modelo,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=self.tools,
            messages=sesion.historial,
        ) as stream:
            final = await stream.get_final_message()

        uso = getattr(final, "usage", None)
        if uso is not None:
            for clave in sesion.uso:
                sesion.uso[clave] += int(getattr(uso, clave, 0) or 0)

        bloques: list[dict[str, Any]] = []
        for bloque in final.content:
            tipo = getattr(bloque, "type", None)
            if tipo == "text":
                bloques.append({"type": "text", "text": bloque.text})
            elif tipo == "tool_use":
                bloques.append({"type": "tool_use", "id": bloque.id,
                                "name": bloque.name, "input": bloque.input or {}})
        return bloques, getattr(final, "stop_reason", None)

    def _procesar_render(
        self, sesion: Sesion, args: dict[str, Any], reintentos: int
    ) -> tuple[dict[str, Any], list[Evento], bool]:
        """Valida el blueprint y, si pasa, lo emite mensaje por mensaje."""
        mensajes = args.get("messages")
        res = validate_a2ui(mensajes)

        if not res.ok:
            log.info("blueprint invalido (intento %s): %s", reintentos + 1, res.errores)
            return (
                {"content": res.para_el_modelo()},
                [Evento("render_rechazado", {"intento": reintentos + 1,
                                             "errores": res.errores})],
                False,
            )

        eventos: list[Evento] = []
        for msg in mensajes:
            sesion.a2ui_del_turno.append(msg)
            if "createSurface" in msg:
                sesion.surface_id = msg["createSurface"]["surfaceId"]
            eventos.append(Evento("a2ui", {"message": msg}))

        if res.avisos:
            eventos.append(Evento("warning", {"avisos": res.avisos}))

        resumen = {
            "ok": True,
            "mensajes_aplicados": len(mensajes),
            "superficie": sesion.surface_id,
            "avisos": res.avisos,
            "nota": "Blueprint válido y aplicado. No lo vuelvas a mandar en este turno.",
        }
        return ({"content": json.dumps(resumen, ensure_ascii=False)}, eventos, True)

    def _emitir_fallback(self, sesion: Sesion) -> list[Evento]:
        log.warning("turno %s: agoté reintentos de render, va la plantilla estática",
                    sesion.turno)
        eventos = [Evento("warning", {
            "mensaje": "El modelo no logró un blueprint válido; monté la pantalla de respaldo."})]
        for msg in plantilla_fallback(sesion.surface_id):
            sesion.a2ui_del_turno.append(msg)
            eventos.append(Evento("a2ui", {"message": msg}))
        return eventos
