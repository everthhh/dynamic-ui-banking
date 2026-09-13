# Roadmap

Qué sigue, en el orden en que se va a construir. El criterio de corte del
proyecto se mantiene aquí también (ver [`trade-offs.md`](trade-offs.md)): un
dominio se abre cuando el anterior está completo y ensayado, no en paralelo.
Cada fase describe qué falta, sobre qué base se construye y qué patrones del
código ya existente aplican directo.

| Fase | Qué agrega | Dominio A2UI | Estado |
|---|---|---|---|
| 1 | Cerrar pagos de servicios | `pay.*` (extiende) | Parcial → por completar |
| 2 | Créditos bancarios | `credito.*` (nuevo) | No iniciado |
| 3 | Seguros | `seguros.*` (nuevo) | No iniciado |
| 4 | Integración de voz | transversal | Exploración |

---

## Fase 1 · Completar pagos de servicios

`pay.*` ya cubre el pago puntual de un recibo, transferencias SPEI y acceso a
efectivo (ver [`README.md`](../README.md#tercer-dominio-pagos)) — lo que
queda parcial es todo lo que convierte un pago en algo que el cliente **no
tiene que volver a pedir**:

- **Domiciliación de recibos.** Autorizar que un convenio (CFE, Telmex, agua,
  etc.) se pague solo cada mes hasta un tope, con la posibilidad de
  cancelarlo. Necesita una tabla de domiciliaciones activas y un job que las
  liquide en la fecha de vencimiento de cada recibo simulado — el patrón ya
  existe parcialmente en `domiciliacion_pago` (`bank/finance/recomendaciones.py`),
  hoy marcada `disponible=False` y pensada solo para el pago mínimo de
  tarjeta; hay que separarla en dos herramientas (tarjeta vs. servicios) o
  generalizarla.
- **Pagos programados y recurrentes.** Agendar una transferencia o un pago de
  servicio a futuro (una sola vez o recurrente), no solo al instante. Mismo
  candado de dos pasos que hoy usa `pay_service`/`confirm_payment`, más un
  estado `programado` que un proceso batch simulado convierte en `ejecutado`
  el día indicado.
- **DiMo, CoDi y cobros con QR**, explícitamente fuera de alcance hasta ahora
  (ver trade-offs). Transferir a un número de celular o cobrar con un código
  requiere un directorio de celulares↔CLABE y un flujo de solicitud de cobro
  que la simulación todavía no modela.
- **Vencimientos que corren solos.** Hoy el reloj del banco no expira códigos
  de retiro ni referencias de depósito porque no hay proceso batch (ver
  trade-offs). Antes de domiciliar o programar pagos hace falta ese reloj
  simulado, porque ambas features dependen de que el tiempo avance sin que
  el cliente interactúe.

**Por qué va primero:** es la brecha más chica — reutiliza el candado de dos
pasos, el catálogo de convenios y los componentes `pay.*` que ya existen.

## Fase 2 · Créditos bancarios

Hoy `services/credit.py` solo expone lectura (`get_credit_overview`); todo lo
que decide o mueve algo sobre un crédito está sin construir. El propio
catálogo de herramientas ya lo anticipa con dos entradas marcadas
`disponible=False` en `bank/finance/recomendaciones.py`:

- **Recalificación y amortización.** Simular qué pasa si el cliente abona a
  capital o cambia el plazo de un crédito existente — mismo motor de
  proyección que `inv.ProjectionChart` ya usa para inversión, aplicado a una
  tabla de amortización en vez de un portafolio.
- **`refinanciamiento` (consolidación de deudas).** Juntar las deudas caras
  del cliente en un crédito de menor tasa. La regla que la dispara ya existe
  en `recomendaciones.py`; falta el servicio que calcule la oferta y el
  candado de dos pasos para contratarla.
- **`domiciliacion_pago` de tarjeta.** Pago automático del mínimo o del total
  en la fecha límite, para que un cliente como Diego (que paga tarde en el
  guion de la demo) deje de generar intereses por atraso.
- **Solicitud de crédito nuevo.** Con el motor de idoneidad y capacidad de
  ahorro ya construido en `bank/finance/`, extenderlo a "cuánto crédito
  puede pagar este cliente sin romper su carga de deuda" es una regla más,
  no un motor nuevo.

**Por qué va segundo:** el core bancario (`bank/schema.sql`) ya tiene
créditos con amortización real desde el primer dominio — no hace falta
rehacer la base, solo el servicio, las tools y los componentes
(`credito.*`), siguiendo los cuatro pasos documentados en
[`docs/arquitectura.md#escalar-a-otros-dominios`](arquitectura.md#escalar-a-otros-dominios).

## Fase 3 · Seguros

Dominio nuevo por completo — no hay tablas, servicios ni componentes hoy.
Alcance propuesto para la primera versión:

- **Catálogo de pólizas** contratables (vida, auto, hogar, gastos médicos)
  con prima, cobertura y deducible, siguiendo el mismo patrón de
  `bank/instrumentos.py` (catálogo declarado con su fuente).
- **Pólizas del cliente**, análogas a `positions` en inversión: qué tiene
  contratado, desde cuándo, con qué prima y con qué vigencia.
- **Recomendación de cobertura** ligada al perfil financiero: un cliente sin
  seguro de vida con dependientes declarados, o un colchón de liquidez que
  no alcanza para un deducible, son reglas nuevas en
  `bank/finance/recomendaciones.py` que se apoyan en datos que el perfil ya
  calcula (dependientes, colchón, ingreso).
- **Contratación y pago de prima** con el mismo candado de dos pasos y el
  mismo `confirmation_token` que ya usan `place_order` y `pay_service`.

**Por qué va tercero:** es el dominio con menos reutilización directa de
datos existentes — a diferencia de crédito, necesita un catálogo de
productos nuevo desde cero — así que conviene abrirlo con el patrón de tres
dominios ya ensayado y estable.

## Fase 4 · Integración de voz

La más lejana, y la única transversal a los tres dominios en vez de un
dominio propio. Dos objetivos distintos que conviene no confundir:

- **Accesibilidad.** Que la interfaz generativa sea operable con lector de
  pantalla y con voz para quien no puede usar mouse/touch: foco manejable,
  descripciones ARIA en cada componente del catálogo (`inv.*`, `bank.*`,
  `pay.*`, y los que agreguen las fases 2 y 3), y confirmación por voz de las
  acciones de dos pasos — sin bajar la guardia en operaciones que mueven
  dinero.
- **Asistente de voz.** Entrada por voz hacia el mismo agente (transcribir a
  texto y reusar `agent/loop.py` sin cambios) y, opcionalmente, salida por
  voz de lo que hoy es texto en el chat — la UI generativa en pantalla no
  cambia, es un canal de entrada/salida adicional al mismo ciclo
  intención → tools → UI → acción.

**Por qué va último:** depende de que el catálogo de componentes esté
estable en los tres dominios de negocio primero — diseñar accesibilidad por
voz contra una superficie que todavía va a cambiar de forma es trabajo que
se repite.

---

## Fuera de este roadmap

Educación financiera (mencionada como dominio faltante en
[`trade-offs.md`](trade-offs.md#lo-que-se-decidió-no-hacer)) no tiene fecha
todavía: a diferencia de crédito y seguros, no hay pedido explícito del
equipo que la priorice sobre las cuatro fases de arriba.
