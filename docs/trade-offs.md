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
| **Riesgo de emisora calculado, no capturado** | `riesgo_1a5` escrito a mano por acción, como el resto del catálogo | Con 15 empresas, un número tecleado no se puede defender ante la pregunta «¿por qué esta es 5 y esta 3?». `bank/emisoras.py` lo deriva de seis factores (volatilidad, beta, calificación, apalancamiento, bursatilidad y riesgo propio) y devuelve el desglose | Hay que mantener los fundamentales al día; el `--check` del seed avisa si el riesgo guardado ya no coincide con el calculado |
| **Precios anclados a una foto con fecha** | Feed de mercado en vivo | El seed tiene que ser reproducible byte a byte: con precios en vivo, `make seed` da resultados distintos cada corrida y los tests dejan de significar algo | Los precios envejecen. Cada `Emisora` trae `fuente` (`anclado`/`estimado`) y el `--check` falla si la foto pasa de 90 días |
| **CAPM para el rendimiento esperado de acciones** | Rendimiento por emisora escrito a mano | Hace explícito lo que importa: el mercado paga por beta, no por riesgo propio. Por eso TLEVISA sale con la volatilidad más alta del catálogo y un rendimiento esperado mediocre — que es el argumento contra concentrarse en ella | CAPM es un modelo discutible; se declara como supuesto en `bank/mercado.py` con su prima de riesgo |
| **Modelo de índice único para correlacionar emisoras** | Correlación promedio por clase de activo | Con la matriz de clases, CEMEX y WALMEX salían al 0.94 por ser las dos «renta variable». Con beta y sector salen al 0.35, y de ahí sale la volatilidad de los fondos que las traen | Una matriz más que mantener; se calcula, no se captura |
| **Emisoras como tenencias, no como instrumentos** | Vender las 15 acciones directo en el catálogo | Es un producto de fondos, no una casa de bolsa. Las empresas entran por debajo (`bank/carteras.py`) y el cliente llega a ellas vía los fondos. Un invariante del seed verifica que ninguna emisora sea contratable | La exposición a una empresa concreta solo se ajusta cambiando de fondo |
| **Riesgo del fondo derivado de su cartera** | `riesgo_1a5` y volatilidad tecleados por fondo | No pueden existir dos verdades. `NAFTRAC` decía 0.155 porque alguien lo escribió; ahora dice 0.177 porque es lo que da `sqrt(w'Σw)` sobre sus tenencias. Si una emisora se deteriora, el fondo sube de riesgo solo | Solo aplica a los fondos con desglose; los internacionales siguen con cifras declaradas |
| **Concentración medida por look-through** | Tope sobre lo que el cliente compró | «Diversificado» no es «tiene varios fondos». Con 60% en renta variable un cliente puede acabar con 10.4% en un solo banco sin haberlo elegido, y sin mirar dentro de los fondos nadie se entera | Hay que mantener la composición de los fondos, y los internacionales no se pueden mirar: se reporta `cobertura_desglose` en vez de fingir transparencia |
| **Idoneidad como control ejecutable** | Guardarraíles en el prompt | Un guardarraíl que vive en el prompt es una sugerencia. `place_order` verifica contra el perfil **guardado** y rechaza; el modelo no puede desactivarlo | Hay reglas duras que a veces estorban en el demo (un conservador no recibe acciones, punto) |
| **Verificar idoneidad dos veces en `place_order`** | Solo al registrar | Entre el paso 1 y el paso 2 pasan minutos: el perfil pudo vencer o alguien pudo reperfilar al cliente | Una consulta más por ejecución |
| **Origen de fondos en la fórmula** | Tratar todo el dinero igual | No es lo mismo invertir un excedente que invertir con una tarjeta al 42%. Con deuda, la referencia para «no perder» es lo que vas a deber, y el perfil aplicable baja a conservador | Un parámetro más que arrastrar por toda la cadena |
| **Bloquear crédito por condición de arbitraje** | Tope fijo de riesgo con crédito | Es una regla defendible con número: si el rendimiento esperado no supera el costo del financiamiento, el valor esperado es negativo. Con el catálogo actual eso bloquea casi todo crédito, y ese es el resultado correcto | Un usuario decidido a apalancarse no puede hacerlo desde aquí |
| **Tasa corta estocástica (Vasicek)** | Tasa constante | Sin esto, un CETES-28 se simula como si su tasa de hoy durara diez años, y el riesgo de reinversión —el riesgo *real* de los CETES— desaparece. Cada instrumento reacciona con dos parámetros propios: `sens_reinversion` y `duracion_anios` | Un proceso más que calibrar (`TASA_LARGA`, κ, σ), todos declarados en `bank/mercado.py` |
| **Impuestos dentro de la proyección** | Proyección bruta | El número bruto es el que el cliente nunca va a recibir. La retención de intereses se cobra sobre el **capital**, así que se paga aunque el instrumento pierda: en un pagaré al 5.15% se lleva casi un quinto del rendimiento | El modelo fiscal es una simplificación (sin compensación de pérdidas, sin regímenes especiales); está declarado en `bank/finance/fiscal.py` |
| **Tres probabilidades de perder, no una** | Solo `prob_perdida_nominal` | «Probabilidad de perder» sin decir contra qué es medio dato. Nominal, real (contra inflación) y contra el origen del dinero dan respuestas muy distintas, y con crédito solo la tercera es honesta | Más columnas que explicar en la UI |
| **Claude Sonnet** | Opus para todo | La latencia es parte de la experiencia: una UI que tarda ocho segundos en aparecer no se siente generativa | Se compensa con few-shots y prompt caching |
| **Mutaciones de banca personal sin candado de dos pasos** (`block_card`, `set_card_limit`, `set_account_alias`, `set_budget`) | El mismo patrón de `place_order` (token + segunda llamada) | Ninguna mueve dinero real; bloquear una tarjeta es la acción de urgencia y debe costar un toque, no dos. El límite y el presupuesto sí llevan techo/piso de negocio explícito en el servidor | Confiar en la validación server-side (ownership + rangos) en vez de una confirmación en pantalla |
| **`card_events`: tabla de auditoría propia** | Confiar en los logs del proceso | Cada bloqueo, cambio de límite o alias queda en la base, no solo en un log que se pierde al reiniciar — es lo que permite reconstruir "quién cambió qué" sin la sesión activa | Una tabla e inserts extra en cada mutación |
| **Mensajes de ownership genéricos** ("no existe o no te pertenece") | Decir explícitamente "esa tarjeta es de otro cliente" | Un mensaje específico confirma que el id existe, solo que es ajeno — información que un cliente no debería poder extraer probando ids | El modelo recibe una pista un poco menos rica para autocorregirse, pero el error ya es inequívoco sobre qué hacer (pedir `get_accounts` de nuevo) |
| **Pagos: el paso 2 es una tool aparte** (`confirm_payment(payment_id, token)`) | Repetir todos los argumentos en la segunda llamada, como `place_order` | Destino y monto quedan guardados en el paso 1: el modelo no puede cambiar nada entre lo que el usuario revisó y lo que se ejecuta, y no hay argumentos que desalinear entre las dos llamadas | Una tool más en el catálogo del modelo |
| **Ninguna tool acredita dinero** (`liquidar_deposito_en_efectivo` fuera de `REGISTRO`) | Una tool `deposit_cash` | Un depósito en efectivo es dinero que llega de fuera. Si el modelo lo pudiera pedir, podría crear saldo de la nada. La liquidación la dispara el corresponsal; en el demo, `make deposito` | El ciclo del depósito no se cierra solo: hay que correr un comando fuera de la conversación |
| **Tope por operación a destinos nuevos, también a los recién guardados** | Solo tope diario | «Agrega esta cuenta y mándame todo» es el fraude más común. Guardar el contacto no salta el tope: cuenta como nuevo durante 30 minutos | Una transferencia grande a alguien nuevo exige dos momentos |
| **Revisar saldo y tope otra vez al ejecutar, y persistir el rechazo** | Revisar solo en el paso 1 | Dos operaciones pendientes pasan el paso 1 por separado y juntas rebasan el tope. El rechazo se guarda con `commit` antes de lanzar el error: si no, el rollback de la sesión lo borra y la operación vuelve a quedar pendiente | Una consulta más por ejecución |
| **Dígito verificador de CLABE en el servidor y en pantalla** | Validar solo que sean 18 dígitos | Un dígito mal tecleado es el error más probable y el más caro. En pantalla es ayuda (el usuario ve el banco mientras teclea); el candado es el del servidor | La lista de bancos SPEI existe dos veces: `bank/pagos.py` y un espejo marcado como tal en `web/src/format.ts` |
| **Formatos de referencia marcados `publico` o `simulado`** | Presentar todos los formatos como reales | CFE (12 dígitos) y telefonía (número a 10 dígitos) salen de los recibos; para los demás no hay fuente pública confiable y se declara, igual que los precios `anclado`/`estimado` de las emisoras | Un formato simulado puede no coincidir con el recibo real de ese convenio |
| **Pagos del seed con semilla aparte, reemplazando los cargos genéricos de «servicios»** | Agregar pagos encima con la misma `rng` | Encima habría contado dos veces el gasto en servicios; con la misma `rng` se habrían movido todas las posiciones y órdenes del demo. Con `rng_pagos` las tablas de inversiones quedan idénticas | El seed tiene dos generadores y hay que saber cuál usar |
| **Números enmascarados en las respuestas** (`•••• 1234`) | Devolver CLABEs y referencias completas | La pantalla se proyecta y el modelo no necesita el número para operar: usa `service_id` y `beneficiary_id`. La única CLABE completa es la propia, que es la que se comparte | Para ver un número completo hay que ir a la base |

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

**Los 3 dominios que faltan** (Crédito más allá de `get_credit_overview`,
Seguros, Educación financiera). El criterio de corte se respeta a propósito:
Inversiones se cerró y se ensayó, luego Banca personal, y Pagos se abrió como
tercero a pedido del equipo. Media demo de cinco dominios es peor que tres
completos.

**En pagos: DiMo, CoDi y cobros con QR.** Transferir a un número de celular o
cobrar con un código QR necesita un directorio de celulares y un flujo de
solicitud de pago que la simulación no tiene. Se transfiere a CLABE, a una
tarjeta guardada o entre cuentas propias.

**En pagos: vencimientos que corren solos.** El reloj del banco simulado es la
fecha de valuación más la hora real, así que durante un demo un código de
retiro o una referencia de depósito no llegan a vencer, y no hay proceso batch
que los expire. Cancelar un retiro sí reembolsa; en la simulación ningún cajero
cobra el código, así que cancelar siempre devuelve el dinero.

## Lo que el modelo financiero sigue sin capturar

Se dice de frente porque todas estas omisiones empujan en la misma dirección:
**subestiman la pérdida**.

- **Colas delgadas.** Los retornos son lognormales. No hay crashes.
- **Correlaciones fijas.** No hay régimen de crisis donde todo se va a 1 justo
  cuando importa. Es la simplificación más cara de la lista.
- **Sin default como evento discreto.** El riesgo de crédito está disuelto en la
  volatilidad y en la calificación, no modelado como impago.
- **Sin costo de transacción ni spread.** El rebalanceo mensual es gratis y
  perfecto.
- **Sin backtest.** Nada valida que una prima de riesgo de 5.5% para México sea
  la correcta; es un supuesto declarado, no un resultado medido.
- **Fundamentales estimados.** Los precios de cinco emisoras están anclados a una
  consulta con fecha; el resto de los precios y **todos** los demás
  fundamentales (beta, apalancamiento, calificación, bursatilidad) son
  estimaciones calibradas a un rango plausible. No es un feed de mercado.
- **Carteras estáticas.** La composición de los fondos no rota: un fondo activo
  real cambia posiciones cada trimestre. El look-through es una foto, igual que
  los precios.
- **Solo dos fondos tienen desglose.** Los internacionales y sectoriales globales
  no traen composición porque su subyacente no son emisoras de la BMV, y se
  declara (`cobertura_desglose`) en lugar de inventarles una cartera.

## El riesgo número uno

Pulir componentes antes de que el ciclo cierre. La UI bonita es el 10 % de la
rúbrica; que **cambie y sirva** es el 45 %. Por eso el hito de la hora 12 era
«intención → UI → acción → UI nueva», feo pero completo, y por eso `make smoke`
existe: contesta en diez segundos si el ciclo sigue cerrando.
