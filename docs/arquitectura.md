# Arquitectura

## El ciclo

```
  usuario
    │ texto
    ▼
┌─────────┐   POST /chat (SSE)   ┌──────────┐   messages.stream   ┌────────┐
│ renderer│ ───────────────────► │ gateway  │ ──────────────────► │ agente │
│  React  │                      │ FastAPI  │                     │ Claude │
└─────────┘ ◄─────────────────── └──────────┘ ◄────────────────── └────────┘
    ▲         eventos a2ui            │  tool_use          tool_result  │
    │                                 │                                 ▼
    │                                 │                    cliente MCP (stdio)
    │        POST /action             │                                 │
    └─────────────────────────────────┘                                 ▼
              acción del usuario                              ┌──────────────────┐
                                                               │ mcp_server/       │
                                                               │ (subproceso propio)│
                                                               └────────┬──────────┘
                                                                        ▼
                                                                 ┌──────────┐
                                                                 │ services │
                                                                 └────┬─────┘
                                                                      │
                                                              ┌───────▼───────┐
                                                              │ bank (SQLite) │
                                                              │ + finance/    │
                                                              └───────────────┘
```

`mcp_server/` es un proceso separado de verdad: el gateway lo levanta como
subproceso al arrancar (`lifespan` en `gateway/main.py`) y le habla por stdio.
`agent/loop.py` no importa `services` — solo conoce `agent/mcp_client.py`.

**Regla dura:** la interacción del usuario nunca actualiza la UI por su cuenta.
Mover un slider escribe el valor local para que el control se sienta inmediato,
pero la pantalla solo cambia cuando el agente lo decide. Por eso `emitirAccion`
vive en el store y no dentro de cada componente.

## Quién hace qué

| Capa | Hace | No hace |
|---|---|---|
| `web/` | Aplicar mensajes A2UI, montar componentes, mantener el data model, emitir acciones | No decide layout, no calcula, no sabe qué significa ningún prop |
| `gateway/` | Sesiones, historial, streaming SSE, `/action`, bitácora, levantar/cerrar el subproceso MCP | No habla con el modelo, no calcula |
| `agent/` | Interpretar, encadenar tools (vía el cliente MCP), emitir y validar el blueprint | No hace aritmética financiera, no toca la base, no importa `services` |
| `mcp_server/` | Exponer `services.REGISTRO` como tools MCP (`list_tools`/`call_tool`) por stdio | No sabe nada de A2UI, de prompts ni de qué modelo lo está llamando |
| `services/` | Validar entradas, orquestar dominio, devolver JSON | No sabe nada de A2UI, de componentes ni de prompts |
| `bank/` | Datos y cálculo determinista | No sabe que existe un modelo de lenguaje |

Cada capa solo conoce a la de abajo. `services/` no importa nada de `agent/` ni
de `mcp_server/`, y `bank/` no importa nada de `services/`. Eso es lo que
permite probar el motor financiero sin levantar nada, probar el agente sin API
key (`tests/fake_mcp.py`) y probar el servidor MCP real sin tocar el modelo
(`tests/test_mcp_server.py`).

## Los cuatro mensajes A2UI (servidor → cliente)

Un mensaje lleva **exactamente una** acción de servidor. `render_surface` solo
puede emitir estas cuatro — están validadas contra los schemas reales del
spec (`specification/v0_9/json/server_to_client.json` en el repo oficial de
A2UI).

```jsonc
// 1. superficie nueva: cambió la tarea
{"version":"v0.9","createSurface":{"surfaceId":"inv-main","catalogId":"…","theme":{…}}}

// 2. cambió lo que el usuario quiere ver
{"version":"v0.9","updateComponents":{"surfaceId":"inv-main","components":[
  {"id":"root","component":"Column","children":["h","donut","proj"]},
  {"id":"h","component":"Text","text":"Propuesta balanceada a 5 años","variant":"h2"},
  {"id":"donut","component":"inv.AllocationDonut",
   "slices":{"path":"/propuesta/slices"},"total":{"path":"/propuesta/monto"}}]}}

// 3. mismos componentes, datos nuevos: no parpadea
{"version":"v0.9","updateDataModel":{"surfaceId":"inv-main","path":"/sim","value":{…}}}

// 4. la superficie ya no aplica (cerró el flujo, cambió de tarea del todo)
{"version":"v0.9","deleteSurface":{"surfaceId":"inv-estado-anterior"}}
```

**`action` no es un quinto mensaje de servidor.** En el spec real es
client-to-server: es el prop de un componente (`Button`, `inv.AmountSlider`,
…), va anidado como `{"event":{"name":…,"context":{…}}}`, y es el **cliente**
quien lo reporta de vuelta —con `sourceComponentId` y `timestamp`— cuando el
usuario interactúa:

```jsonc
// prop de un componente (lo escribe el agente en updateComponents)
{"id":"slider","component":"inv.AmountSlider","label":"Monto",
 "value":{"path":"/sim/monto"},"min":10000,"max":300000,
 "action":{"event":{"name":"simulate"}}}

// lo que el CLIENTE manda a POST /action al soltar el slider
{"version":"v0.9","session_id":"ses-…","action":{
  "name":"simulate","surfaceId":"inv-main","sourceComponentId":"slider",
  "timestamp":"2026-09-12T10:00:00Z","context":{"amount":120000}}}
```

**El truco de rendimiento:** mover un slider produce un solo `updateDataModel`.
Los componentes no se remontan, así que la gráfica se redibuja sin que la
pantalla parpadee. Elegir mal entre `updateDataModel` y `updateComponents` es la
diferencia entre una UI que se siente viva y una que se siente un refresh.

**Binding bidireccional.** Un componente apunta a una ruta
(`{"path":"/sim/horizonte"}`). Hacia abajo el agente escribe y el componente se
redibuja; hacia arriba el usuario mueve el control, el cliente actualiza la ruta
de inmediato y ese valor viaja en el `context` de la siguiente acción. El data
model es un árbol JSON con escrituras inmutables que clonan solo la rama tocada:
mover un slider no copia una serie de 5000 puntos.

## El catálogo como fuente única de verdad

```
                          a2ui/catalog.json
                                  │
          ┌───────────────────────┼───────────────────────┐
          ▼                       ▼                       ▼
  agent/catalog_prompt.md   a2ui/models.py      web/src/catalog.types.ts
    (system prompt)           (validador)        (tipos del renderer)
          │                       │                       │
          └───────── test_contract.py ──────┘   registry.check.ts (tsc)
```

Dos guardias independientes:

- `a2ui/tests/test_contract.py` corre el generador con `--check` y falla si
  alguien editó el catálogo sin regenerar.
- `web/src/registry.check.ts` hace que `tsc --noEmit` falle si un componente del
  catálogo no tiene implementación en React, o si hay una implementación que no
  está en el catálogo.

## Confianza

| Mecanismo | Dónde vive | Qué evita |
|---|---|---|
| Allowlist del catálogo | `store.ts` + `registry.ts` | Que un componente inventado se monte. A2UI son datos, no código |
| Validación con reintento | `agent/loop.py` + `a2ui/models.py` | Blueprints rotos en pantalla |
| Plantilla estática | `agent/fallback.py` | Que el usuario se quede sin pantalla |
| Confirmación en dos pasos | componente, agente y `services/orders.py` | Que el modelo ejecute por su cuenta |
| Idempotencia (`UNIQUE`) | `bank/schema.sql` | Que un reintento compre dos veces |
| Disclaimers como props | `a2ui/catalog.json` | Que el modelo redacte sus propias advertencias |
| Bitácora del blueprint | `surface_log` | Que una sesión no se pueda reconstruir |
| Redacción de tokens | `agent/loop.py` | Que un token salga en la traza proyectada |

## Escalar a otros dominios

Banca personal (`bank.*`) es el segundo dominio, y confirmó que el patrón
escala sin fricción: **no** hizo falta un servidor MCP nuevo ni un catálogo
aparte. Un dominio nuevo es:

1. Tablas nuevas en `bank/schema.sql` + servicios en `services/<dominio>.py`
   (lectura) y, si hace falta mutar algo, un módulo de efecto aparte —
   `services/banking.py` es al `bank.*` lo que `services/orders.py` es al
   `inv.*`.
2. Entradas nuevas en `agent/tools.py::TOOLS_DATOS` — el mismo `mcp_server/`
   las recoge solo, porque construye `list_tools()` desde ahí.
3. Componentes nuevos en `a2ui/catalog.json` bajo un prefijo propio
   (`bank.*`), en el MISMO archivo y el mismo `catalogId` que `inv.*` — un
   catálogo por dominio aparte no se necesitó, y separar por `catalogId`
   sigue siendo la opción si un dominio se vuelve tan grande que conviene
   cargarlo aparte.
4. Componentes React + entrada en `registry.ts`. `test_contract.py` y
   `registry.check.ts` fallan solos si falta alguno de los tres.

Componentes transversales ya se repiten: `inv.ProjectionChart` sirve igual
para proyección de inversión que para amortización de crédito; el patrón
slider-suelta-confirma de `inv.AmountSlider` es el mismo que usan
`bank.CardManager` y `bank.SpendingBudgets`.

El esquema ya trae el core bancario completo (tarjetas, créditos, categorización
de gasto) precisamente para que abrir un dominio nuevo no exija rehacer la
base.

**Criterio de corte, sin cambios:** un dominio nuevo solo se abre cuando el
anterior está completo y ensayado. Faltan Crédito (recalificación,
amortización, refinanciamiento), Pagos, Seguros y Educación financiera.
