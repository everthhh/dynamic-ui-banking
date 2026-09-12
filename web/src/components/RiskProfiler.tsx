// inv.RiskProfiler — el componente que convierte "me falta contexto" en UI.
//
// Una pregunta a la vez, con regreso. Al contestar la última manda
// `profile_done` con las cuatro respuestas en el contexto. El score NO se
// calcula aquí: lo calcula el banco.

import { useMemo, useState } from "react";
import { leerAccion } from "../a2ui";
import type { A2UIAction } from "../catalog.types";
import { useStore } from "../store";

type Opcion = { value: number; label: string };
type Pregunta = { id: string; text: string; options: Opcion[] };

export type RiskProfilerProps = {
  questions?: unknown;
  value?: unknown;
  action?: A2UIAction;
  intro?: string;
  nodoId?: string;
};

function normalizar(entrada: unknown): Pregunta[] {
  if (!Array.isArray(entrada)) return [];
  return entrada.flatMap((q) => {
    if (typeof q !== "object" || q === null) return [];
    const o = q as Record<string, unknown>;
    const opciones = Array.isArray(o.options) ? o.options : [];
    return [
      {
        id: String(o.id ?? ""),
        text: String(o.text ?? o.texto ?? ""),
        options: opciones.flatMap((op) =>
          typeof op === "object" && op !== null
            ? [
                {
                  value: Number((op as Record<string, unknown>).value),
                  label: String((op as Record<string, unknown>).label ?? ""),
                },
              ]
            : [],
        ),
      },
    ];
  });
}

export function RiskProfiler({ nodoId, questions, value, action, intro }: RiskProfilerProps) {
  const preguntas = useMemo(() => normalizar(questions), [questions]);
  const iniciales = (typeof value === "object" && value !== null
    ? (value as Record<string, number>)
    : {}) as Record<string, number>;

  const [respuestas, setRespuestas] = useState<Record<string, number>>(iniciales);
  const [indice, setIndice] = useState(0);
  const [enviado, setEnviado] = useState(false);
  const emitir = useStore((s) => s.emitirAccion);
  const pensando = useStore((s) => s.estado === "pensando");

  if (!preguntas.length) {
    return <div className="rndr-hueco">El perfilador llegó sin preguntas.</div>;
  }

  const pregunta = preguntas[Math.min(indice, preguntas.length - 1)]!;
  const total = preguntas.length;
  const contestadas = preguntas.filter((q) => respuestas[q.id] !== undefined).length;

  function elegir(valor: number) {
    const siguientes = { ...respuestas, [pregunta.id]: valor };
    setRespuestas(siguientes);

    const faltan = preguntas.filter((q) => siguientes[q.id] === undefined);
    if (faltan.length === 0) {
      setEnviado(true);
      const answers = preguntas.map((q) => ({ id: q.id, value: siguientes[q.id]! }));
      const accion = leerAccion(action);
      if (accion) void emitir(accion.name, { ...accion.context, answers }, nodoId);
      return;
    }
    const siguienteIdx = preguntas.findIndex((q) => siguientes[q.id] === undefined);
    setIndice(siguienteIdx === -1 ? indice : siguienteIdx);
  }

  return (
    <section className="rp" aria-label="Perfil de riesgo">
      {intro ? <p className="rp-intro">{intro}</p> : null}

      <div className="rp-progreso" role="progressbar" aria-valuenow={contestadas} aria-valuemax={total}>
        {preguntas.map((q, i) => (
          <span
            key={q.id}
            className={
              "rp-paso" +
              (respuestas[q.id] !== undefined ? " hecho" : "") +
              (i === indice && !enviado ? " activo" : "")
            }
          />
        ))}
        <span className="rp-contador">
          {Math.min(contestadas + (enviado ? 0 : 1), total)} de {total}
        </span>
      </div>

      {enviado ? (
        <p className="rp-gracias">
          {pensando ? "Calculando tu perfil…" : "Listo, ya tengo tus cuatro respuestas."}
        </p>
      ) : (
        <>
          <h4 className="rp-pregunta">{pregunta.text}</h4>
          <div className="rp-opciones">
            {pregunta.options.map((op) => (
              <button
                key={op.value}
                type="button"
                className={
                  "rp-opcion" + (respuestas[pregunta.id] === op.value ? " elegida" : "")
                }
                onClick={() => elegir(op.value)}
                disabled={pensando}
              >
                {op.label}
              </button>
            ))}
          </div>
          {indice > 0 ? (
            <button type="button" className="rp-atras" onClick={() => setIndice(indice - 1)}>
              ← Regresar
            </button>
          ) : null}
        </>
      )}
    </section>
  );
}
