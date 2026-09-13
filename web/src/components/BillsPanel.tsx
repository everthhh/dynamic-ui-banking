// pay.BillsPanel — recibos por pagar.
//
// Cada recibo trae su botón «Pagar», pero el botón NO paga: emite `pay_bill` y
// el agente llama el paso 1 (`pay_service`), que regresa un pay.PaymentTicket
// por confirmar. El dinero solo se mueve desde el ticket.

import { ETIQUETA_SERVICIO, fechaCorta, moneda } from "../format";
import { useStore } from "../store";

type Recibo = {
  periodo?: string;
  total?: number;
  fecha_limite?: string;
  dias_para_vencer?: number;
  vencido?: boolean;
};

type Servicio = {
  service_id?: string;
  nombre?: string;
  convenio?: string;
  categoria?: string;
  referencia_mask?: string | null;
  recibo?: Recibo | null;
};

type Resumen = { total_por_pagar?: number; recibos_pendientes?: number; vencidos?: number };

export type BillsPanelProps = {
  servicios?: unknown;
  resumen?: unknown;
  nodoId?: string;
};

function vencimiento(r: Recibo): { texto: string; tono: string } {
  const dias = Number(r.dias_para_vencer);
  const plural = (n: number) => (n === 1 ? "" : "s");
  if (r.vencido) {
    const n = Math.abs(dias);
    return { texto: `Venció hace ${n} día${plural(n)}`, tono: "danger" };
  }
  if (dias === 0) return { texto: "Vence hoy", tono: "warning" };
  if (dias <= 5) return { texto: `Vence en ${dias} día${plural(dias)}`, tono: "warning" };
  return { texto: `Vence el ${fechaCorta(r.fecha_limite)}`, tono: "neutral" };
}

export function BillsPanel({ nodoId, servicios, resumen }: BillsPanelProps) {
  const emitir = useStore((s) => s.emitirAccion);
  const pensando = useStore((s) => s.estado === "pensando");
  const lista = Array.isArray(servicios) ? (servicios as Servicio[]) : [];
  const r = (typeof resumen === "object" && resumen !== null ? resumen : {}) as Resumen;

  return (
    <section className="pg-bills">
      {r.total_por_pagar !== undefined ? (
        <header className="pg-cabeza">
          <div>
            <span className="pg-label">
              Por pagar · {r.recibos_pendientes ?? 0} recibo{r.recibos_pendientes === 1 ? "" : "s"}
            </span>
            <strong className="pg-monto">{moneda(r.total_por_pagar, true)}</strong>
          </div>
          {r.vencidos ? (
            <span className="c-badge c-badge-danger">
              {r.vencidos} vencido{r.vencidos === 1 ? "" : "s"}
            </span>
          ) : null}
        </header>
      ) : null}

      {!lista.length ? (
        <div className="rndr-hueco">Todavía no hay servicios registrados.</div>
      ) : (
        <ul className="pg-lista">
          {lista.map((s, i) => {
            const rec = s.recibo;
            const v = rec ? vencimiento(rec) : null;
            return (
              <li key={s.service_id ?? i} className={"pg-item" + (rec?.vencido ? " vencido" : "")}>
                <span className={`pg-cat pg-cat-${s.categoria ?? "otro"}`}>
                  {ETIQUETA_SERVICIO[s.categoria ?? ""] ?? s.categoria}
                </span>
                <div className="pg-item-info">
                  <strong>{s.nombre}</strong>
                  <span className="pg-sub">
                    {[s.nombre !== s.convenio ? s.convenio : null, s.referencia_mask, rec?.periodo]
                      .filter(Boolean)
                      .join(" · ")}
                  </span>
                </div>
                {rec && v ? (
                  <>
                    <div className="pg-item-cobro">
                      <strong>{moneda(rec.total, true)}</strong>
                      <span className={`pg-vence pg-vence-${v.tono}`}>{v.texto}</span>
                    </div>
                    <button
                      type="button"
                      className="c-button c-button-primary"
                      disabled={pensando}
                      onClick={() => void emitir("pay_bill", { service_id: s.service_id }, nodoId)}
                    >
                      Pagar
                    </button>
                  </>
                ) : (
                  <span className="pg-al-corriente">Al corriente</span>
                )}
              </li>
            );
          })}
        </ul>
      )}

      <div>
        <button
          type="button"
          className="c-button c-button-secondary"
          disabled={pensando}
          onClick={() => void emitir("add_service", {}, nodoId)}
        >
          Agregar servicio
        </button>
      </div>
    </section>
  );
}
