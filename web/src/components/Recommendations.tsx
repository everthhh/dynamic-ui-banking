// bank.Recommendations — lo que el banco le recomienda a este cliente.
//
// El orden, las cifras y la herramienta vienen de `get_recommendations`
// (bank/finance/recomendaciones.py). Tocar una manda `follow_recommendation`
// con su prompt y su herramienta, y el agente arma la pantalla de esa
// herramienta. "Ver más" es estado local de la vista: no cambia qué se
// recomienda ni en qué orden.

import { useState } from "react";
import { moneda, porFormato } from "../format";
import { useStore } from "../store";

type Obj = Record<string, unknown>;

const obj = (v: unknown): Obj =>
  typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Obj) : {};
const lista = (v: unknown): Obj[] =>
  Array.isArray(v) ? (v as unknown[]).filter((x): x is Obj => typeof x === "object" && x !== null) : [];

export type RecommendationsProps = {
  recomendaciones?: unknown;
  titulo?: string;
  max?: number;
  nodoId?: string;
};

const URGENCIA: Record<string, { etiqueta: string; tono: string }> = {
  alta: { etiqueta: "Urgente", tono: "danger" },
  media: { etiqueta: "Importante", tono: "warning" },
  baja: { etiqueta: "Oportunidad", tono: "info" },
};

const PERIODO: Record<string, string> = { anual: "al año", mensual: "al mes" };

function Recomendacion({ r, nodoId }: { r: Obj; nodoId?: string }) {
  const emitir = useStore((s) => s.emitirAccion);
  const pensando = useStore((s) => s.estado === "pensando");
  const urgencia = URGENCIA[String(r.urgencia)] ?? { etiqueta: "Sugerencia", tono: "info" };
  const impacto = obj(r.impacto);
  const herramienta = obj(r.herramienta);
  const disponible = herramienta.disponible !== false;
  const periodo = PERIODO[String(impacto.periodo)];

  return (
    <li className={`rc-item rc-${urgencia.tono}`}>
      <div className="rc-cabeza">
        <span className={`c-badge c-badge-${urgencia.tono}`}>{urgencia.etiqueta}</span>
        <span className="rc-prioridad" title="Urgencia más impacto frente a tu ingreso">
          Prioridad {Number(r.prioridad ?? 0)}/100
        </span>
      </div>

      <h4 className="rc-item-titulo">{String(r.titulo ?? "")}</h4>
      <p className="rc-desc">{String(r.descripcion ?? "")}</p>

      {lista(r.evidencia).length ? (
        <dl className="rc-evidencia">
          {lista(r.evidencia)
            .slice(0, 4)
            .map((e) => (
              <div key={String(e.etiqueta)}>
                <dt>{String(e.etiqueta)}</dt>
                <dd>{porFormato(e.valor, String(e.formato ?? "numero"))}</dd>
              </div>
            ))}
        </dl>
      ) : null}

      <div className="rc-pie">
        <div className="rc-impacto">
          <strong>
            {moneda(impacto.valor)}
            {periodo ? <small> {periodo}</small> : null}
          </strong>
          <span>{String(impacto.etiqueta ?? "")}</span>
          {impacto.supuesto ? <span className="rc-supuesto">{String(impacto.supuesto)}</span> : null}
        </div>
        <div className="rc-accion">
          <span className="rc-herramienta">
            {String(herramienta.nombre ?? "")}
            {disponible ? null : <em>Próximamente</em>}
          </span>
          <button
            type="button"
            className={`c-button ${disponible ? "c-button-primary" : "c-button-secondary"}`}
            disabled={pensando}
            onClick={() =>
              void emitir(
                "follow_recommendation",
                {
                  recomendacion_id: r.recomendacion_id,
                  herramienta_id: herramienta.herramienta_id,
                  prompt: r.prompt,
                },
                nodoId,
              )
            }
          >
            {disponible ? "Empezar" : "Preguntar al asistente"}
          </button>
        </div>
      </div>
    </li>
  );
}

export function Recommendations({ recomendaciones, titulo, max = 3, nodoId }: RecommendationsProps) {
  const [verTodas, setVerTodas] = useState(false);
  const todas = lista(recomendaciones);
  const tope = Math.max(1, Number(max) || 3);

  if (!todas.length) {
    return <div className="rndr-hueco">Por ahora no encontramos nada urgente que recomendarte.</div>;
  }
  const visibles = verTodas ? todas : todas.slice(0, tope);

  return (
    <section className="rc">
      {titulo ? <h3 className="rc-titulo">{titulo}</h3> : null}
      <ol className="rc-lista">
        {visibles.map((r) => (
          <Recomendacion key={String(r.recomendacion_id)} r={r} nodoId={nodoId} />
        ))}
      </ol>
      {todas.length > tope ? (
        <button type="button" className="rc-mas" onClick={() => setVerTodas((v) => !v)}>
          {verTodas ? "Ver menos" : `Ver ${todas.length - tope} más`}
        </button>
      ) : null}
    </section>
  );
}
