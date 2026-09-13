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
        ├── tool de datos  ► cliente MCP ► mcp_server/ ► tool_result ──┐
        │                                                              │ vuelve al modelo
        └── render_surface ► validate_a2ui ──► ok ─► eventos a2ui
                                    └──► error ─► tool_result is_error ──┘
                                                   (hasta MAX_REINTENTOS,
                                                    luego plantilla estatica)

El turno termina cuando el modelo deja de pedir tools (`stop_reason != tool_use`).

Las tools de datos ya NO se llaman importando `services` directo: viven en un
proceso separado (`mcp_server/`) y este loop les habla como cliente MCP (ver
`agent/mcp_client.py`). Los schemas que ve el modelo tampoco se escriben aquí:
se piden a `list_tools()` del servidor la primera vez que corre un turno.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable

from a2ui.models import validate_a2ui
from agent.fallback import plantilla_fallback
from agent.prompts import construir_system, contexto_de_sesion
from agent.tools import RENDER_SURFACE, NOMBRE_RENDER
from services import CON_EFECTO

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


# El panel de traza del front muestra estos resúmenes en pantalla, y en un demo
# la pantalla se proyecta. Un `confirmation_token` a la vista invita a que
# alguien pregunte si el modelo pudo haberlo copiado, que es justo la duda que
# el diseño quiere cerrar. El código de un retiro sin tarjeta es peor: con él
# se saca efectivo de un cajero.
CLAVES_SENSIBLES = ("confirmation_token", "idempotency_key", "codigo_retiro")


def _redactar(valor: Any) -> Any:
    if isinstance(valor, dict):
        return {
            k: ("«oculto»" if k in CLAVES_SENSIBLES else _redactar(v))
            for k, v in valor.items()
        }
    if isinstance(valor, list):
        return [_redactar(v) for v in valor]
    return valor


def _resumir(valor: Any, limite: int = 220) -> str:
    texto = json.dumps(_redactar(valor), ensure_ascii=False, default=str)
    return texto if len(texto) <= limite else texto[:limite] + "…"


class AgenteUIGenerativa:
    """Un turno de conversacion = una llamada a `run_turn`.

    `mcp` es cualquier objeto con `tools_para_el_modelo()` y `llamar(nombre, args)`
    async — normalmente un `agent.mcp_client.ClienteMCP` ya conectado. Los tests
    usan `tests.fake_mcp.FakeClienteMCP`, que llama `services.REGISTRO` en el
    mismo proceso para no pagar el costo de un subproceso real.
    """

    def __init__(
        self,
        cliente: Any | None = None,
        *,
        mcp: Any,
        modelo: str = MODELO_DEFAULT,
        registrar_superficie: Callable[..., None] | None = None,
    ) -> None:
        if cliente is None:
            import anthropic                       # import tardio: los tests no lo necesitan
            cliente = anthropic.AsyncAnthropic()
        self.cliente = cliente
        self.mcp = mcp
        self.modelo = modelo
        self.tools: list[dict[str, Any]] | None = None
        self._registrar = registrar_superficie

    async def _preparar(self) -> None:
        """Pide los schemas de datos al servidor MCP una sola vez por instancia."""
        if self.tools is None:
            datos = await self.mcp.tools_para_el_modelo()
            self.tools = [*datos, RENDER_SURFACE]

    # ------------------------------------------------------------------ publico
    async def run_turn(
        self, sesion: Sesion, entrada: str | dict[str, Any]
    ) -> AsyncIterator[Evento]:
        """Procesa un mensaje del usuario o una accion de la UI."""
        await self._preparar()
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
                ok, payload = await self._llamar_tool_de_datos(nombre, args)
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
    async def _llamar_tool_de_datos(self, nombre: str, argumentos: dict[str, Any]) -> tuple[bool, Any]:
        """Delega en el cliente MCP. Devuelve (ok, payload) para el `tool_result`.

        Un `ServiceError` del lado del servidor NO es una excepcion que haya
        que propagar: llega como `(False, payload)` y el texto explica al
        modelo como corregir. Si el cliente MCP mismo falla (proceso caído,
        timeout), tampoco tumbamos el turno.
        """
        try:
            return await self.mcp.llamar(nombre, argumentos)
        except Exception as exc:                   # noqa: BLE001 - nunca tumbar el turno
            log.exception("el cliente MCP falló llamando %s", nombre)
            return False, {
                "error": "mcp_no_disponible",
                "mensaje": f"No pude llamar {nombre!r}: {type(exc).__name__}.",
                "sugerencia": "Intenta de nuevo en un momento o continúa sin esa información.",
            }

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
            log.info("blueprint invalido (intento %s) — payload crudo: %s", reintentos + 1,
                      json.dumps(mensajes, ensure_ascii=False, default=str)[:6000])
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
