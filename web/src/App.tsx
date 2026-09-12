// Cáscara de la aplicación. Tres zonas:
//   · conversación (lo que el usuario escribe y las dos frases del agente)
//   · superficie (lo que el agente monta; es la protagonista)
//   · traza (qué tools se llamaron, qué mensajes A2UI llegaron, qué se rechazó)
//
// La traza está a la vista a propósito: en un jurado técnico, mostrar el
// encadenado de tools y un blueprint rechazado-y-corregido vale más que
// cualquier animación.

import { useEffect, useRef, useState, type ReactNode } from "react";
import { Superficie } from "./renderer/Renderer";
import { manejarEvento, useStore } from "./store";
import { enviarMensaje, getModo, listarClientes, type ClienteDemo } from "./transport";
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
  "tengo 80 mil pesos parados y los podría dejar 5 años, ¿qué hago?",
  "¿en qué se me va el dinero cada mes?",
  "¿me conviene más pagar mi crédito o invertir?",
  "muéstrame los instrumentos de riesgo bajo",
];

export default function App() {
  const [texto, setTexto] = useState("");
  const [clientes, setClientes] = useState<ClienteDemo[]>([]);
  const [verTraza, setVerTraza] = useState(true);

  const estado = useStore((s) => s.estado);
  const chat = useStore((s) => s.mensajesDeChat);
  const traza = useStore((s) => s.traza);
  const error = useStore((s) => s.error);
  const ignorados = useStore((s) => s.ignorados);
  const clientId = useStore((s) => s.clientId);
  const sessionId = useStore((s) => s.sessionId);
  const setClient = useStore((s) => s.setClient);
  const agregarChat = useStore((s) => s.agregarChat);
  const setEstado = useStore((s) => s.setEstado);
  const setError = useStore((s) => s.setError);
  const reset = useStore((s) => s.reset);

  const finChat = useRef<HTMLDivElement>(null);
  const finTraza = useRef<HTMLDivElement>(null);

  useEffect(() => {
    verificarRegistry();
    void listarClientes().then(setClientes);
  }, []);

  useEffect(() => {
    finChat.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat.length]);

  useEffect(() => {
    finTraza.current?.scrollIntoView({ behavior: "smooth" });
  }, [traza.length]);

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

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-marca">
          <span className="app-punto" />
          <div>
            <strong>Banca · interfaz generativa</strong>
            <span className="app-sub">
              El agente no escribe la respuesta: la construye.
            </span>
          </div>
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
              disabled={estado === "pensando" || !!sessionId}
              onChange={(e) => setClient(e.target.value)}
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
          <button type="button" className="app-reset" onClick={reset}>
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
            {chat.length === 0 ? (
              <div className="conv-vacio">
                <p>Pregúntame algo sobre tu dinero.</p>
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
            ) : (
              chat.map((m, i) => (
                <p key={i} className={`conv-msg conv-${m.rol}`}>
                  {conNegritas(m.texto)}
                </p>
              ))
            )}
            {estado === "pensando" ? (
              <p className="conv-msg conv-agente conv-pensando">
                <span />
                <span />
                <span />
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
