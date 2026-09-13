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

Y antes de que escriba nada, ya hay algo en pantalla. El banco leyó sus últimos
12 meses —movimientos, estados de cuenta de la tarjeta, créditos, saldos,
posiciones— y calculó su **perfil financiero**: cuánto gana y cómo le llega,
en qué gasta, cómo paga la tarjeta, cuánto colchón tiene y cuánto dinero tiene
parado. Encima de ese perfil van las **recomendaciones**, en orden: «tienes 290
mil pesos sin invertir», «tu tarjeta cobra 47% y pagas el mínimo», cada una con
la evidencia que la dispara, su impacto en pesos y la herramienta del catálogo
que la resuelve. Tocar una arranca esa herramienta. Ese tablero no llama al
modelo.

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

# un depósito en efectivo lo acredita la tienda, no el agente:
make deposito REF=<referencia de 16 dígitos> MONTO=2000
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

## Guía de prueba paso a paso

Pensada para alguien que clona el repo por primera vez y necesita verificar,
de punta a punta, que todo funciona — instalación, suite automatizada y un
recorrido manual guiado por la UI.

### 0. Requisitos

| Herramienta | Mínimo | Verificar con | Notas |
|---|---|---|---|
| Python | 3.10+ | `python3 --version` | El código usa `str \| None` (PEP 604); no corre en 3.9 o anterior. |
| Node.js | 18+ | `node --version` | Lo pide Vite 5. |
| npm | 9+ | `npm --version` | Viene con Node. |
| API key de Anthropic con crédito | — | — | [console.anthropic.com](https://console.anthropic.com) → *Billing*. Sin crédito, el paso 4 falla con `400 - Your credit balance is too low`. |

**Windows:** el Makefile usa `PY := python3`. Si tu `python3` responde *"Python was
not found; run without arguments to install from the Microsoft Store"*, es el
alias de la tienda, no un intérprete real. Sustitúyelo por `py` (el Python
Launcher) anteponiendo `PY=py` a cualquier target: `make PY=py install`,
`make PY=py seed`, etc.

### 1. Sincronizar con el remoto

```bash
git fetch origin
git status                       # debe decir "up to date with 'origin/main'"
git pull --ff-only origin main   # si no lo está
```

Si `bank/schema.sql` cambió desde tu último pull, tu base local queda
desalineada con el código — el paso 3 la regenera; no lo saltes.

### 2. Instalar dependencias

```bash
make install
# Windows, si `python3` no resuelve:
make PY=py install
```

Instala `requirements.txt` (Python, vía pip) y `web/node_modules` (npm). Una
corrida limpia no debe imprimir errores en rojo de `pip` ni de `npm`.

### 3. Regenerar la base simulada

```bash
make seed
# Windows: make PY=py seed
```

Salida esperada, exacta:

```
Base simulada escrita en <ruta-absoluta>/data/bank.sqlite
Series exportadas a <ruta-absoluta>/data/series.parquet
Invariantes OK.
```

Si termina en `Invariantes roto:` seguido de una lista, `bank/seed.py` y
`bank/schema.sql` están desalineados: no sigas hasta que diga
`Invariantes OK.`.

### 4. Configurar la API key

```bash
cp .env.example .env
```

Edita `.env` y reemplaza `ANTHROPIC_API_KEY` por una clave real con crédito
disponible. `gateway/main.py` la carga con `python-dotenv` al arrancar; nada
más la necesita.

### 5. Verificación automatizada

Antes de tocar el navegador, confirma que el entorno está sano:

```bash
make test
```

Esperado: `527 passed` en 20-25 segundos aproximadamente. Un fallo aquí es un
problema de entorno (dependencias, base sin regenerar), no de diseño —
resuélvelo antes de continuar.

```bash
make smoke
# Windows, para evitar un UnicodeEncodeError por la codepage cp1252 de la consola:
PYTHONIOENCODING=utf-8 py -m scripts.smoke
```

Corre los seis turnos del guion completo contra el **servidor MCP real**
(subproceso propio) con un cliente de Anthropic **falso** — cero tokens
gastados. Última línea esperada:

```
El ciclo cierra: intención → tools (MCP) → UI → acción → UI nueva.
```

### 6. Arrancar la aplicación

Dos terminales, en este orden:

```bash
# Terminal 1 — gateway
make api
# Windows: make PY=py api
```

Verifica antes de seguir: `curl http://localhost:8000/health` debe devolver
`{"ok": true, "db": "...", ...}`. Si `"ok": false`, falta el paso 3.

```bash
# Terminal 2 — front
make web
```

Abre `http://localhost:5173`.

### 7. Recorrido guiado del camino feliz

| # | Acción | Resultado esperado |
|---|---|---|
| 7.0 | Abre la app sin escribir nada | Tablero inicial: saludo en el chat, `bank.FinancialProfile` (salud financiera, a dónde se va el ingreso, hábitos de consumo y de tarjeta) y `bank.Recommendations` con 3 recomendaciones visibles. En el panel de traza aparece `tool directa (sin LLM)` y **ninguna** llamada a Anthropic. |
| 7.1 | En la primera recomendación (*«Tienes … sin invertir»*) clic en **Empezar**, o escribe: *«tengo 80 mil pesos parados y los podría dejar 5 años, ¿qué hago?»* | Aparece `inv.RiskProfiler`: 4 preguntas, una a la vez, con barra de progreso. **Cero** entradas `blueprint rechazado` en el panel "Qué está pasando". |
| 7.2 | Responde las 4 preguntas | Al contestar la última: perfil calculado (ej. *Crecimiento*), dona de asignación (5-7 instrumentos) y proyección Monte Carlo con escenarios p10/p50/p90. |
| 7.3 | Clic en **"Ver cómo invertir"** | Aparece `inv.OrderTicket`: folio real (`BN-2026-XXXXXX`), desglose por instrumento con títulos, cuenta de cargo, saldo estimado. |
| 7.4 | Marca la casilla de confirmación y clic en **"Confirmar $X"** | La pantalla cambia a estado de cuenta: mismo folio, tabla de posiciones, rendimiento en `$0` (recién comprado). |
| 7.5 | Escribe: *«muéstrame mis cuentas y tarjetas»* | `bank.AccountsOverview`: cuentas con saldo, tarjetas con últimos 4 dígitos. |
| 7.6 | Clic en **"Ponle un apodo"** en una cuenta, escribe un nombre, `Enter` | El apodo aparece de inmediato. Es una acción determinista: no debe generar una llamada nueva a Anthropic en el panel de traza. |
| 7.7 | Escribe de nuevo: *«enséñame mis cuentas»* | El apodo del paso 7.6 sigue ahí. Si desaparece, es el bug de la columna `alias` — corre `make seed` y confirma que estás en `origin/main`. |
| 7.8 | Escribe: *«¿en qué se me va el dinero cada mes?»* | Desglose de gasto por categoría en un componente (nunca una lista en texto plano). |
| 7.9 | Cambia el cliente a **Diego Alcantara** | La sesión se reinicia y el tablero se rehace: salud *frágil*, rasgo *Paga tarde su tarjeta* y la primera recomendación es liquidar su tarjeta. En **Ver 3 más**, la de domiciliar el pago sale con *Próximamente*. |

### 8. Modo sin API key (opcional)

```bash
make web
```

Abre `http://localhost:5173/?mock=1` — trae el tablero inicial grabado de los 8
clientes (en el de Ana, **Empezar** en la primera recomendación arranca el
guion) y reproduce el guion grabado
(`web/src/fixtures/demo.json`) con el mismo ritmo de streaming, sin red ni
backend.

### 9. Problemas comunes

| Síntoma | Causa | Solución |
|---|---|---|
| `no such column: alias` (o cualquier columna) | Base local generada con un `schema.sql` viejo | `make seed` de nuevo, ya en la rama actual |
| `no such table: card_statements`, o el tablero no aparece al entrar | Base generada antes del perfil financiero | `make seed` de nuevo |
| `400 - Your credit balance is too low` | Sin saldo en la cuenta de Anthropic | Recargar en console.anthropic.com → Billing |
| La pantalla nunca se actualiza tras enviar un mensaje | Front y back en versiones distintas | `git pull`, reinstalar (paso 2), reiniciar ambos servidores |
| `python3`: *"not found... Microsoft Store"* | Alias de Windows, no es un intérprete | Usa `py` o antepón `PY=py` a cada `make` |
| `blueprint rechazado` se repite en casi todos los turnos | Versión del repo desalineada con el validador | `git pull origin main` |
| Caracteres corruptos al correr `scripts.smoke` en Windows | La consola usa `cp1252`, no UTF-8 | `PYTHONIOENCODING=utf-8 py -m scripts.smoke` |

---

## Qué hay aquí

```
dynamic-ui-banking/
├─ bank/            simulación de la base del banco + motor financiero
│  ├─ schema.sql       core bancario, inversiones y pagos
│  ├─ seed.py          generador determinista (semilla 20260912)
│  ├─ personas.py      hábitos de cada cliente: cómo gana, gasta y paga
│  ├─ comportamiento.py simulación por eventos: hábitos → movimientos y estados de cuenta
│  ├─ categorias.py    qué es consumo, qué es esencial y qué no es gasto
│  ├─ mercado.py       parámetros de mercado CON su procedencia y fecha
│  ├─ emisoras.py      15 emisoras BMV: fundamentales y riesgo derivado de ellos
│  ├─ carteras.py      qué empresas hay DENTRO de cada fondo (look-through)
│  ├─ instrumentos.py  24 instrumentos contratables, correlaciones y bloques
│  ├─ pagos.py         bancos SPEI, CLABE, convenios de servicios y canales de efectivo
│  └─ finance/         perfil financiero, recomendaciones, planes de deuda, riesgo,
│                      idoneidad, origen de fondos, fiscal, Monte Carlo
├─ services/        la única superficie que el agente puede tocar (44 tools)
├─ mcp_server/      servidor MCP standalone que expone services/ por stdio
├─ a2ui/            catalog.json (fuente única de verdad) + validador + contrato
├─ agent/           loop propio sobre el SDK nativo de Anthropic + cliente MCP
├─ gateway/         FastAPI + SSE, sesiones, bitácora, tablero inicial sin LLM
│                   y ciclo de vida del MCP
├─ web/             renderer A2UI, registry y componentes inv.*/bank.*/pay.* (charts con Recharts)
├─ scripts/         generadores de artefactos, smoke del ciclo completo y liquidación de depósitos
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

### 1b. Los guardarraíles son código, no prompt

Un guardarraíl que vive en el system prompt es una sugerencia. Dos controles
están en `bank/finance/` y el modelo no puede desactivarlos:

**Idoneidad** (`idoneidad.py`). Toda asignación se cruza contra el perfil
**guardado** del cliente antes de simularse y antes de ejecutarse: riesgo del
instrumento contra el perfil, techo de renta variable, concentración efectiva
por empresa y por sector **mirando dentro de los fondos**, plazo forzoso contra
el horizonte y montos mínimos. `place_order` lo verifica **dos veces** —al
registrar y al ejecutar— porque entre los dos pasos pueden pasar minutos y el
perfil pudo vencer. Si el modelo pide una propuesta «agresiva» para un cliente
con score 18, gana la base y queda escrito en `notas`.

**Origen de los fondos** (`origen.py`). No es lo mismo invertir un excedente de
la cuenta de ahorro que invertir con una tarjeta al 42%, y hasta ahora el
sistema trataba los dos casos igual. Con dinero prestado: la deuda corre en
paralelo y la referencia para «no perder» deja de ser lo aportado, el perfil
aplicable baja a conservador, y la operación se bloquea por **condición de
arbitraje** si el rendimiento esperado no supera el costo del crédito. Con el
catálogo actual el instrumento más rentable espera 14.9% y el crédito más barato
cuesta 10.75%, así que casi todo crédito queda bloqueado. Ese es el resultado
correcto, no un efecto secundario.

Por eso `simulate_portfolio` devuelve **tres** probabilidades de perder y no
una: nominal (no recuperar lo aportado), real (no ganarle a la inflación) y
contra el origen (no ganarle a la deuda o a lo que ese dinero ya rendía). Con
crédito, la única honesta es la tercera. Y cada una viene acompañada de cuánto
se pierde cuando se pierde —pérdida media condicional, VaR y CVaR 95—, porque
una probabilidad sola no distingue perder 2% de perder 40%.

### 2. El catálogo es la fuente única de verdad

`a2ui/catalog.json` define 31 componentes (8 primitivos, 23 de dominio — 10 de
`inv.*`, 6 de `bank.*` y 7 de `pay.*`) y las 26 acciones válidas. De ahí se
generan, y nunca se escriben a mano:

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

Pagos usa el mismo candado con una variante: el paso 2 es una tool aparte,
`confirm_payment(payment_id, confirmation_token)`, que no recibe ni destino ni
monto. Todo eso quedó guardado en el paso 1, así que entre lo que el usuario
revisó en pantalla y lo que se ejecuta no hay nada que el modelo pueda cambiar.

---

## El perfil financiero es la base de toda recomendación

Ninguna recomendación sale de la intuición del modelo. Salen de un perfil que el
banco **calcula** con lo que ya tiene del cliente, y cada una trae los números
que la sostienen.

```
movimientos (12 meses) ┐
estados de cuenta TDC  │     bank/finance/perfil.py        bank/finance/recomendaciones.py
créditos y saldos      ├──►  perfil financiero        ──►  11 reglas → evidencia, impacto,
posiciones             │     (flujo, consumo, crédito,     prioridad, herramienta
perfil de riesgo       ┘      liquidez, inversión)                  │
                                                                    ▼
                                                  tablero inicial (sin LLM) · get_recommendations
```

**Qué mide el perfil**, y de dónde:

| Bloque | Qué dice | Cómo se deduce |
|---|---|---|
| Flujo | ingreso (fijo o variable), consumo, pagos de crédito, intereses, cuánto le queda, meses en rojo, carga de deuda | movimientos por mes; la variabilidad del ingreso con MAD/mediana, para que un aguinaldo no vuelva «variable» un sueldo |
| Consumo | gasto por categoría con tendencia, suscripciones, gasto hormiga, cuánto va a la tarjeta | la tendencia compara **medianas** de 3 meses (un viaje suelto no es un hábito); una suscripción es un comercio que cobra casi lo mismo una vez al mes, detectada por comportamiento y no por nombre |
| Crédito | hábito de cada tarjeta (totalero, revolvente, paga el mínimo, paga tarde), intereses y comisiones, salud crediticia 0-100 con desglose | estados de cuenta vencidos: cuánto debía al corte, cuál era el mínimo, cuánto pagó y cuándo |
| Liquidez | colchón en meses contra el objetivo (3 con ingreso fijo, 6 con variable), efectivo sin invertir y lo que deja de ganar | saldos + fondos de liquidez diaria contra gasto esencial y pagos de deuda |
| Inversión | perfil vigente, mezcla de renta variable contra la que le toca a su perfil | posiciones valuadas + la política de `bank/finance/rules.py` |

Encima de eso: **rasgos** («paga el mínimo de su tarjeta», «gasto hormiga
alto»), cada uno con el dato que lo sostiene; los **productos** que usa; una
**salud financiera** 0-100 con desglose por factor; y una frase de resumen
armada con plantilla, no redactada: *«Luis gana $22,448 al mes y gasta $15,723
en consumo (70%); a créditos, intereses y comisiones se le van $3,573…»*.

**Cada recomendación** es una regla que lee el perfil y devuelve:

- **evidencia**: las cifras que la disparan;
- **impacto** en pesos con su supuesto declarado (tasa de CETES, tasa de la
  tarjeta, recortar a la mitad);
- **prioridad** 0-100 con una fórmula auditable: urgencia (50/30/15) + 2
  puntos por cada 1% del ingreso anual que representa el impacto (tope 40) −
  15 si la herramienta aún no existe;
- la **herramienta** del catálogo que la resuelve, con sus tools, parámetros
  sugeridos y un `prompt`.

Las reglas se hablan entre sí: si hay tarjeta cara y el efectivo no alcanza
para liquidarla e invertir, «invierte tu efectivo» baja a urgencia baja y dice
«antes, liquida tu tarjeta»; si alcanza para las dos, dice cuánto usar para
cada una. Sin perfil de inversión vigente, nunca manda a una herramienta que lo
exige: manda al perfilador.

**El catálogo de herramientas** es un contrato de tres capas, como el catálogo
A2UI: qué ofrece el banco (`bank/finance/recomendaciones.py`), con qué tools se
resuelve (`services/profile.py`) y con qué componentes se pinta
(`agent/prompts.py`). `tests/test_perfil.py` falla si las tres dejan de decir
lo mismo. Hay herramientas marcadas como no disponibles —domiciliación del
pago, consolidación de deudas—: las recomendaciones que las necesitan se
muestran con «Próximamente» y penalización de prioridad, en lugar de
esconderse.

**Tablero inicial, sin LLM.** `POST /session/start` abre la sesión y el gateway
arma `bank.FinancialProfile` + `bank.Recommendations` con los mismos servicios
que usa el agente y el mismo validador A2UI. Al entrar todavía no hay pregunta
que interpretar, así que no se paga una llamada al modelo. Lo que sí se hace es
dejarle al agente, en el contexto de sesión, qué recomendaciones tiene el
cliente enfrente. Tocar una emite `follow_recommendation`, que **sí** pasa por
el agente: abrir la herramienta correcta con los datos correctos es
interpretar.

**Datos que valen la pena analizar.** Antes el seed sorteaba cargos con la misma
probabilidad para todos: un cliente de 18 mil gastaba igual que uno de 240 mil,
la renta aparecía dos meses de dieciocho y ningún crédito se pagaba nunca. Un
perfil calculado sobre eso decía «tasa de ahorro 93%». Ahora cada cliente
tiene una **persona** con hábitos (`bank/personas.py`) y
`bank/comportamiento.py` los simula por eventos: pagar el mínimo genera
intereses el mes siguiente, la tarjeta llena rechaza la compra y el cargo se va
a la cuenta, una cuenta corta paga tarde y cobra comisión. Las personas
declaran hábitos, nunca conclusiones: que Diego «paga tarde» lo **descubre** el
perfil leyendo sus estados de cuenta, y hay un test que lo verifica.

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
- **Redacción en la traza.** Los `confirmation_token` y los códigos de retiro
  sin tarjeta no salen al panel de depuración: en un demo la pantalla se proyecta.

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

**Core bancario:** 8 clientes con datos de conocimiento del cliente (edad,
ocupación, dependientes), cuentas, tarjetas de débito y crédito, y créditos con
amortización real. Sus 18 meses de movimientos y de estados de cuenta de
tarjeta no se sortean: se simulan desde los hábitos de cada persona —nómina
quincenal con aguinaldo o depósitos irregulares de negocio, renta, colegiaturas,
servicios, suscripciones, compras chicas, cómo paga la tarjeta y si barre su
excedente—, con una semilla propia por cliente. Compras con tarjeta, intereses y
comisiones viven en el mismo libro que la cuenta (`card_id`), como los ve el
cliente en la app. `bank/seed.py --check` falla si alguien queda con saldo
negativo, si una tarjeta rebasa su límite o si una persona no alcanza a pagar
sus cargos fijos. Las CLABE llevan dígito
verificador válido, y alrededor de los cargos de servicios que produce la
simulación vive el dominio de pagos (ver abajo).

**Inversiones:** 24 instrumentos contratables (CETES, bonos M, UDIBONOs,
pagarés, fondos y ETFs), repreciados sobre la curva real de septiembre 2026:
CETES 28d en 6.49%, tasa objetivo de Banxico en 6.50%. Más 120 meses de series
por instrumento con GBM correlacionado vía Cholesky, posiciones y órdenes.

**Esto es un producto de fondos, no una casa de bolsa.** No se venden acciones
sueltas y no hay trading. Pero debajo del catálogo viven **15 emisoras reales de
la BMV** (WALMEX, GFNORTEO, AMXB, GMEXICOB, CEMEXCPO, FEMSAUBD, BIMBOA, KOFUBL,
TLEVISACPO, ALFAA, ORBIA, ASURB, GAPB, PENOLES, LIVEPOLC1) como **tenencias de
los fondos**. El cliente nunca compra WALMEX; compra un fondo que la trae. Un
invariante del seed lo verifica: ninguna emisora puede aparecer como instrumento
contratable.

Cinco precios están **anclados** a una consulta con fecha; el resto de los
precios y todos los demás fundamentales son **estimados**, y cada `Emisora` lo
declara en su campo `fuente`. No es un feed en vivo: es una foto con fecha,
porque el seed tiene que ser reproducible byte a byte.

**El riesgo de una empresa no se captura, se calcula.** `bank/emisoras.py`
combina seis factores —volatilidad, beta, calificación crediticia,
apalancamiento y cobertura, bursatilidad y tamaño, y riesgo propio (`1 − R²`)—
y devuelve el desglose, no solo el número. Si alguien pregunta por qué Televisa
sale 70/100 y Walmex 17, la respuesta es una tabla con pesos y aportes.

**Y el riesgo del fondo tampoco.** `NAFTRAC` y `FND-RV-MX` no declaran su
volatilidad: sale de `sqrt(w'Σw)` sobre las empresas que traen, con la matriz de
correlación entre emisoras (modelo de índice único: beta y sector). El índice da
17.7% de volatilidad y riesgo 3; el fondo activo, más concentrado, da 20.8% y
riesgo 4. Si una emisora se deteriora, el fondo que la trae sube de riesgo solo.
El `--check` del seed falla si el riesgo guardado deja de coincidir con el
calculado.

**Look-through.** `peso efectivo = peso del fondo × peso de la empresa dentro
del fondo`. Es la única forma de contestar «¿en qué empresas está mi dinero?» en
un producto donde el cliente nunca compró una acción, y de detectar que alguien
con 60% en renta variable acabó con 10.4% de su patrimonio en un solo banco sin
elegirlo. El control de concentración de `idoneidad.py` mira ahí, no en lo que
se compró. Se reporta también `cobertura_desglose`: los fondos internacionales
no se pueden ver por dentro y se dice, en lugar de inventarles cartera.

Cuatro detalles del modelo que vale la pena defender:

- `rend_esperado_anual` es rendimiento **aritmético** esperado, así que la deriva
  logarítmica es `log1p(mu) − σ²/2`. El arrastre por volatilidad es real y no se
  esconde: la trayectoria mediana rinde menos que la media.
- La **tasa corta es estocástica** (Vasicek con reversión a la media). Sin esto,
  un CETES-28 se simula como si su tasa de hoy durara diez años y el riesgo de
  reinversión —el riesgo real de los CETES— desaparece. Cada instrumento reacciona
  con dos parámetros propios: `sens_reinversion` (cuánto se renegocia a la tasa
  vigente) y `duracion_anios` (cuánto pierde de precio si la tasa sube). Un
  CETES-28 es todo lo primero; un Bono M 10A, todo lo segundo.
- La proyección va **neta de impuestos**. La retención de intereses se cobra
  sobre el **capital**, no sobre la ganancia: se paga aunque el instrumento
  pierda. En un pagaré al 5.15% se lleva casi un quinto del rendimiento.
- Con aportaciones mensuales, `(final/aportado)^(1/años) − 1` **miente**: trata el
  dinero del mes 59 como si hubiera estado invertido cinco años. Se reporta la
  **TIR** por bisección sobre los flujos reales.

**Invariante del demo:** `CLI-0001` no tiene perfil de riesgo vigente. Es lo que
hace que el agente monte el perfilador en lugar de proponer a ciegas, y
`bank/seed.py --check` falla si alguien lo rompe.

---

## Segundo dominio: banca personal

Inversiones se cerró y se ensayó primero, a propósito — es el criterio de
corte del proyecto (ver `docs/trade-offs.md`). Banca personal es el segundo,
mismo catálogo, mismo agente, prefijo `bank.*` en vez de `inv.*`:

- **Base de datos** (`bank/schema.sql`): `accounts.alias`, `cards.alias` y
  `cards.estado` (activa/bloqueada); tabla `budgets` (un presupuesto por
  cliente y categoría); tabla `card_events`, auditoría de cada bloqueo, cambio
  de límite o alias — igual que `surface_log` audita el blueprint.
- **Servicios**: lectura ampliada en `services/accounts.py`
  (`search_transactions` con filtros combinables, `get_budgets`,
  `get_spending_alerts`); las mutaciones —que no mueven dinero, así que no
  llevan el candado de dos pasos de `place_order`— viven en
  `services/banking.py`: `block_card`/`unblock_card` (idempotentes),
  `set_card_limit` (no baja del saldo usado ni pasa de 3× el ingreso
  declarado), `set_card_alias`, `set_account_alias`, `set_budget`.
- **Seguridad**: toda mutación verifica que la cuenta/tarjeta sea del cliente
  en sesión (`_exigir_cuenta_del_cliente` / `_exigir_tarjeta_del_cliente`) y
  el mensaje de error nunca confirma ni niega que algo ajeno exista — no dice
  "esa tarjeta es de otro cliente", dice "no existe o no te pertenece". Los
  alias se recortan y tienen tope de 40 caracteres.
- **Componentes** (`bank.*`): `AccountsOverview` (cuentas y tarjetas, alias
  editable en línea), `CardManager` (bloqueo de un toque, slider de límite,
  alias), `SpendingBudgets` (presupuesto vs. gasto real con Recharts +
  slider por categoría), `TransactionSearch` (resultados filtrados con chips
  de categoría — el filtro lo decide el agente, el cliente solo lo pide).

---

## Tercer dominio: pagos

Mismo catálogo, mismo agente, prefijo `pay.*`. Es lo que un cliente hace más
seguido con su banco:

- **Pago de servicios con datos de México.** Convenios reales —CFE, Telmex
  (Infinitum), izzi, Totalplay, Megacable, Telcel, AT&T, SKY, Naturgy— y el
  organismo de agua de cada ciudad de los clientes (Agua y Drenaje de
  Monterrey, SIAPA, SACMEX, CEA Querétaro, JAPAY, Agua de Puebla, CESPT,
  SAPAL). Cada convenio valida su referencia: el número de servicio de CFE son
  12 dígitos y la telefonía se paga con el número a 10 dígitos, como en los
  recibos (`fuente_formato: publico`); el resto son longitudes plausibles y lo
  declaran (`simulado`). `register_service` valida y consulta el adeudo;
  `pay_service` paga el recibo completo —el monto lo pone el convenio, no el
  modelo— y el pago cuenta contra el presupuesto de «servicios».
- **Transferencias SPEI.** A un contacto guardado, a una CLABE nueva o entre
  cuentas propias. La CLABE se valida con el dígito verificador de Banxico
  (pesos 3-7-1) en el servidor —y como ayuda, en pantalla— y el código de banco
  tiene que ser un participante de SPEI. Si la CLABE es de otro cliente del
  mismo banco, el dinero le llega en el acto y aparece en su historial con el
  nombre de quien lo mandó.
- **Efectivo.** Retiro sin tarjeta en cajero (múltiplos de $100, hasta $9,000,
  con un código de 12 dígitos que se entrega una sola vez y en la base solo
  queda hasheado) y depósito en corresponsales (OXXO, 7-Eleven, Walmart,
  Farmacias del Ahorro, Telecomm) con referencia y comisión estimada. La CLABE
  propia sale completa, lista para compartir.
- **Historiales.** Lo que salió (`get_payment_history`: servicios,
  transferencias y retiros con folio y clave de rastreo) y lo que entró
  (`get_received_money`: nómina, honorarios, SPEI, depósitos y traspasos, con remitente y
  totales por canal; `total_recibido` no cuenta traspasos propios).

Los candados viven en `services/movements.py`:

| Candado | Qué evita |
|---|---|
| Dos pasos: `pay_service`, `transfer_money` y `withdraw_cash` solo registran; `confirm_payment` ejecuta con el token | Que el modelo mueva dinero sin que el usuario confirme en `pay.PaymentTicket` |
| El paso 2 no recibe destino ni monto: salen de lo guardado en el paso 1 | Que cambie algo entre lo que el usuario vio y lo que se ejecuta |
| Saldo y tope diario por segmento, en el paso 1 **y** otra vez al ejecutar | Que dos operaciones pendientes juntas rebasen lo permitido |
| Tope por operación a un destino nuevo, aunque se acabe de guardar (30 minutos) | El fraude «agrega esta cuenta y mándame todo» |
| `liquidar_deposito_en_efectivo` fuera de `services.REGISTRO` | Que alguna tool pueda crear saldo de la nada |
| Números enmascarados en las respuestas y `codigo_retiro` redactado en la traza | Que un número completo salga en una pantalla proyectada |

Un rechazo al ejecutar (recibo que ya se pagó, SPEI devuelto, tope rebasado)
se **persiste** antes de lanzar el error: sin eso, el rollback de la sesión lo
borraría y la operación volvería a quedar pendiente.

**Componentes** (`pay.*`): `BillsPanel` (recibos con vencimiento y botón de
pagar), `ServiceForm` (alta con el formato validado en pantalla),
`TransferForm` (contactos, CLABE nueva con verificador en vivo y cuentas
propias), `PaymentTicket` (confirmación y comprobante: folio, clave de rastreo
o código de retiro), `PaymentHistory`, `ReceivedMoney` (barras por canal) y
`CashAccess` (retiro sin tarjeta, CLABE para compartir y corresponsales).

**Datos sembrados.** Pagos no agrega movimientos: los cargos de luz, internet,
telefonía y agua ya los produce la simulación de hábitos. Alrededor de ellos,
cada cliente tiene 4 o 5 servicios con su convenio, referencia y recibo vigente
(algunos vencidos a propósito; el CFE de CLI-0001 vence en cuatro días), tres
contactos —dos de otros bancos y uno del mismo banco— y un historial de pagos
derivado de los cargos de servicios que salieron de su cuenta. Nada de eso usa
el generador aleatorio: el perfil financiero, las recomendaciones y las
inversiones quedan idénticos. Transferencias, retiros y depósitos aparecen en
los historiales cuando el cliente los hace.

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
527 tests
  a2ui/tests/test_contract.py       (122) catálogo bien formado (31 componentes, 26
                                     acciones), artefactos alineados, casos inválidos
                                     (incl. spec A2UI real: action anidado,
                                     deleteSurface), accionables y tablero inicial
  tests/test_services.py             (84) cuadre de cifras, errores con sugerencia,
                                     los dos pasos de la orden, idempotencia, token
                                     nunca expuesto, capacidad de ahorro neta de deuda
  tests/test_riesgo_emisoras.py      (68) look-through a empresas dentro de fondos,
                                     idoneidad (perfil/concentración/plazo), origen de
                                     fondos y arbitraje con crédito, fiscal, curva de
                                     tasas
  tests/test_agent_loop.py           (63) encadenado de tools (vía MCP falso),
                                     validación con reintento, fallback, bitácora,
                                     límites, token inventado en place_order y en
                                     confirm_payment
  tests/test_payments.py             (56) CLABE y Luhn, dos pasos, token ajeno o
                                     inventado, tope a destino nuevo y diario (también
                                     al ejecutar), rechazo que persiste, código de retiro
                                     de una sola vez, ninguna tool acredita dinero
  tests/test_finance.py              (41) monotonía del score, tope por horizonte,
                                     pesos que suman 1, percentiles que no se cruzan,
                                     diversificación que baja la volatilidad,
                                     comisiones que se cobran
  tests/test_perfil.py               (41) deducciones del perfil con datos armados a
                                     mano, que cada persona se DESCUBRA en sus
                                     movimientos, prioridad, planes de deuda y el
                                     contrato herramientas ↔ tools ↔ prompt
  tests/test_banking.py              (22) ownership de cuenta/tarjeta, límites con
                                     techo y piso, bloqueo idempotente, alias saneado,
                                     presupuestos
  tests/test_gateway_direct_actions.py (14) acciones deterministas (alias, bloqueo de
                                     tarjeta, límite, presupuesto) resueltas sin LLM,
                                     y el ruteo directo-vs-modelo
  tests/test_tablero.py              (12) tablero inicial válido para los 8 clientes,
                                     sin instanciar el agente, con contexto para el
                                     siguiente turno y en bitácora
  tests/test_mcp_server.py            (4) el servidor MCP real por stdio: list_tools,
                                     llamada exitosa, tool desconocida, error de
                                     servicio

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
instrumentos son inventados y las operaciones no mueven dinero. Los convenios
de pago llevan el nombre de empresas reales, pero las referencias, los adeudos
y las comisiones son simulados. Esto no es asesoría de inversión.
