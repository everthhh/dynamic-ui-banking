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
        "name": "get_financial_profile",
        "description": (
            "Perfil financiero CALCULADO del cliente con 12 meses de datos: ingreso (fijo o "
            "variable), consumo por categoría con tendencia, suscripciones y gasto hormiga "
            "detectados, hábito de pago de cada tarjeta (totalero, revolvente, paga el mínimo, "
            "paga tarde) leído de sus estados de cuenta, carga de deuda, colchón de liquidez, "
            "efectivo sin invertir, mezcla del portafolio, productos que usa, rasgos y un score "
            "de salud financiera con su desglose. Úsala para «¿cómo estoy?», «¿en qué se me va "
            "el dinero?» o para justificar una recomendación. Las cifras son del banco: no las "
            "recalcules. Se pinta con `bank.FinancialProfile`."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"client_id": {"type": "string"}},
            "required": ["client_id"],
        },
    },
    {
        "name": "get_recommendations",
        "description": (
            "Recomendaciones priorizadas derivadas del perfil financiero. Cada una trae "
            "`evidencia` (las cifras que la disparan), `impacto` en pesos con su supuesto, "
            "`prioridad` 0-100 (la fórmula viene en `criterio_prioridad`), la `herramienta` del "
            "catálogo que la resuelve con sus `tools`, `parametros` sugeridos para esas tools y "
            "un `prompt`. Es la BASE de toda recomendación: no recomiendes nada que no esté aquí "
            "o que no puedas respaldar con `get_financial_profile`. Se pinta con "
            "`bank.Recommendations`."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "client_id": {"type": "string"},
                "limite": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
            "required": ["client_id"],
        },
    },
    {
        "name": "simulate_debt_payoff",
        "description": (
            "Plan para liquidar una tarjeta de crédito sobre su saldo y tasa reales. Con "
            "`meses_objetivo` calcula el pago mensual; con `pago_mensual`, en cuántos meses se "
            "liquida (pasa uno, no los dos; sin ninguno, 12 meses). Compara contra pagar solo el "
            "mínimo: meses, intereses totales y `ahorro_intereses`. Sin `card_id` usa la tarjeta "
            "con más saldo. Si el pago no cubre ni los intereses, la rechaza y sugiere uno que sí "
            "liquida. Es la herramienta `plan_pago_tarjeta`."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "client_id": {"type": "string"},
                "card_id": {"type": "string"},
                "pago_mensual": {"type": "number", "exclusiveMinimum": 0},
                "meses_objetivo": {"type": "integer", "minimum": 1, "maximum": 120},
            },
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
            "Catálogo de los 24 instrumentos contratables: deuda, pagarés, fondos y "
            "ETFs. Aquí no hay acciones sueltas; es un producto de fondos. Los fondos "
            "de renta variable mexicana traen `desglose` con las empresas que tienen "
            "dentro y su riesgo derivado de ellas. Pasa `monto_disponible` para no "
            "mostrar instrumentos cuyo mínimo el cliente no alcanza."
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
        "name": "get_issuer_profile",
        "description": (
            "Fundamentales de una empresa de la BMV y el DESGLOSE de su riesgo: beta, "
            "volatilidad, calificación, apalancamiento, bursatilidad y qué tanto de su "
            "riesgo es propio de la empresa (el que no desaparece diversificando y que "
            "el mercado tampoco te paga). Úsala cuando el usuario pregunte «¿qué tan "
            "segura es esta empresa?» o «¿por qué me conviene un fondo que la trae?». "
            "La respuesta es la tabla de factores, no tu opinión.\n"
            "OJO: esta empresa NO se puede contratar. Este es un producto de fondos; "
            "el cliente llega a ella a través de los fondos que la tienen en cartera, "
            "y la respuesta te dice cuáles son."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {"type": "string",
                           "description": "Ej. 'WALMEX', 'GFNORTEO', 'CEMEXCPO'."},
            },
            "required": ["ticker"],
        },
    },
    {
        "name": "get_fund_holdings",
        "description": (
            "Qué empresas hay DENTRO de lo que el cliente compra.\n"
            "Con `instrument_id`: la cartera de ese fondo y las cifras que se derivan "
            "de ella (volatilidad, beta, concentración, riesgo). Es de dónde sale el "
            "riesgo del fondo: no está tecleado, se calcula desde sus tenencias.\n"
            "Con `asignacion`: el look-through del portafolio completo, o sea el peso "
            "EFECTIVO en cada empresa sumando lo que aporta cada fondo. Es la respuesta "
            "a «¿en qué empresas está mi dinero?» cuando el cliente nunca compró una "
            "acción. Mira `cobertura_desglose`: los fondos internacionales no se pueden "
            "ver por dentro y hay que decirlo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "instrument_id": {"type": "string",
                                  "description": "Ej. 'NAFTRAC', 'FND-RV-MX'."},
                "asignacion": {"type": "object",
                               "additionalProperties": {"type": "number"}},
            },
        },
    },
    {
        "name": "get_funding_sources",
        "description": (
            "De dónde puede salir el dinero y qué le hace cada opción al cálculo. Con "
            "`client_id` devuelve las cuentas y créditos REALES del cliente con su tasa "
            "contratada. Llámala antes de simular si el usuario menciona pagar con "
            "tarjeta, con un crédito o «lo que tengo en la cuenta»: invertir con deuda "
            "cambia la referencia de pérdida y baja el perfil aplicable a conservador."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"client_id": {"type": "string"}},
        },
    },
    {
        "name": "check_suitability",
        "description": (
            "¿Esta asignación le corresponde a este cliente? Devuelve `apto`, los "
            "motivos `bloqueantes` y los `avisos`. Es EXACTAMENTE el mismo control que "
            "aplica `place_order`, así que si aquí sale `apto: false`, la orden se va a "
            "rechazar. Úsala antes de pintar una propuesta que armaste tú, para no "
            "enseñarle al usuario algo que no va a poder ejecutar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "asignacion": {"type": "object",
                               "additionalProperties": {"type": "number"}},
                "client_id": {"type": "string",
                              "description": "Si lo pasas, el perfil y el horizonte "
                                             "salen de la base y ganan sobre lo que "
                                             "mandes tú."},
                "perfil": {"type": "string",
                           "enum": ["conservador", "moderado", "balanceado",
                                    "crecimiento", "agresivo"]},
                "horizonte_anios": {"type": "number", "exclusiveMinimum": 0},
                "monto": {"type": "number", "minimum": 0},
                "origen": {"type": "string",
                           "description": "Clave de `get_funding_sources`."},
            },
            "required": ["asignacion"],
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
            "Asignación por reglas del banco. Devuelve `slices` (para "
            "`inv.AllocationDonut`), `asignacion` (para simular y ordenar) e "
            "`idoneidad` (el veredicto contra el perfil). Nunca inventes porcentajes: "
            "pide la propuesta aquí.\n"
            "PASA SIEMPRE `client_id` cuando lo tengas: así el perfil y el horizonte "
            "salen de la base. Si mandas un `perfil` distinto al vigente, gana el de "
            "la base y te lo dice en `notas`. La propuesta son SOLO fondos; los "
            "`slices` de renta variable mexicana traen `principales_emisoras` para "
            "poder decir en qué empresas acaba el dinero."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "monto": {"type": "number", "exclusiveMinimum": 0},
                "client_id": {"type": "string",
                              "description": "Preferido. Toma el perfil vigente y el "
                                             "horizonte de la base."},
                "perfil": {"type": "string",
                           "enum": ["conservador", "moderado", "balanceado",
                                    "crecimiento", "agresivo"],
                           "description": "Solo si no hay `client_id`."},
                "horizonte_anios": {"type": "number", "exclusiveMinimum": 0, "maximum": 40},
                "liquidez_requerida": {
                    "type": "boolean", "default": False,
                    "description": "True si el usuario dijo que podría necesitar el dinero antes.",
                },
                "excluir_clases": {"type": "array", "items": {"type": "string"}},
                "origen": {"type": "string",
                           "description": "De dónde sale el dinero (`get_funding_sources`). "
                                          "Con crédito el perfil aplicable baja a "
                                          "conservador."},
            },
            "required": ["monto"],
        },
    },
    {
        "name": "simulate_portfolio",
        "description": (
            "Monte Carlo de 5000 trayectorias, NETO de impuestos y de costo de "
            "financiamiento. Devuelve escenarios p10/p50/p90 mes a mes, TIR, "
            "volatilidad, peor caída, `indice_riesgo` (0-100) y tres probabilidades de "
            "perder distintas: `prob_perdida_nominal` (no recuperar lo aportado), "
            "`prob_perdida_real` (no ganarle a la inflación) y `prob_perdida_vs_origen` "
            "(no ganarle a la deuda o al rendimiento que ya tenía ese dinero). Cuando "
            "el dinero es prestado, la tercera es la única honesta: úsala.\n"
            "Es determinista: los mismos argumentos dan los mismos números. Todo lo que "
            "pintes en `inv.ProjectionChart` viene de aquí."
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
                "origen": {"type": "string",
                           "description": "De dónde sale el dinero (`get_funding_sources`). "
                                          "Cambia la referencia de pérdida."},
                "client_id": {"type": "string",
                              "description": "Si lo pasas, el resultado trae adjunto el "
                                             "veredicto de idoneidad."},
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
                "origen": {"type": "string",
                           "description": "Mismo origen para las dos, para que la "
                                          "diferencia sea de las asignaciones."},
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
            "un reintento no compre dos veces.\n"
            "Los DOS pasos verifican la asignación contra el perfil guardado del cliente "
            "y la rechazan si no le corresponde. Ese control no se puede desactivar desde "
            "aquí: si quieres saber antes si va a pasar, llama `check_suitability`."
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
                "origen": {"type": "string",
                           "description": "Por omisión se deduce del tipo de la cuenta "
                                          "de cargo."},
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
