"""Schemas de tools para el SDK nativo de Anthropic.

Dos familias, y la separacion importa:

  * **tools de datos** — envuelven `services.REGISTRO`. Leen o calculan. El
    resultado vuelve al modelo como `tool_result`.
  * **una sola tool de presentacion** — `render_surface`. Su argumento es el
    arreglo de mensajes A2UI. No devuelve datos: emite UI.

Los schemas se escriben a mano (no introspeccion de firmas) porque la
descripcion de cada parametro es prompt: es donde se le dice al modelo cuando
usar la tool y que NO hacer con ella. Un test verifica que el conjunto de
schemas y `services.REGISTRO` no se desincronicen.
"""

from __future__ import annotations

from typing import Any

from a2ui.models import A2UI_VERSION, CATALOG_ID

# --------------------------------------------------------------------------- datos
TOOLS_DATOS: list[dict[str, Any]] = [
    {
        "name": "get_client_snapshot",
        "description": (
            "Foto del cliente: quién es, saldos, posiciones, crédito y si tiene perfil de "
            "riesgo vigente. Llámala primero en casi toda conversación. Si "
            "`perfil_vigente` es false, NO propongas nada todavía: genera "
            "`inv.RiskProfiler`."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"client_id": {"type": "string", "description": "Ej. 'CLI-0001'."}},
            "required": ["client_id"],
        },
    },
    {
        "name": "get_accounts",
        "description": "Cuentas y tarjetas del cliente con saldos. Úsala si necesitas elegir cuenta de cargo.",
        "input_schema": {
            "type": "object",
            "properties": {"client_id": {"type": "string"}},
            "required": ["client_id"],
        },
    },
    {
        "name": "get_transactions",
        "description": "Movimientos recientes del cliente. Para preguntas sobre gasto puntual.",
        "input_schema": {
            "type": "object",
            "properties": {
                "client_id": {"type": "string"},
                "meses": {"type": "integer", "minimum": 1, "maximum": 18, "default": 3},
                "categoria": {"type": "string", "description": "Filtra una sola categoría."},
                "limite": {"type": "integer", "minimum": 1, "maximum": 300, "default": 50},
            },
            "required": ["client_id"],
        },
    },
    {
        "name": "get_spending_summary",
        "description": (
            "Gasto por categoría y capacidad de ahorro mensual. Úsala antes de sugerir una "
            "aportación mensual: el tope del slider sale de aquí, no de tu criterio."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "client_id": {"type": "string"},
                "meses": {"type": "integer", "minimum": 1, "maximum": 18, "default": 6},
            },
            "required": ["client_id"],
        },
    },
    {
        "name": "get_credit_overview",
        "description": (
            "Créditos, tarjetas y carga de pago sobre ingreso. Relevante si el usuario "
            "pregunta si le conviene invertir o pagar deuda."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"client_id": {"type": "string"}},
            "required": ["client_id"],
        },
    },
    {
        "name": "search_transactions",
        "description": (
            "Busca movimientos con filtros combinables: fechas, categoría, texto libre de "
            "comercio/descripción, rango de monto, tipo (cargo/abono) o una cuenta puntual. "
            "Úsala para preguntas específicas ('¿cuánto gasté en restaurantes en agosto?', "
            "'movimientos de más de 2000 pesos'). Para 'mis últimos movimientos' sin filtro, "
            "usa mejor `get_transactions`, que es más simple."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "client_id": {"type": "string"},
                "fecha_desde": {"type": "string", "description": "ISO 'YYYY-MM-DD'."},
                "fecha_hasta": {"type": "string", "description": "ISO 'YYYY-MM-DD'."},
                "categoria": {"type": "string"},
                "comercio": {"type": "string",
                             "description": "Coincide con comercio o descripción, parcial."},
                "tipo": {"type": "string", "enum": ["cargo", "abono"]},
                "monto_min": {"type": "number", "minimum": 0},
                "monto_max": {"type": "number", "minimum": 0},
                "account_id": {"type": "string"},
                "limite": {"type": "integer", "minimum": 1, "maximum": 300, "default": 100},
            },
            "required": ["client_id"],
        },
    },
    {
        "name": "get_budgets",
        "description": "Presupuestos por categoría que el cliente ya configuró, si los tiene.",
        "input_schema": {
            "type": "object",
            "properties": {"client_id": {"type": "string"}},
            "required": ["client_id"],
        },
    },
    {
        "name": "get_spending_alerts",
        "description": (
            "Compara el gasto de los últimos 30 días contra los presupuestos vigentes. "
            "Úsala para responder '¿voy bien con mi presupuesto?' o al mostrar "
            "`bank.SpendingBudgets`. Si el cliente no tiene presupuestos, la lista viene vacía: "
            "no inventes límites, ofrece ayudarle a poner uno con `set_budget`."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"client_id": {"type": "string"}},
            "required": ["client_id"],
        },
    },
    {
        "name": "set_budget",
        "description": (
            "Crea o actualiza el presupuesto mensual de una categoría de gasto. El monto no "
            "puede pasar del ingreso mensual del cliente; si lo hace, la tool rechaza y dice "
            "el máximo. No pidas confirmación en dos pasos: es una preferencia, no dinero real."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "client_id": {"type": "string"},
                "categoria": {
                    "type": "string",
                    "enum": ["super", "restaurantes", "transporte", "servicios",
                             "renta", "salud", "entretenimiento", "educacion"],
                },
                "monto_mensual": {"type": "number", "exclusiveMinimum": 0},
            },
            "required": ["client_id", "categoria", "monto_mensual"],
        },
    },
    {
        "name": "block_card",
        "description": (
            "Bloquea una tarjeta de inmediato. Es la acción de urgencia (tarjeta perdida, cargo "
            "sospechoso): NO requiere confirmación en dos pasos, un solo llamado la ejecuta. "
            "Idempotente: bloquear una tarjeta ya bloqueada no es error."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"client_id": {"type": "string"}, "card_id": {"type": "string"}},
            "required": ["client_id", "card_id"],
        },
    },
    {
        "name": "unblock_card",
        "description": "Reactiva una tarjeta bloqueada. Idempotente igual que `block_card`.",
        "input_schema": {
            "type": "object",
            "properties": {"client_id": {"type": "string"}, "card_id": {"type": "string"}},
            "required": ["client_id", "card_id"],
        },
    },
    {
        "name": "set_card_limit",
        "description": (
            "Cambia el límite de una tarjeta de crédito. Rechaza un límite menor al saldo ya "
            "usado, y un límite mayor a 3 veces el ingreso mensual declarado del cliente — en "
            "ambos casos el error dice el valor válido más cercano."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "client_id": {"type": "string"},
                "card_id": {"type": "string"},
                "nuevo_limite": {"type": "number", "exclusiveMinimum": 0},
            },
            "required": ["client_id", "card_id", "nuevo_limite"],
        },
    },
    {
        "name": "set_card_alias",
        "description": "Pone o quita el apodo de una tarjeta (ej. 'Platino viajes'). "
                       "Manda `alias: null` para quitarlo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "client_id": {"type": "string"},
                "card_id": {"type": "string"},
                "alias": {"type": ["string", "null"], "maxLength": 40},
            },
            "required": ["client_id", "card_id", "alias"],
        },
    },
    {
        "name": "set_account_alias",
        "description": "Pone o quita el apodo de una cuenta (ej. 'Mi cuenta del súper'). "
                       "Manda `alias: null` para quitarlo.",
        "input_schema": {
            "type": "object",
            "properties": {
                "client_id": {"type": "string"},
                "account_id": {"type": "string"},
                "alias": {"type": ["string", "null"], "maxLength": 40},
            },
            "required": ["client_id", "account_id", "alias"],
        },
    },
    {
        "name": "list_instruments",
        "description": (
            "Catálogo de instrumentos filtrado. Pasa `monto_disponible` para no mostrar "
            "instrumentos cuyo mínimo el cliente no alcanza."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "clase": {
                    "type": "string",
                    "enum": ["deuda_gub", "deuda_corp", "renta_variable",
                             "fondo_deuda", "fondo_rv", "etf", "pagare"],
                },
                "riesgo_max": {"type": "integer", "minimum": 1, "maximum": 5},
                "riesgo_min": {"type": "integer", "minimum": 1, "maximum": 5},
                "liquidez": {"type": "string",
                             "enum": ["diaria", "24h", "48h", "al_vencimiento"]},
                "monto_disponible": {"type": "number", "minimum": 0},
                "ordenar_por": {
                    "type": "string",
                    "enum": ["rendimiento", "riesgo", "volatilidad", "comision", "minimo", "nombre"],
                    "default": "rendimiento",
                },
                "limite": {"type": "integer", "minimum": 1, "maximum": 100, "default": 24},
            },
        },
    },
    {
        "name": "get_instrument_factsheet",
        "description": "Detalle de un instrumento y su serie histórica sintética.",
        "input_schema": {
            "type": "object",
            "properties": {
                "instrument_id": {"type": "string"},
                "meses_historia": {"type": "integer", "minimum": 12, "maximum": 120,
                                   "default": 60},
            },
            "required": ["instrument_id"],
        },
    },
    {
        "name": "get_risk_questions",
        "description": (
            "Las 4 preguntas del perfilador, listas para la prop `questions` de "
            "`inv.RiskProfiler`. No redactes preguntas propias."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "score_risk_profile",
        "description": (
            "Califica las respuestas del perfilador y devuelve score, perfil y horizonte. "
            "El score lo calcula el banco, no tú: nunca estimes un perfil a ojo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "answers": {
                    "type": "array",
                    "description": "Las 4 respuestas, tal como llegan en el contexto de `profile_done`.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string",
                                   "enum": ["horizonte", "reaccion_caida",
                                            "experiencia", "proposito"]},
                            "value": {"type": "integer", "minimum": 1, "maximum": 5},
                        },
                        "required": ["id", "value"],
                    },
                    "minItems": 4,
                    "maxItems": 4,
                },
                "client_id": {"type": "string",
                              "description": "Si lo pasas, el perfil queda guardado y vigente."},
                "guardar": {"type": "boolean", "default": True},
            },
            "required": ["answers"],
        },
    },
    {
        "name": "propose_allocation",
        "description": (
            "Asignación por reglas del banco para un perfil, horizonte y monto. Devuelve "
            "`slices` (para `inv.AllocationDonut`) y `asignacion` (para simular y ordenar). "
            "Nunca inventes porcentajes: pide la propuesta aquí."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "perfil": {"type": "string",
                           "enum": ["conservador", "moderado", "balanceado",
                                    "crecimiento", "agresivo"]},
                "horizonte_anios": {"type": "number", "exclusiveMinimum": 0, "maximum": 40},
                "monto": {"type": "number", "exclusiveMinimum": 0},
                "liquidez_requerida": {
                    "type": "boolean", "default": False,
                    "description": "True si el usuario dijo que podría necesitar el dinero antes.",
                },
                "excluir_clases": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["perfil", "horizonte_anios", "monto"],
        },
    },
    {
        "name": "simulate_portfolio",
        "description": (
            "Monte Carlo de 5000 trayectorias: escenarios p10/p50/p90 mes a mes, TIR, "
            "volatilidad, peor caída y probabilidad de perder. Es determinista: los mismos "
            "argumentos dan los mismos números. Todo lo que pintes en "
            "`inv.ProjectionChart` viene de aquí."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "asignacion": {
                    "type": "object",
                    "description": "{instrument_id: peso}. Usa el campo `asignacion` de propose_allocation.",
                    "additionalProperties": {"type": "number"},
                },
                "monto": {"type": "number", "minimum": 0},
                "horizonte_anios": {"type": "number", "exclusiveMinimum": 0, "maximum": 40},
                "aportacion_mensual": {"type": "number", "minimum": 0, "default": 0},
            },
            "required": ["asignacion", "monto", "horizonte_anios"],
        },
    },
    {
        "name": "compare_allocations",
        "description": (
            "Compara dos asignaciones bajo los mismos supuestos y devuelve la tabla de "
            "métricas para `inv.ComparePanel`. Úsala cuando el usuario pregunte '¿y si...?' "
            "o '¿qué conviene más?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "izquierda": {"type": "object", "additionalProperties": {"type": "number"}},
                "derecha": {"type": "object", "additionalProperties": {"type": "number"}},
                "monto": {"type": "number", "exclusiveMinimum": 0},
                "horizonte_anios": {"type": "number", "exclusiveMinimum": 0, "maximum": 40},
                "aportacion_mensual": {"type": "number", "minimum": 0, "default": 0},
                "metricas": {
                    "type": "array",
                    "items": {"type": "string",
                              "enum": ["valor_final_p50", "valor_final_p10", "valor_final_p90",
                                       "ganancia_p50", "tir_anual_p50", "volatilidad_anual",
                                       "max_drawdown", "prob_perdida_nominal"]},
                },
                "etiqueta_izquierda": {"type": "string", "default": "Opción A"},
                "etiqueta_derecha": {"type": "string", "default": "Opción B"},
            },
            "required": ["izquierda", "derecha", "monto", "horizonte_anios"],
        },
    },
    {
        "name": "place_order",
        "description": (
            "MUEVE DINERO. Confirmación en dos pasos, obligatoria:\n"
            "  Paso 1 — llámala SIN `confirmation_token`. No ejecuta: registra la orden y "
            "devuelve un token. Pinta el resultado en `inv.OrderTicket` y espera.\n"
            "  Paso 2 — solo cuando llegue la acción `place_order` del usuario, vuelve a "
            "llamarla con el MISMO `idempotency_key` y el token que te dio el paso 1.\n"
            "Nunca llames el paso 2 por iniciativa propia. `idempotency_key` debe ser "
            "estable para la misma intención (ej. '<client_id>-<monto>-<turno>'), para que "
            "un reintento no compre dos veces."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "client_id": {"type": "string"},
                "asignacion": {"type": "object", "additionalProperties": {"type": "number"}},
                "monto": {"type": "number", "minimum": 1000},
                "idempotency_key": {"type": "string"},
                "account_id": {"type": "string",
                               "description": "Opcional: por omisión, la cuenta de inversión."},
                "confirmation_token": {
                    "type": "string",
                    "description": "SOLO en el paso 2, con el valor exacto del paso 1.",
                },
            },
            "required": ["client_id", "asignacion", "monto", "idempotency_key"],
        },
    },
    {
        "name": "get_orders",
        "description": (
            "Historial de órdenes del cliente, la más reciente primero. Úsala para "
            "responder '¿qué compré?' y para armar el estado de cuenta después de ejecutar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "client_id": {"type": "string"},
                "estado": {"type": "string",
                           "enum": ["pendiente", "ejecutada", "rechazada", "cancelada"]},
                "limite": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            },
            "required": ["client_id"],
        },
    },
]

# ---------------------------------------------------------------------- presentacion
RENDER_SURFACE: dict[str, Any] = {
    "name": "render_surface",
    "description": (
        "Pinta la interfaz. Su argumento es un arreglo de mensajes A2UI "
        f"{A2UI_VERSION} validado contra el catálogo del banco.\n"
        "Reglas:\n"
        "  · Un mensaje = una acción de servidor (createSurface | updateComponents | "
        "updateDataModel | deleteSurface). `action` NO es una de estas: es el prop de un "
        "componente, y solo el cliente la manda de vuelta.\n"
        "  · Solo componentes del catálogo; cualquier otro lo ignora el renderer.\n"
        "  · Recalculaste datos pero la intención es la misma -> `updateDataModel`.\n"
        "    Cambió lo que el usuario quiere ver -> `updateComponents`.\n"
        "    Cambió de tarea -> `createSurface` nueva.\n"
        "    Tarea terminada y la superficie ya no aplica -> `deleteSurface`.\n"
        "  · El prop `action` de un componente va anidado: "
        "{\"event\": {\"name\": ..., \"context\": {...}}}.\n"
        "  · Toda cifra enlazada por `{\"path\": ...}` debe existir en el data model: "
        "mándala antes con `updateDataModel`.\n"
        "  · Prefiere pintar a explicar. Si puedes mostrarlo con un componente, no lo "
        "escribas en un `Text` largo.\n"
        "Si el blueprint no valida, recibes los errores y tienes que corregir y volver a llamar."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "messages": {
                "type": "array",
                "minItems": 1,
                "description": "Mensajes A2UI en orden de aplicación.",
                "items": {"type": "object"},
            },
            "nota": {
                "type": "string",
                "description": "Opcional, para la bitácora: en una línea, por qué esta superficie.",
            },
        },
        "required": ["messages"],
    },
}

CATALOGO_EN_USO = CATALOG_ID

# El parametro `tools` de `messages.create` ya NO sale de aqui directo: las
# tools de datos las expone `mcp_server/server.py` (que sí lee TOOLS_DATOS) y
# el agente las pide por MCP (ver `agent/mcp_client.py`). `RENDER_SURFACE` se
# agrega aparte porque no es una tool de datos, es la señal que intercepta
# `agent/loop.py`.

NOMBRES_DATOS = frozenset(t["name"] for t in TOOLS_DATOS)
NOMBRE_RENDER = RENDER_SURFACE["name"]
