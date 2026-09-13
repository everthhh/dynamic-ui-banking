// bank.TransactionSearch — resultados de búsqueda de movimientos, con chips
// de filtro rápido por categoría.
//
// El agente manda TODO el histórico una sola vez, al montar el componente
// (`movimientosCompletos`, regla 8c). A partir de ahí, cada clic en un chip
// filtra esa copia con código puro (`filtroLocal.ts`) — cero ida y vuelta al
// servidor, y por lo tanto cero llamada al LLM por clic. Si por lo que sea
// el blueprint no trae el caché completo (una superficie vieja, o el modelo
// se saltó la regla), se cae de vuelta al camino de red de siempre
// (`refine_search`), sin romperse.

import { useState } from "react";
import { ETIQUETA_CATEGORIA, conSigno, moneda } from "../format";
import { filtrarMovimientos, resumenDe, type Movimiento } from "../filtroLocal";
import { useStore } from "../store";

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
  movimientosCompletos?: unknown;
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

export function TransactionSearch({
  movimientos,
  filtros,
  resumen,
  movimientosCompletos,
}: TransactionSearchProps) {
  const emitir = useStore((s) => s.emitirAccion);
  const filas = Array.isArray(movimientos) ? (movimientos as Movimiento[]) : [];
  const f = (typeof filtros === "object" && filtros !== null ? filtros : {}) as Filtros;
  const r = (typeof resumen === "object" && resumen !== null ? resumen : {}) as Resumen;

  const completos = Array.isArray(movimientosCompletos)
    ? (movimientosCompletos as Movimiento[])
    : null;
  const [categoriaLocal, setCategoriaLocal] = useState<string | null>(f.categoria ?? null);

  function filtrarPor(categoria: string | null) {
    if (completos) {
      setCategoriaLocal(categoria);            // cómputo local, cero red
      return;
    }
    void emitir("refine_search", { filtro: { categoria } });   // fallback: sin caché, va al agente
  }

  const categoriaActiva = completos ? categoriaLocal : f.categoria ?? null;
  const mostrar = completos ? filtrarMovimientos(completos, { categoria: categoriaLocal }) : filas;
  const resumenMostrado = completos ? resumenDe(mostrar) : r;

  return (
    <section className="ts">
      <div className="ts-chips">
        <button
          type="button"
          className={"ts-chip" + (!categoriaActiva ? " activo" : "")}
          onClick={() => filtrarPor(null)}
        >
          Todas
        </button>
        {CATEGORIAS_CHIP.map((c) => (
          <button
            key={c}
            type="button"
            className={"ts-chip" + (categoriaActiva === c ? " activo" : "")}
            onClick={() => filtrarPor(c)}
          >
            {ETIQUETA_CATEGORIA[c]}
          </button>
        ))}
      </div>

      {(resumenMostrado.total_cargos !== undefined || resumenMostrado.total_abonos !== undefined) && (
        <div className="ts-resumen">
          <span>
            {mostrar.length} movimiento{mostrar.length === 1 ? "" : "s"}
          </span>
          <span className="pos-down">−{moneda(resumenMostrado.total_cargos)}</span>
          <span className="pos-up">+{moneda(resumenMostrado.total_abonos)}</span>
        </div>
      )}

      {!mostrar.length ? (
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
              {mostrar.map((m, i) => (
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
