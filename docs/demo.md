# Guion de la demo · 3 minutos

Cliente: **CLI-0001, Ana Sofía Reyes**. No tiene perfil de riesgo vigente, y eso
es el motor de todo lo que sigue.

## Antes de empezar

```bash
make seed && make catalog && make fixtures && make check
make api          # terminal 1
make web          # terminal 2
```

Abre `http://localhost:5173`. Deja una pestaña con `?mock=1` cargada por si
acaso (plan B más abajo).

**Primera frase, antes de tocar nada:** «Todos los datos son sintéticos y no hay
asesoría real. Lo que sí es real es el ciclo.»

---

## Los siete momentos

| # | Qué haces | Qué decir mientras carga | Qué se ve |
|---|---|---|---|
| 0 | Nada: abres la app | «Antes de que escriba, el banco ya leyó 12 meses de su historia: movimientos, estados de cuenta de la tarjeta, créditos. Esto no lo escribió el modelo; lo **calculó** el banco, y no hubo una sola llamada a la API.» | Tablero: salud financiera, a dónde se va el ingreso, rasgos y recomendaciones con evidencia e impacto en pesos |
| 1 | En la primera recomendación («Tienes … sin invertir») presionas **Empezar** —o escribes «tengo 80 mil pesos parados y los podría dejar 5 años, ¿qué hago?»— | «Le falta contexto: no tengo su perfil. En vez de preguntárselo en texto, **construye** la pregunta.» | `createSurface` + perfilador de 4 preguntas |
| 2 | Contestas las cuatro | «El score no lo inventa el modelo, se lo pide al banco. Y con eso arma la propuesta.» | La superficie se reescribe: métricas, dona, proyección p10/p50/p90, sliders |
| 3 | Subes la aportación mensual a $2,500 | «Fíjense que **no parpadeó**. Un solo `updateDataModel`: los componentes ya estaban montados.» | La gráfica se recalcula en el lugar |
| 4 | Presionas «¿Y si fuera más conservador?» | «Nadie programó una pantalla de comparación. El agente decidió que esa pregunta se responde con dos columnas.» | `inv.ComparePanel` con las mismas métricas |
| 5 | Presionas «Me quedo con mi perfil y quiero invertir» | «Aquí sí se mueve dinero. Dos pasos: esta llamada **no ejecutó nada**, solo registró y me dio un token.» | `inv.OrderTicket` con el botón deshabilitado |
| 6 | Marcas la casilla y confirmas | «Folio real, saldo movido, y la superficie ya no es una propuesta: es un estado de cuenta.» | Superficie nueva con las posiciones |

**Tiempo objetivo:** 20 s el encuadre, 2:20 el recorrido, 20 s el cierre.

---

## Lo que hay que señalar en el panel de traza

Está abajo a propósito. Vale más que cualquier animación frente a un jurado
técnico:

- el **encadenado de tools** en el turno 2: `score_risk_profile` →
  `get_spending_summary` → `propose_allocation` → `simulate_portfolio`;
- `tool (mueve dinero)` en rojo en los turnos 5 y 6;
- en el turno 3, **un solo** `updateDataModel` frente a los
  `updateComponents` de los otros turnos;
- en el momento 0, `tool directa (sin LLM)`: el tablero entero salió de los
  servicios, sin tokens.

**Si hay tiempo, cambia de cliente.** Con Luis (CLI-0003) o Diego (CLI-0005) el
tablero cambia solo: la primera recomendación deja de ser invertir y pasa a ser
su tarjeta, porque sus estados de cuenta dicen que pagan el mínimo o tarde. Nadie
programó esa diferencia por cliente.

Si en algún turno aparece `blueprint rechazado`, **no lo escondas**: es el mejor
momento de la demo. «El modelo se equivocó, el validador le devolvió el error
diciéndole exactamente qué prop estaba mal, y se corrigió solo en la siguiente
vuelta.»

---

## Cierre (20 segundos)

> Tres superficies distintas salieron de la misma conversación, y ninguna estaba
> programada como pantalla. El catálogo es la fuente única de verdad: de ahí
> salen el prompt, el validador y los tipos del front, y hay un test que falla si
> se desalinean. El modelo decide **qué** mostrar; los números los pone el banco.

---

## Plan B

| Si falla… | Haces |
|---|---|
| La API de Anthropic | Cambias a la pestaña con `?mock=1`. Es el mismo guion con los mismos números, grabado desde los servicios reales. Lo dices: «voy al guion grabado, son los mismos datos». |
| El gateway | Igual: `?mock=1` no toca el backend. |
| Todo | Video de respaldo grabado con `?mock=1` a 1440×980. |

No intentes depurar en vivo. Cambias de pestaña y sigues hablando.

---

## Guion alterno: pagos (1 minuto)

Mismo cliente, **CLI-0001**. Su recibo de CFE vence en cuatro días: es lo que
hace que el panel tenga algo urgente que mostrar.

| # | Qué haces | Qué decir mientras carga | Qué se ve |
|---|---|---|---|
| 1 | Escribes «¿qué recibos tengo por pagar?» | «No es una lista en texto: cada recibo trae su fecha límite y su botón.» | `pay.BillsPanel` con CFE, agua, Telmex, Telcel y Naturgy |
| 2 | Presionas «Pagar» en CFE | «Ese botón no pagó nada. Registró el pago y me dio un token: el dinero sale hasta que confirmas.» | `pay.PaymentTicket` por confirmar |
| 3 | Marcas la casilla y confirmas | «El monto lo puso el convenio, no el modelo. Folio real, y el mismo ticket ya es el comprobante.» | Ticket en verde con folio; el recibo desaparece del panel |
| 4 | Escribes «necesito sacar mil pesos y no traigo tarjeta» | «Otra vez dos pasos. El código se genera al confirmar, se muestra una vez, y en la base solo queda su hash.» | `pay.CashAccess` → ticket → código de 12 dígitos |

Para mostrar un depósito en efectivo: pide «quiero depositar en OXXO», copia la
referencia y, en otra terminal, `make deposito REF=<referencia> MONTO=2000`.
Luego «¿ya llegó mi depósito?» → `pay.ReceivedMoney`. Si preguntan por qué hace
falta un comando: **ninguna tool puede acreditar dinero**; eso lo hace la tienda.

---

## Preguntas que van a hacer

**«¿El modelo inventa los números?»**
No. El system prompt lo prohíbe y el motor está en `bank/finance/`; toda cifra en
pantalla viene de un `tool_result`. Además el Monte Carlo es determinista: la
semilla se deriva de los argumentos, así que mover un slider y regresarlo da
exactamente lo mismo.

**«¿De dónde salen las recomendaciones? ¿Las decide el modelo?»**
No. Salen de reglas sobre un perfil que el banco calcula con 12 meses de datos
(`bank/finance/perfil.py`). Cada una trae la evidencia que la dispara, su impacto
en pesos con el supuesto declarado y una prioridad con fórmula: urgencia más el
impacto frente al ingreso. El modelo las puede explicar, pero no las reordena ni
inventa otras.

**«¿Cómo sabe que paga el mínimo?»**
Lo lee de sus estados de cuenta: en cuántos cortes pagó completo, cuántos pagó
cerca del mínimo y cuántos tarde. Los clientes sintéticos declaran hábitos, no
etiquetas; el perfil tiene que descubrirlos y un test verifica que lo haga.

**«¿Qué pasa si el modelo inventa un componente?»**
Tres cosas, en orden: el validador lo rechaza y le devuelve el error con los
componentes válidos; si insiste dos veces, se monta una plantilla estática; y
aunque algo se colara, el renderer tiene su propia allowlist y no lo monta. A2UI
son datos, no código.

**«¿Puede ejecutar una orden por su cuenta?»**
No. `place_order` requiere un `confirmation_token` que solo existe en la
respuesta del paso 1, y el paso 1 no mueve nada. Hay un test que prueba que un
token inventado se rechaza.

**«¿Por qué no LangChain?»**
Porque hay que interceptar `render_surface` entre el modelo y el cliente para
validarlo contra el catálogo y devolver el error. Un framework que resuelve el
loop por ti no deja meter ese paso. El loop propio son 300 líneas.

**«¿Cuánto cuesta un turno?»**
El system prompt con el catálogo va cacheado con un solo punto de corte, y el
contexto de sesión se manda después para no invalidar el prefijo. El gateway
reporta el uso en `GET /api/sessions/{id}`.

**«¿Cómo lo llevan a otro dominio?»**
Un catálogo y un servidor de servicios por dominio, con un router de intención
al frente que carga solo el catálogo relevante. El esquema ya trae tarjetas,
créditos y categorización de gasto para no rehacer la base.
