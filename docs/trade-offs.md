# Trade-offs

Lo que se decidió, contra qué, y qué costó.

| Decisión | Alternativa descartada | Por qué | Costo aceptado |
|---|---|---|---|
| **Catálogo de dominio** (`inv.*` gordos) | Solo primitivos A2UI y que el modelo componga `Row`/`Column`/`Text` | Menos tokens por render, mucha menos alucinación, y apariencia bancaria desde el primer blueprint | Abrir un dominio nuevo exige componentes nuevos |
| **Composición libre sobre catálogo cerrado** | Plantillas fijas por intención | Las plantillas no son UI generativa y el jurado lo nota en treinta segundos | Hace falta validador con reintento |
| **SDK nativo de Anthropic** | LangChain u otro framework de agentes | Necesitamos interceptar `render_surface` entre el modelo y el cliente para validarlo; un framework que resuelve el loop no deja meter ese paso | ~300 líneas de loop propio |
| **Cálculo en `bank/finance/`** | Que el modelo estime rendimientos | Determinismo y auditabilidad. Un demo donde el mismo slider da números distintos dos veces está muerto | Más código de dominio |
| **Monte Carlo con semilla derivada de los argumentos** | Semilla del reloj | Mover un slider y regresarlo devuelve exactamente los mismos números | Ninguno real |
| **TIR por bisección** | `(final/aportado)^(1/años) − 1` | Con aportaciones mensuales la fórmula simple subestima ~3 puntos: trata el dinero del mes 59 como si llevara cinco años invertido | 200 iteraciones de bisección por simulación (imperceptible) |
| **Shocks centrados en el generador de series** | GBM crudo | El historial sintético no se desvía del rendimiento declarado por puro azar de la muestra, que es lo que hace que un juez pregunte «¿por qué tu ETF rindió 3% en diez años?» | Las series son ilustrativas, no un backtest. Se dice en el código y en el `disclaimer` |
| **A2UI v0.9** | v0.8 (`beginRendering`, `literalString`) | Sintaxis mucho más compacta | El ecosistema se mueve; fijamos la versión y validamos contra ella |
| **`action` anidado como `{"event":{"name","context"}}` + `deleteSurface`** | `{"name","context"}` plano, sin `deleteSurface` (implementación original, antes de comparar contra `specification/v0_9/json/*.json` del repo oficial) | Es lo que dice el schema real (`common_types.json#/$defs/Action`, `client_to_server.json`); un `action` a secas tampoco es un mensaje que el agente pueda emitir en el spec real — es client-to-server, nunca al revés | Hubo que tocar los 8 componentes que emiten acciones, el validador, el prompt y el guion grabado |
| **Renderer React propio** | Renderer oficial (Lit / Angular) | El de React aún está en desarrollo y el reto exige componentes propios | ~100 líneas de renderer |
| **Recharts para `inv.ProjectionChart` y `inv.AllocationDonut`** | SVG a mano (decisión original) / D3 / Chart.js | Menos código propio que mantener (ejes, ticks, tooltip, hit-testing del donut), sin perder el control fino (el hueco de la dona con el monto y el hover que explica el bloque siguen siendo un overlay propio, porque Recharts no expone ese slot) | ~30 kB gzip al bundle; se acepta porque el catálogo ya tiene dos componentes de gráfica y va a crecer |
| **MCP separado (`mcp_server/`)** | Tools declaradas directo en el SDK sobre `services.REGISTRO` (decisión original) | El reto lo pide explícito. El agente le habla al servidor por stdio como cliente MCP (`agent/mcp_client.py`); `agent/loop.py` ya no importa `services` | Un subproceso más que levantar (lo hace el gateway solo, por `lifespan`); los tests usan `tests/fake_mcp.py` para no pagar el costo en cada corrida — `tests/test_mcp_server.py` prueba el servidor real por separado |
| **`agent/tools.py` como fuente única de los schemas** | Reescribir las tools otra vez en `mcp_server/` | El servidor MCP lee `TOOLS_DATOS` para construir `list_tools()`; el test que ya existía (`test_cada_tool_declarada_existe_como_servicio`) sigue siendo la única guardia que hace falta | Ninguno: es el mismo patrón que ya usaba el catálogo A2UI para no desincronizarse |
| **Estado en el servidor, cliente optimista** | Estado solo en el cliente | Bitácora, reconexión y auditoría | Un round-trip más |
| **SSE sobre POST** | WebSocket | El flujo es unidireccional y es trivial en FastAPI | Parser de stream a mano (`EventSource` solo hace GET) |
| **Zustand** | Redux, o Context puro | El store es chico y necesita escrituras desde fuera de React (el transporte SSE) | Una dependencia más |
| **SQLite** | Postgres | Cero infraestructura, `make seed` en dos segundos, y el archivo se versiona si hace falta | Un solo escritor; irrelevante a esta escala |
| **Fixtures generados desde los servicios** | Fixtures escritos a mano | Los números del guion son reales y los blueprints pasan por el mismo validador; si el catálogo cambia, el guion se rompe y nos enteramos | Hay que regenerar con `make fixtures` |
| **Claude Sonnet** | Opus para todo | La latencia es parte de la experiencia: una UI que tarda ocho segundos en aparecer no se siente generativa | Se compensa con few-shots y prompt caching |

## Lo que se decidió NO hacer

**Dona editable arrastrando pesos.** El catálogo declara `editable`, pero la
implementación quedó fuera del alcance. Un usuario arrastrando pesos es un
`updateDataModel` por píxel y una renormalización que hay que pensar bien; el
panel comparativo responde la misma pregunta («¿y si le muevo?») con mucho menos
riesgo y se ve mejor.

**Streaming incremental de mensajes A2UI dentro de un mismo `render_surface`.**
Hoy se valida el arreglo completo y después se emite. Emitir cada mensaje en
cuanto cierra el JSON requiere un parser tolerante y complica la validación —y la
ganancia percibida es de décimas, porque el cuello de botella es el
encadenado de tools, no el render.

**Un segundo dominio.** El esquema ya soporta crédito y gasto, y hay dos
componentes listos (`inv.SpendingBreakdown`, `get_credit_overview`), pero el
criterio de corte se respeta: el primero se termina y se ensaya antes de abrir
el segundo. Media demo de inversiones más media de crédito es peor que una
completa.

## El riesgo número uno

Pulir componentes antes de que el ciclo cierre. La UI bonita es el 10 % de la
rúbrica; que **cambie y sirva** es el 45 %. Por eso el hito de la hora 12 era
«intención → UI → acción → UI nueva», feo pero completo, y por eso `make smoke`
existe: contesta en diez segundos si el ciclo sigue cerrando.
