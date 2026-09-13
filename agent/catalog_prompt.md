<!-- GENERADO por scripts/gen_catalog_artifacts.py desde a2ui/catalog.json. No editar a mano. -->

## Catálogo de componentes (A2UI v0.9)

`catalogId`: `https://dynamic-ui-banking.local/a2ui/inv/v1/catalog.json`

Reglas del catálogo:
- Un mensaje A2UI contiene exactamente una acción de servidor: createSurface, updateComponents, updateDataModel o deleteSurface. `action` NO es una de estas: es el prop de un componente, y es el cliente quien la manda de vuelta, nunca tú.
- Todo componente debe existir en este catálogo. El renderer ignora cualquier otro.
- Los datos numéricos se enlazan por ruta ({"path": "/sim/escenarios"}), nunca se escriben inline.
- Recalcular datos -> updateDataModel. Cambiar la intención -> updateComponents. Cambiar la tarea -> nueva superficie. Tarea terminada y superficie ya no aplica -> deleteSurface.
- El prop `action` de cualquier componente va anidado como {"event": {"name": ..., "context": {...}}} (spec A2UI v0.9). Solo los ids declarados en `acciones` son válidos como `event.name`.

### Acciones declaradas

| acción | cuándo | contexto que debe viajar |
|---|---|---|
| `profile_done` | El usuario terminó de contestar el perfilador. | `answers` |
| `simulate` | Recalcular la proyección con nuevos parámetros. | `amount`, `horizon`, `monthly` |
| `compare` | El usuario pidió comparar la propuesta contra otra alternativa. | `baseline`, `alternative` |
| `select_allocation` | El usuario eligió una de las dos columnas del comparativo. | `lado` |
| `select_instrument` | El usuario tocó un instrumento de la tabla y quiere el detalle. | `instrument_id` |
| `place_order` | El usuario confirmó la orden. Requiere confirmación en dos pasos. **(mueve dinero)** | `order`, `confirmation_token` |
| `cancel_order` | El usuario abortó el ticket. | `order_id` |
| `ask` | Botón que manda una pregunta en texto de vuelta al agente. | `prompt` |
| `manage_card` | El usuario tocó una tarjeta en el panorama de cuentas y quiere administrarla. El servidor la resuelve directo (sin LLM): manda la tarjeta completa que ya está en pantalla, no solo el id. | `card_id`, `card` |
| `set_account_alias` | El usuario le puso o quitó apodo a una cuenta. | `account_id`, `alias` |
| `toggle_card_block` | El usuario bloqueó o desbloqueó una tarjeta. Efecto inmediato, sin confirmación en dos pasos. El servidor la resuelve directo (sin LLM): necesita el `estado` actual para decidir la dirección. **(mueve dinero)** | `card_id`, `estado` |
| `update_card_limit` | El usuario movió el slider de límite de una tarjeta de crédito y lo soltó. **(mueve dinero)** | `card_id`, `nuevo_limite` |
| `set_card_alias` | El usuario le puso o quitó apodo a una tarjeta. | `card_id`, `alias` |
| `set_budget` | El usuario definió o cambió el presupuesto mensual de una categoría. **(mueve dinero)** | `categoria`, `monto_mensual` |
| `refine_search` | El usuario ajustó un filtro rápido sobre resultados de búsqueda de movimientos. | `filtro` |

### Componentes de dominio

#### `inv.RiskProfiler`
*Cuándo:* Falta contexto para poder proponer: el cliente no tiene perfil vigente. Preguntar con este componente, NO con texto.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `questions` | array | sí | sí | Viene tal cual de get_risk_questions / score_risk_profile. [{id, text, options[{value,label}]}] |
| `value` | object | — | sí | Respuestas parciales, {id: value}. |
| `action` | action | sí | — | Se dispara al contestar la última. Debe ser profile_done. |
| `intro` | string | — | — | Una línea de por qué se pregunta. |

#### `inv.AllocationDonut`
*Cuándo:* Mostrar o ajustar una propuesta de asignación. Sustituye cualquier lista de porcentajes en texto.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `slices` | array | sí | sí | `slices` de propose_allocation: [{instrument_id, instrumento, etiqueta, peso, monto, porque}] |
| `total` | number | sí | sí | Monto total en MXN. |
| `editable` | boolean | — | — | Si true, el usuario puede arrastrar los pesos. |
| `action` | action | — | — | Al tocar un gajo. |
| `subtitulo` | string | — | sí |  |

#### `inv.ProjectionChart`
*Cuándo:* Responder '¿cuánto voy a tener?'. Siempre con los tres escenarios, nunca con un número solo.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `scenarios` | object | sí | sí | `escenarios` de simulate_portfolio: {p10:[{mes,anios,valor}], p50:[...], p90:[...]} |
| `horizonYears` | number | sí | sí |  |
| `aportado` | number | — | sí | Línea de referencia: total aportado. |
| `disclaimer` | string | sí | — | Obligatoria. Úsala tal cual viene del tool_result; no la redactes tú. |
| `resaltar` | p10|p50|p90 | — | — |  |

#### `inv.InstrumentTable`
*Cuándo:* Explorar el catálogo. Nunca enlistes instrumentos en texto.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `rows` | array | sí | sí | `instrumentos` de list_instruments. |
| `columns` | array | sí | — | Ids de columna a mostrar, en orden. Válidas: nombre, clase, rend_esperado_anual, rend_neto_anual, volatilidad_anual, comision_anual, riesgo_1a5, liquidez, plazo_dias, monto_minimo. |
| `selectable` | boolean | — | — |  |
| `action` | action | — | — |  |

#### `inv.ComparePanel`
*Cuándo:* El usuario pregunta '¿qué conviene más?' o '¿y si...?'. Dos columnas, mismas métricas.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `left` | object | sí | sí | `izquierda` de compare_allocations. |
| `right` | object | sí | sí | `derecha` de compare_allocations. |
| `metrics` | array | sí | sí | `filas` de compare_allocations. |
| `action` | action | — | — | Al elegir un lado. |
| `disclaimer` | string | sí | — |  |

#### `inv.AmountSlider`
*Cuándo:* Dejar que el usuario simule variaciones. Mover el slider NO remonta componentes: dispara updateDataModel.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `label` | string | sí | — |  |
| `value` | number | sí | sí | Enlaza a una ruta del data model para binding bidireccional. |
| `min` | number | sí | — |  |
| `max` | number | sí | — |  |
| `step` | number | — | — |  |
| `format` | moneda|porcentaje|numero|anios | — | — |  |
| `action` | action | sí | — | Se dispara al soltar, no en cada pixel. |

#### `inv.OrderTicket`
*Cuándo:* Ejecutar. Es el único componente que mueve dinero y exige confirmación en dos pasos.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `order` | object | sí | sí | Respuesta de place_order en estado pendiente: {folio, monto, legs, saldo_antes, saldo_despues_estimado}. |
| `action` | action | sí | — | Debe ser place_order. |
| `requiresConfirmation` | boolean | sí | — | Siempre true. El renderer rechaza el ticket si viene en false. |
| `disclaimer` | string | sí | — |  |

#### `inv.FactSheet`
*Cuándo:* El usuario pidió el detalle de un instrumento concreto.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `instrument` | object | sí | sí | Respuesta de get_instrument_factsheet. |
| `mostrarHistoria` | boolean | — | — |  |

#### `inv.PositionsTable`
*Cuándo:* Después de ejecutar, o cuando el usuario pregunta '¿cómo voy?'. Es el estado de cuenta.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `positions` | array | sí | sí | `posiciones` de get_client_snapshot. |
| `resumen` | object | — | sí | `inversion` de get_client_snapshot: {costo_total, valor_mercado, rendimiento}. |
| `action` | action | — | — |  |

#### `inv.SpendingBreakdown`
*Cuándo:* Justificar de dónde sale la capacidad de ahorro, o responder sobre gasto.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `categorias` | array | sí | sí | `por_categoria` de get_spending_summary. |
| `capacidadAhorro` | number | sí | sí |  |
| `ingresoMensual` | number | sí | sí |  |

#### `bank.AccountsOverview`
*Cuándo:* Panorama de cuentas y tarjetas: saldos, alias, estado de cada tarjeta. Sustituye cualquier lista de cuentas en texto. Tocar una tarjeta pide administrarla.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `cuentas` | array | sí | sí | `cuentas` de get_accounts: [{account_id, tipo, alias, moneda, saldo_disponible}]. |
| `tarjetas` | array | sí | sí | `tarjetas` de get_accounts: [{card_id, tipo, alias, last4, estado, limite_credito, saldo_utilizado}]. |

#### `bank.CardManager`
*Cuándo:* Administrar UNA tarjeta: bloquear/desbloquear, ajustar límite (solo crédito) y ponerle alias. Se monta después de `manage_card` desde `bank.AccountsOverview`.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `card` | object | sí | sí | Una tarjeta de `tarjetas` (get_accounts), o el resultado de block_card/unblock_card/set_card_limit/set_card_alias. |
| `ingresoMensual` | number | sí | sí | Para el tope del slider de límite: no deja pasar de 3x esto. |

#### `bank.SpendingBudgets`
*Cuándo:* Presupuestos por categoría contra el gasto real, con aviso de excedidos. Para 'control de gasto' o '¿voy bien con mi presupuesto?'. Si `alertas` viene vacío, es que el cliente no ha configurado ninguno: ofrece ponerle uno, no inventes cifras.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `alertas` | array | sí | sí | `alertas` de get_spending_alerts: [{categoria, presupuesto, gastado, restante, porcentaje, excedido}]. |

#### `bank.TransactionSearch`
*Cuándo:* Resultados de una búsqueda de movimientos con filtros aplicados. Nunca enlistes movimientos filtrados en texto; para 'mis últimos movimientos' sin filtro considera si de plano no hace falta filtrar.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `movimientos` | array | sí | sí | `movimientos` de search_transactions o get_transactions. |
| `filtros` | object | — | sí | `filtros` de search_transactions, para mostrar qué se está filtrando. |
| `resumen` | object | — | sí | {total_cargos, total_abonos, total} de search_transactions. |
| `movimientosCompletos` | array | — | sí | Caché completo para filtrar sin volver a llamarte (regla 8c). Escríbelo UNA sola vez, al montar el componente por primera vez, con el mismo arreglo que mandas a `movimientos`. |


### Primitivos

#### `Column`
*Cuándo:* Apilar cosas verticalmente. Es la raíz habitual de una superficie.
*Anida:* sí, vía `children: [ids]`.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `gap` | number | — | — | Separación en px. |
| `align` | start|center|end|stretch | — | — |  |

#### `Row`
*Cuándo:* Poner cosas lado a lado. Colapsa a columna en pantalla angosta.
*Anida:* sí, vía `children: [ids]`.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `gap` | number | — | — |  |
| `align` | start|center|end|baseline | — | — |  |
| `wrap` | boolean | — | — |  |

#### `Card`
*Cuándo:* Agrupar un bloque con título. No la uses para envolver un solo Text.
*Anida:* sí, vía `children: [ids]`.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `title` | string | — | sí |  |
| `subtitle` | string | — | sí |  |
| `tone` | neutral|info|warning|danger | — | — |  |

#### `Text`
*Cuándo:* Texto. Un párrafo corto, un encabezado, una aclaración.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `text` | string | sí | sí |  |
| `variant` | h1|h2|h3|body|caption | — | — |  |
| `tone` | default|muted|positive|negative | — | — |  |

#### `Divider`
*Cuándo:* Separar dos bloques cuando el espacio no alcanza.

#### `Button`
*Cuándo:* Una acción que el usuario puede tomar. Siempre lleva `action`.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `label` | string | sí | — |  |
| `action` | action | sí | — |  |
| `variant` | primary|secondary|ghost | — | — |  |
| `disabled` | boolean | — | sí |  |

#### `Badge`
*Cuándo:* Etiqueta corta de estado: 'Moderado', 'Ejecutada', 'Simulado'.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `label` | string | sí | sí |  |
| `tone` | neutral|info|positive|warning|danger | — | — |  |

#### `Stat`
*Cuándo:* Una cifra sola con su etiqueta. Tres o cuatro en un Row leen mejor que un párrafo.

| prop | tipo | obl. | enlazable | nota |
|---|---|---|---|---|
| `label` | string | sí | — |  |
| `value` | number | sí | sí |  |
| `format` | moneda|porcentaje|numero|texto | — | — |  |
| `delta` | number | — | sí |  |
| `hint` | string | — | — |  |
