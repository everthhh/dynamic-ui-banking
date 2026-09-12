// bank.TransactionSearch — resultados de búsqueda de movimientos, con chips
// de filtro rápido por categoría. El chip no filtra en el cliente: manda
// `refine_search` de vuelta al agente, que vuelve a llamar
// `search_transactions` y reescribe `movimientos` — el cliente sigue sin
// decidir qué se pinta, solo qué se le pide al agente.

import { ETIQUETA_CATEGORIA, conSigno, moneda } from "../format";
import { useStore } from "../store";

type Movimiento = {
  txn_id?: string;
  fecha?: string;
  tipo?: "cargo" | "abono";
  monto?: number;
  categoria?: string;
  descripcion?: string;
  comercio?: string | null;
};

type Filtros = {
  categoria?: string | null;
  comercio?: string | null;
  fecha_desde?: string | null;
  fecha_hasta?: string | null;
};

type Resumen = { total?: number; total_cargos?: number; total_abonos?: number };

export type TransactionSearchProps = {
  movimientos?: unknown;
  filtros?: unknown;
  resumen?: unknown;
  nodoId?: string;
};

const CATEGORIAS_CHIP = [
  "super", "restaurantes", "transporte", "servicios",
  "renta", "salud", "entretenimiento", "educacion",
];

function fechaCorta(iso: string | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso.slice(0, 10)
    : d.toLocaleDateString("es-MX", { day: "2-digit", month: "short" });
}

export function TransactionSearch({ movimientos, filtros, resumen }: TransactionSearchProps) {
  const emitir = useStore((s) => s.emitirAccion);
  const filas = Array.isArray(movimientos) ? (movimientos as Movimiento[]) : [];
  const f = (typeof filtros === "object" && filtros !== null ? filtros : {}) as Filtros;
  const r = (typeof resumen === "object" && resumen !== null ? resumen : {}) as Resumen;

  function filtrarPor(categoria: string | null) {
    void emitir("refine_search", { filtro: { categoria } });
  }

  return (
    <section className="ts">
      <div className="ts-chips">
        <button
          type="button"
          className={"ts-chip" + (!f.categoria ? " activo" : "")}
          onClick={() => filtrarPor(null)}
        >
          Todas
        </button>
        {CATEGORIAS_CHIP.map((c) => (
          <button
            key={c}
            type="button"
            className={"ts-chip" + (f.categoria === c ? " activo" : "")}
            onClick={() => filtrarPor(c)}
          >
            {ETIQUETA_CATEGORIA[c]}
          </button>
        ))}
      </div>

      {(r.total_cargos !== undefined || r.total_abonos !== undefined) && (
        <div className="ts-resumen">
          <span>
            {filas.length} movimiento{filas.length === 1 ? "" : "s"}
          </span>
          <span className="pos-down">−{moneda(r.total_cargos)}</span>
          <span className="pos-up">+{moneda(r.total_abonos)}</span>
        </div>
      )}

      {!filas.length ? (
        <div className="rndr-hueco">Ningún movimiento cumple ese filtro.</div>
      ) : (
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Fecha</th>
                <th>Movimiento</th>
                <th>Categoría</th>
                <th className="der">Monto</th>
              </tr>
            </thead>
            <tbody>
              {filas.map((m, i) => (
                <tr key={m.txn_id ?? i}>
                  <td>{fechaCorta(m.fecha)}</td>
                  <td>
                    <strong>{m.comercio ?? m.descripcion}</strong>
                    {m.comercio ? <span className="tbl-sub">{m.descripcion}</span> : null}
                  </td>
                  <td>{ETIQUETA_CATEGORIA[m.categoria ?? ""] ?? m.categoria}</td>
                  <td className={"der " + (m.tipo === "abono" ? "pos-up" : "pos-down")}>
                    {conSigno(m.tipo === "abono" ? m.monto : -(m.monto ?? 0))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
