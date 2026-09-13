"""Acciones deterministas que NO pasan por el LLM.

De las 15 acciones que declara `a2ui/catalog.json`, la mayoría son un mapeo
1:1 a una sola función de `services/`: el usuario bloquea una tarjeta, sube
un límite, le pone apodo a algo, cambia un presupuesto, o pide administrar
una tarjeta que ya tiene enfrente. Nada de eso necesita que Claude decida
nada — decidir es exactamente lo que sí hace falta para `profile_done`,
`compare` o `ask`, pero no para esto.

Antes, CADA acción (sin excepción) reinvocaba `agent/loop.py::run_turn`, o
sea una llamada real a la API de Anthropic, solo para que el modelo llamara
una tool y volviera a mandar el mismo `updateDataModel` que este módulo arma
aquí directo. Este archivo es el camino corto: `gateway/main.py::accion()`
consulta `DIRECT_HANDLERS` antes de tocar al agente.

Convención fija de rutas del data model (ver docs/trade-offs.md): estas
funciones asumen que `bank.AccountsOverview`/`bank.CardManager`/
`bank.SpendingBudgets` están enlazados exactamente a `/cuentas`, `/tarjetas`,
`/card`, `/ingresoMensual` y `/alertas` — es la misma convención que
`agent/prompts.py` le exige al modelo cuando monta estos componentes por
primera vez. Si el modelo se desvía, `agent/loop.py::_procesar_render` avisa
por la traza (no bloquea el render), y una acción directa terminaría
escribiendo a una ruta que nadie lee — un hueco conocido, no un bug oculto.

Cada handler:
  * recibe la `Sesion` (para `client_id`/`surface_id`) y el `context` crudo
    que mandó el cliente;
  * llama servicios reales — los mismos que llamaría el modelo, con las
    mismas reglas de negocio y los mismos `ServiceError`;
  * devuelve `ResultadoDirecto`: los cuerpos de mensaje A2UI (sin `version`,
    eso lo pone el llamador) y una línea de resumen para la traza/bitácora.

`ServiceError` NO se atrapa aquí: `gateway/main.py::_stream_directo` lo
convierte en un evento `error`, igual que ya hace `_stream` con el camino
del LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from agent.loop import Sesion
from services import accounts, banking
from services.errors import ServiceError


@dataclass
class ResultadoDirecto:
    mensajes: list[dict[str, Any]]
    resumen: str


def _dm(surface_id: str, path: str, value: Any) -> dict[str, Any]:
    return {"updateDataModel": {"surfaceId": surface_id, "path": path, "value": value}}


def _set_account_alias(ses: Sesion, ctx: dict[str, Any]) -> ResultadoDirecto:
    banking.set_account_alias(ses.client_id, ctx["account_id"], ctx.get("alias"))
    # set_account_alias regresa {account_id, alias}, no la cuenta completa:
    # se relee para que /cuentas quede igual de completo que si lo hubiera
    # mandado el modelo.
    cuentas = accounts.get_accounts(ses.client_id)["cuentas"]
    return ResultadoDirecto(
        [_dm(ses.surface_id, "/cuentas", cuentas)],
        f"alias de {ctx['account_id']} actualizado",
    )


def _set_card_alias(ses: Sesion, ctx: dict[str, Any]) -> ResultadoDirecto:
    tarjeta = banking.set_card_alias(ses.client_id, ctx["card_id"], ctx.get("alias"))
    return ResultadoDirecto(
        [_dm(ses.surface_id, "/card", tarjeta)],
        f"alias de {ctx['card_id']} actualizado",
    )


def _toggle_card_block(ses: Sesion, ctx: dict[str, Any]) -> ResultadoDirecto:
    # El cliente manda el `estado` que ya tiene en pantalla para decidir la
    # dirección — sin esto, no hay forma determinista de saber si toca
    # bloquear o desbloquear sin preguntarle a alguien (antes, al modelo).
    fn = banking.unblock_card if ctx.get("estado") == "bloqueada" else banking.block_card
    tarjeta = fn(ses.client_id, ctx["card_id"])
    verbo = "bloqueada" if tarjeta["estado"] == "bloqueada" else "activa"
    return ResultadoDirecto(
        [_dm(ses.surface_id, "/card", tarjeta)],
        f"tarjeta {ctx['card_id']} {verbo}",
    )


def _update_card_limit(ses: Sesion, ctx: dict[str, Any]) -> ResultadoDirecto:
    tarjeta = banking.set_card_limit(ses.client_id, ctx["card_id"], ctx["nuevo_limite"])
    return ResultadoDirecto(
        [_dm(ses.surface_id, "/card", tarjeta)],
        f"límite de {ctx['card_id']} = {ctx['nuevo_limite']}",
    )


def _set_budget(ses: Sesion, ctx: dict[str, Any]) -> ResultadoDirecto:
    banking.set_budget(ses.client_id, ctx["categoria"], ctx["monto_mensual"])
    # set_budget regresa solo {client_id, categoria, monto_mensual}: SpendingBudgets
    # necesita gastado/porcentaje/excedido, así que se relee get_spending_alerts.
    alertas = accounts.get_spending_alerts(ses.client_id)["alertas"]
    return ResultadoDirecto(
        [_dm(ses.surface_id, "/alertas", alertas)],
        f"presupuesto {ctx['categoria']} = {ctx['monto_mensual']}",
    )


def _manage_card(ses: Sesion, ctx: dict[str, Any]) -> ResultadoDirecto:
    card = ctx.get("card")
    if not isinstance(card, dict) or not card.get("card_id"):
        raise ServiceError(
            "Falta el objeto `card` en el contexto de manage_card.",
            sugerencia="El cliente debe mandar la tarjeta completa que ya tiene en pantalla.",
        )
    # `card` viene del cliente y solo se usa para pintar: cualquier mutación
    # posterior sobre esa tarjeta revalida ownership server-side
    # (_exigir_tarjeta_del_cliente dentro de services/banking.py) sin
    # importar lo que el cliente haya mandado aquí.
    ingreso = accounts.get_client_snapshot(ses.client_id)["ingreso_mensual"]
    return ResultadoDirecto(
        [
            _dm(ses.surface_id, "/card", card),
            _dm(ses.surface_id, "/ingresoMensual", ingreso),
            {"updateComponents": {"surfaceId": ses.surface_id, "components": [
                {"id": "root", "component": "bank.CardManager",
                 "card": {"path": "/card"}, "ingresoMensual": {"path": "/ingresoMensual"}},
            ]}},
        ],
        f"administrando tarjeta {card['card_id']}",
    )


DIRECT_HANDLERS: dict[str, Callable[[Sesion, dict[str, Any]], ResultadoDirecto]] = {
    "set_account_alias": _set_account_alias,
    "set_card_alias": _set_card_alias,
    "toggle_card_block": _toggle_card_block,
    "update_card_limit": _update_card_limit,
    "set_budget": _set_budget,
    "manage_card": _manage_card,
}
