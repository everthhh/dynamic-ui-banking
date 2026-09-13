// Cáscara de la aplicación. Tres zonas:
//   · conversación (lo que el usuario escribe y las dos frases del agente)
//   · superficie (lo que el agente monta; es la protagonista)
//   · traza (qué tools se llamaron, qué mensajes A2UI llegaron, qué se rechazó)
//
// Al entrar —y al cambiar de cliente o empezar de nuevo— se abre una sesión y
// el gateway pinta el tablero inicial: perfil financiero y recomendaciones,
// sin llamar al LLM. La conversación arranca con eso ya en pantalla.
//
// La traza está a la vista a propósito: en un jurado técnico, mostrar el
// encadenado de tools y un blueprint rechazado-y-corregido vale más que
// cualquier animación.

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Logo } from "./components/Logo";
import { copiaAmigable } from "./progressCopy";
import { Superficie } from "./renderer/Renderer";
import { SURFACE_TABLERO, manejarEvento, useStore } from "./store";
import {
  enviarMensaje,
  getModo,
  iniciarSesion,
  listarClientes,
  type ClienteDemo,
} from "./transport";
import { verificarRegistry } from "./registry.check";

/** Markdown mínimo: solo `**negritas**`.
 *
 * El modelo escribe en markdown por costumbre y dejar los asteriscos crudos en
 * pantalla se ve descuidado. Se resuelven aquí las negritas y nada más: el
 * mensaje del agente son una o dos frases, no un documento. */
function conNegritas(texto: string): ReactNode[] {
  return texto.split(/(\*\*[^*]+\*\*)/g).map((trozo, i) =>
    trozo.startsWith("**") && trozo.endsWith("**") && trozo.length > 4 ? (
      <strong key={i}>{trozo.slice(2, -2)}</strong>
    ) : (
      <span key={i}>{trozo}</span>
    ),
  );
}

const SUGERENCIAS = [
  "¿cómo están mis finanzas?",
  "tengo 80 mil pesos parados y los podría dejar 5 años, ¿qué hago?",
  "¿en qué se me va el dinero cada mes?",
  "¿me conviene más pagar mi tarjeta o invertir?",
];

export default function App() {
  const [texto, setTexto] = useState("");
  const [clientes, setClientes] = useState<ClienteDemo[]>([]);
  const [verTraza, setVerTraza] = useState(true);
  const [aperturas, setAperturas] = useState(0);

  const estado = useStore((s) => s.estado);
  const chat = useStore((s) => s.mensajesDeChat);
  const traza = useStore((s) => s.traza);
  const error = useStore((s) => s.error);
  const ignorados = useStore((s) => s.ignorados);
  const clientId = useStore((s) => s.clientId);
  const sessionId = useStore((s) => s.sessionId);
  const superficieActiva = useStore((s) => s.superficieActiva);
  const hayTablero = useStore((s) => SURFACE_TABLERO in s.superficies);
  const setClient = useStore((s) => s.setClient);
  const agregarChat = useStore((s) => s.agregarChat);
  const setEstado = useStore((s) => s.setEstado);
  const setError = useStore((s) => s.setError);
  const reset = useStore((s) => s.reset);
  const activarSuperficie = useStore((s) => s.activarSuperficie);

  const finChat = useRef<HTMLDivElement>(null);
  const finTraza = useRef<HTMLDivElement>(null);
  const tableroPedido = useRef<string | null>(null);
  const [copiaProgreso, setCopiaProgreso] = useState<string | null>(null);

  useEffect(() => {
    const copia = copiaAmigable(traza[traza.length - 1]);
    if (copia !== undefined) setCopiaProgreso(copia);
  }, [traza]);

  useEffect(() => {
    verificarRegistry();
    void listarClientes().then(setClientes);
  }, []);

  useEffect(() => {
    // StrictMode monta los efectos dos veces en desarrollo: sin esta guarda
    // se abrirían dos sesiones por cada carga.
    const clave = `${clientId}#${aperturas}`;
    if (tableroPedido.current === clave) return;
    tableroPedido.current = clave;
    void abrirTablero(clientId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [clientId, aperturas]);

  useEffect(() => {
    finChat.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat.length]);

  useEffect(() => {
    finTraza.current?.scrollIntoView({ behavior: "smooth" });
  }, [traza.length]);

  async function abrirTablero(cliente: string) {
    setEstado("pensando");
    setError(null);
    try {
      await iniciarSesion({ client_id: cliente }, manejarEvento);
      setEstado("inactivo");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  function empezarDeNuevo() {
    reset();
    setAperturas((n) => n + 1);
  }

  function cambiarCliente(id: string) {
    reset();
    setClient(id);
  }

  async function enviar(mensaje: string) {
    const limpio = mensaje.trim();
    if (!limpio || estado === "pensando") return;
    setTexto("");
    agregarChat("usuario", limpio);
    setEstado("pensando");
    setError(null);
    try {
      await enviarMensaje({ message: limpio, session_id: sessionId, client_id: clientId },
                          manejarEvento);
      setEstado("inactivo");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const modo = getModo();
  const yaPregunto = chat.some((m) => m.rol === "usuario");

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-marca">
          <Logo />
          <span className="app-sub">
            El agente no escribe la respuesta: la construye.
          </span>
        </div>

        <div className="app-controles">
          {modo === "simulado" ? (
            <span className="app-modo" title="Guion grabado con datos reales de services/">
              guion simulado
            </span>
          ) : null}
          <label className="app-cliente">
            <span>Cliente</span>
            <select
              value={clientId}
              disabled={estado === "pensando"}
              onChange={(e) => cambiarCliente(e.target.value)}
            >
              {clientes.length === 0 ? <option value={clientId}>{clientId}</option> : null}
              {clientes.map((c) => (
                <option key={c.client_id} value={c.client_id}>
                  {c.nombre} · {c.segmento}
                  {c.perfil_vigente ? "" : " · sin perfil"}
                </option>
              ))}
            </select>
          </label>
          {hayTablero && superficieActiva !== SURFACE_TABLERO ? (
            <button
              type="button"
              className="app-reset"
              onClick={() => activarSuperficie(SURFACE_TABLERO)}
            >
              Mi resumen
            </button>
          ) : null}
          <button type="button" className="app-reset" onClick={empezarDeNuevo}>
            Empezar de nuevo
          </button>
        </div>
      </header>

      {error ? (
        <div className="app-error" role="alert">
          {error}
        </div>
      ) : null}

      {ignorados.length ? (
        <div className="app-aviso" role="status">
          Ignoré {ignorados.length} componente(s) fuera del catálogo:{" "}
          <code>{[...new Set(ignorados)].join(", ")}</code>. A2UI son datos, no código.
        </div>
      ) : null}

      <main className="app-cuerpo">
        <section className="app-conversacion">
          <div className="conv-mensajes">
            {chat.map((m, i) => (
              <p key={i} className={`conv-msg conv-${m.rol}`}>
                {conNegritas(m.texto)}
              </p>
            ))}
            {!yaPregunto && estado !== "pensando" ? (
              <div className="conv-vacio">
                <p>{chat.length ? "O pregúntame lo que quieras:" : "Pregúntame algo sobre tu dinero."}</p>
                <ul>
                  {SUGERENCIAS.map((s) => (
                    <li key={s}>
                      <button type="button" onClick={() => void enviar(s)}>
                        {s}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {estado === "pensando" ? (
              <p className="conv-msg conv-agente conv-pensando">
                <span className="conv-pensando-puntos">
                  <span />
                  <span />
                  <span />
                </span>
                {copiaProgreso ? (
                  <span key={copiaProgreso} className="conv-pensando-texto">
                    {copiaProgreso}
                  </span>
                ) : null}
              </p>
            ) : null}
            <div ref={finChat} />
          </div>

          <form
            className="conv-entrada"
            onSubmit={(e) => {
              e.preventDefault();
              void enviar(texto);
            }}
          >
            <input
              value={texto}
              onChange={(e) => setTexto(e.target.value)}
              placeholder="Escribe aquí…"
              disabled={estado === "pensando"}
              aria-label="Mensaje"
            />
            <button type="submit" disabled={estado === "pensando" || !texto.trim()}>
              Enviar
            </button>
          </form>
        </section>

        <section className="app-superficie">
          <Superficie />
        </section>
      </main>

      <aside className={"app-traza" + (verTraza ? " abierta" : "")}>
        <button type="button" className="traza-toggle" onClick={() => setVerTraza((v) => !v)}>
          {verTraza ? "▾" : "▸"} Qué está pasando ({traza.length})
        </button>
        {verTraza ? (
          <ol className="traza-lista">
            {traza.map((t, i) => (
              <li key={i} className={`traza-${t.tipo.replace(/[^a-z]/gi, "-")}`}>
                <code>{t.tipo}</code>
                <span>{t.detalle}</span>
              </li>
            ))}
            <div ref={finTraza} />
          </ol>
        ) : null}
      </aside>
    </div>
  );
}
