# dynamic-ui-banking

Interfaz bancaria generativa: el agente no escribe la respuesta, la **construye**.
Reto UI Generativa (Banorte × Tec de Monterrey, HackMTY 2026).

El usuario escribe «tengo 80 mil pesos parados y los podría dejar 5 años». El
agente descubre que no hay perfil de riesgo vigente, así que en lugar de
preguntar en texto **monta un perfilador**. Con las respuestas pide el score al
banco, propone una asignación, la simula y reescribe la pantalla como dona +
proyección + sliders. El usuario mueve un slider y la gráfica se recalcula sin
remontar nada. Pregunta «¿y si fuera más conservador?» y aparece un panel
comparativo que nadie programó como pantalla. Confirma, y la superficie se
convierte en un estado de cuenta con folio real.

Tres superficies distintas de la misma conversación, y una acción con efecto.

---

## Arrancar

```bash
make install      # deps de Python y de npm
make seed         # genera la base simulada del banco (semilla fija)
make catalog      # artefactos derivados del catálogo A2UI
make fixtures     # guion grabado del front

# con API key: agente real
cp .env.example .env    # y pon tu ANTHROPIC_API_KEY real ahí — .env nunca se commitea
make api          # terminal 1 · gateway en :8000 (carga .env con python-dotenv)
make web          # terminal 2 · front en :5173

# sin API key ni backend: guion grabado con datos reales
make web          # y abre http://localhost:5173/?mock=1
```

**La clave nunca toca el repo.** `.env` está en `.gitignore`;
`gateway/main.py` la carga con `load_dotenv()` al arrancar y nada más lo
necesita — ni siquiera `mcp_server/`, que corre en su propio subproceso sin
heredar variables de entorno arbitrarias. Ver `.env.example` para la lista
completa de variables y las reglas de manejo.

Antes de empujar nada:

```bash
make check        # tests + smoke + catálogo alineado + invariantes + typecheck
```

---

## Qué hay aquí

```
dynamic-ui-banking/
├─ bank/            simulación de la base del banco + motor financiero
│  ├─ schema.sql       core bancario e inversiones
│  ├─ seed.py          generador determinista (semilla 20260912)
│  ├─ instrumentos.py  24 instrumentos, sus correlaciones y los bloques
│  └─ finance/         riesgo, reglas de asignación, Monte Carlo, comparación
├─ services/        la única superficie que el agente puede tocar (15 servicios)
├─ mcp_server/      servidor MCP standalone que expone services/ por stdio
├─ a2ui/            catalog.json (fuente única de verdad) + validador + contrato
├─ agent/           loop propio sobre el SDK nativo de Anthropic + cliente MCP
├─ gateway/         FastAPI + SSE, sesiones, bitácora y ciclo de vida del MCP
├─ web/             renderer A2UI, registry y componentes inv.* (charts con Recharts)
├─ scripts/         generadores de artefactos y smoke del ciclo completo
└─ docs/            arquitectura, trade-offs y guion de la demo
```

---

## Las cuatro decisiones que sostienen el proyecto

### 1. El modelo no hace aritmética

Ningún monto, porcentaje, proyección, score ni folio sale del modelo. Todo
número que llega a pantalla viene de un `tool_result` calculado en
`bank/finance/`. El system prompt lo prohíbe explícitamente, y el Monte Carlo es
determinista —la semilla se deriva de los argumentos con BLAKE2b— así que mover
un slider y regresarlo devuelve exactamente los mismos números. En un demo en
vivo eso importa.

### 2. El catálogo es la fuente única de verdad

`a2ui/catalog.json` define 18 componentes (8 primitivos, 10 de dominio) y las 8
acciones válidas. De ahí se generan, y nunca se escriben a mano:

| Artefacto | Generado por | Consumido por |
|---|---|---|
| `agent/catalog_prompt.md` | `scripts/gen_catalog_artifacts.py` | el system prompt |
| `web/src/catalog.types.ts` | el mismo script | el renderer |
| el validador Pydantic | `a2ui/models.py` lee el JSON | el loop del agente |

`a2ui/tests/test_contract.py` falla si los tres se desalinean, y
`web/src/registry.check.ts` hace que `tsc` falle si un componente del catálogo
no tiene React detrás. **Regla de equipo: nadie agrega un componente sin
agregarlo al `catalog.json` primero.**

El modelo compone con componentes gordos de dominio (`inv.AllocationDonut`,
`inv.ProjectionChart`, `inv.ComparePanel`) en lugar de con `Row`/`Column`/`Text`
sueltos. Menos tokens, menos alucinación, y apariencia bancaria desde el primer
render.

### 3. Validación con reintento, no con fe

`render_surface` es la única tool de presentación y su argumento se intercepta
antes de llegar al navegador:

```
render_surface → validate_a2ui → ok    → se emiten los mensajes A2UI
                        └──────→ error → tool_result is_error → el modelo corrige
                                         (2 intentos, luego plantilla estática)
```

Los mensajes de error están escritos para que el modelo se corrija solo: dicen
qué componente, qué prop, qué estaba mal y cuáles son los valores válidos. No
«invalid component», sino:

> `updateComponents.components[0]`: el componente `'inv.CryptoWidget'` no está en
> el catálogo y el renderer lo va a ignorar. Componentes de dominio:
> `inv.AllocationDonut`, `inv.ComparePanel`, … Primitivos: `Badge`, `Button`, …

El renderer, además, aplica una allowlist propia: A2UI son **datos, no código**,
y lo que no está en el registry no se monta pase lo que pase en el servidor.

### 4. Nada mueve dinero sin dos pasos

`place_order` se llama dos veces. La primera valida todo, registra la orden como
`pendiente` y devuelve un `confirmation_token`; la segunda ejecuta. El modelo no
puede saltarse el paso porque no puede inventar el token, y `idempotency_key` es
`UNIQUE` en la base, así que un reintento devuelve el mismo folio con
`duplicado: true` en lugar de comprar dos veces. El candado existe en las tres
capas —componente, agente y banco— y `tests/test_agent_loop.py` prueba que un
token inventado no ejecuta.

---

## El SDK nativo de Anthropic

Sin LangChain ni frameworks de agentes: `anthropic.AsyncAnthropic` +
`messages.stream` + un `while` propio (`agent/loop.py`, ~300 líneas).

La razón es concreta: necesitamos interceptar `render_surface` entre el modelo y
el cliente para validarlo y devolverle el error. Un framework que resuelve el
loop por ti no deja meter ese paso.

Lo que el loop hace y un wrapper no haría igual de bien:

- **Prompt caching con un solo punto de corte.** El system prompt son cuatro
  bloques (identidad, reglas, catálogo, few-shots); el `cache_control` va en el
  último y el contexto de sesión se manda *después*, para que cambiar de turno no
  invalide el prefijo.
- **Errores de servicio como información, no como excepciones.** Un
  `ServiceError` se convierte en `tool_result` con `is_error=true` y el modelo
  sigue trabajando.
- **Límites duros.** Máximo 12 vueltas de encadenado y 2 reintentos de render;
  después, plantilla estática. El usuario nunca se queda con la pantalla en
  blanco.
- **Redacción en la traza.** Los `confirmation_token` no salen al panel de
  depuración: en un demo la pantalla se proyecta.

---

## Las tools de datos viven en un MCP separado

`mcp_server/` es un proceso propio: expone `services.REGISTRO` por MCP
(`list_tools` / `call_tool`, stdio) y no sabe nada de A2UI, prompts, ni de
Claude. El gateway lo levanta como subproceso al arrancar y lo cierra al
apagarse (`lifespan` en `gateway/main.py`); `agent/loop.py` le habla como
cliente MCP (`agent/mcp_client.py`) y ya no importa `services` directo.

Los schemas no se duplican: el servidor MCP construye su `list_tools()` desde
`agent/tools.py::TOOLS_DATOS` — la misma lista que antes se le pasaba directo
al SDK de Anthropic. Un solo lugar describe cada tool.

```bash
make mcp   # correrlo aislado, para inspeccionarlo con un cliente MCP externo
```

Los tests del loop usan `tests/fake_mcp.py` (llama `services` en el mismo
proceso, sin subproceso) para no pagar el costo en cada corrida;
`tests/test_mcp_server.py` prueba el servidor real por stdio, y `make smoke`
corre el ciclo completo de seis turnos contra ese mismo servidor real.

---

## La simulación del banco

Todo sintético, generado con semilla fija (`SEED = 20260912`). `make seed` es
reproducible byte a byte.

**Core bancario:** 8 clientes con cuentas, 18 meses de movimientos con barrido de
fin de mes, tarjetas de débito y crédito, y créditos con amortización real.

**Inversiones:** 24 instrumentos con perfil riesgo-rendimiento plausible para
México a 2026 (CETES, bonos M, UDIBONOs, pagarés, fondos, ETFs, FIBRAs), 120
meses de series por instrumento con GBM correlacionado entre clases de activo
vía Cholesky, posiciones y órdenes.

Dos detalles del modelo que vale la pena defender:

- `rend_esperado_anual` es rendimiento **aritmético** esperado, así que la deriva
  logarítmica es `log1p(mu) − σ²/2`. El arrastre por volatilidad es real y no se
  esconde: la trayectoria mediana rinde menos que la media.
- Con aportaciones mensuales, `(final/aportado)^(1/años) − 1` **miente**: trata el
  dinero del mes 59 como si hubiera estado invertido cinco años. Se reporta la
  **TIR** por bisección sobre los flujos reales.

**Invariante del demo:** `CLI-0001` no tiene perfil de riesgo vigente. Es lo que
hace que el agente monte el perfilador en lugar de proponer a ciegas, y
`bank/seed.py --check` falla si alguien lo rompe.

---

## La simulación del sistema de componentes

`web/src/fixtures/demo.json` es el guion completo —los seis turnos, los mismos
blueprints, los mismos números— generado por `scripts/gen_fixtures.py` desde los
servicios reales. Con `?mock=1` el front lo reproduce con el ritmo del streaming
y sin tocar la red.

Sirve para tres cosas: desarrollar el renderer sin gastar tokens, tener un
respaldo interactivo si la API se cae a media presentación, y —lo más útil— los
blueprints del guion pasan por el **mismo validador** que los del modelo, así que
si el catálogo cambia, el guion se rompe y nos enteramos.

---

## Verificación

```
215 tests
  a2ui/tests/test_contract.py    catálogo bien formado, artefactos alineados,
                                 casos inválidos (incl. spec A2UI real: action
                                 anidado, deleteSurface) y que cada error sea accionable
  tests/test_finance.py          monotonía del score, tope por horizonte, pesos que
                                 suman 1, percentiles que no se cruzan, diversificación
                                 que baja la volatilidad, comisiones que se cobran
  tests/test_services.py         cuadre de cifras, errores con sugerencia, los dos
                                 pasos de la orden, idempotencia, token nunca expuesto
  tests/test_agent_loop.py       encadenado de tools (vía MCP falso), validación con
                                 reintento, fallback, bitácora, límites
  tests/test_mcp_server.py       el servidor MCP real por stdio: list_tools,
                                 llamada exitosa, tool desconocida, error de servicio

make smoke   ciclo completo de seis turnos contra el SERVIDOR MCP REAL
             (subproceso propio) y un cliente de Anthropic falso. Sin tokens.
```

El front se verificó manejando el guion completo en Chromium: seis turnos, la
consola limpia, y sin desbordamiento horizontal a 400 px.

---

## Documentación

- [`docs/arquitectura.md`](docs/arquitectura.md) — las capas, qué hace y qué no hace cada una
- [`docs/trade-offs.md`](docs/trade-offs.md) — qué se descartó y qué costó
- [`docs/demo.md`](docs/demo.md) — guion de tres minutos y plan B

---

## Aviso

Todos los datos son sintéticos. No hay información real de ningún cliente, los
instrumentos son inventados y las operaciones no mueven dinero. Esto no es
asesoría de inversión.
