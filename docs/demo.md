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

## Los seis momentos

| # | Qué haces | Qué decir mientras carga | Qué se ve |
|---|---|---|---|
| 1 | Escribes «tengo 80 mil pesos parados y los podría dejar 5 años, ¿qué hago?» | «Le falta contexto: no tengo su perfil. En vez de preguntárselo en texto, **construye** la pregunta.» | `createSurface` + perfilador de 4 preguntas |
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
  `updateComponents` de los otros turnos.

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

## Preguntas que van a hacer

**«¿El modelo inventa los números?»**
No. El system prompt lo prohíbe y el motor está en `bank/finance/`; toda cifra en
pantalla viene de un `tool_result`. Además el Monte Carlo es determinista: la
semilla se deriva de los argumentos, así que mover un slider y regresarlo da
exactamente lo mismo.

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
