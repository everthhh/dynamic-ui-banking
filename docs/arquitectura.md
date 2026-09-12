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
    │                                 │                          ┌──────────┐
    │        POST /action             │                          │ services │
    └─────────────────────────────────┘                          └────┬─────┘
              acción del usuario                                      │
                                                              ┌───────▼───────┐
                                                              │ bank (SQLite) │
                                                              │ + finance/    │
                                                              └───────────────┘
```

**Regla dura:** la interacción del usuario nunca actualiza la UI por su cuenta.
Mover un slider escribe el valor local para que el control se sienta inmediato,
pero la pantalla solo cambia cuando el agente lo decide. Por eso `emitirAccion`
vive en el store y no dentro de cada componente.

## Quién hace qué

| Capa | Hace | No hace |
|---|---|---|
| `web/` | Aplicar mensajes A2UI, montar componentes, mantener el data model, emitir acciones | No decide layout, no calcula, no sabe qué significa ningún prop |
| `gateway/` | Sesiones, historial, streaming SSE, `/action`, bitácora | No habla con el modelo, no calcula |
| `agent/` | Interpretar, encadenar tools, emitir y validar el blueprint | No hace aritmética financiera, no toca la base |
| `services/` | Validar entradas, orquestar dominio, devolver JSON | No sabe nada de A2UI, de componentes ni de prompts |
| `bank/` | Datos y cálculo determinista | No sabe que existe un modelo de lenguaje |

Cada capa solo conoce a la de abajo. `services/` no importa nada de `agent/`, y
`bank/` no importa nada de `services/`. Eso es lo que permite probar el motor
financiero sin levantar nada y probar el agente sin API key.

## Los cuatro mensajes A2UI

Un mensaje lleva **exactamente una** acción.

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

// 4. el usuario hizo algo
{"version":"v0.9","action":{"name":"simulate","surfaceId":"inv-main",
  "context":{"amount":80000,"horizon":5,"monthly":2500}}}
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

1. Un servidor de servicios por dominio (`inv`, `credit`, `spend`, `insurance`).
2. Un catálogo por dominio, mismo formato, prefijo distinto; el `catalogId` dice
   cuál cargar.
3. Un router de intención al frente: una llamada barata clasifica el dominio y
   carga solo ese catálogo y esas tools.
4. Componentes transversales: `inv.ProjectionChart` y `inv.ComparePanel` sirven
   igual para amortización de crédito o cobertura de seguro.

El esquema ya trae el core bancario completo (tarjetas, créditos, categorización
de gasto) precisamente para que abrir el segundo dominio no exija rehacer la
base.

**Criterio de corte:** un segundo dominio solo se abre cuando el primero está
completo y ensayado.
