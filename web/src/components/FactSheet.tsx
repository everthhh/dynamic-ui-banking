// inv.FactSheet y inv.SpendingBreakdown.

import {
  ETIQUETA_CLASE,
  ETIQUETA_LIQUIDEZ,
  ETIQUETA_RIESGO,
  compacto,
  moneda,
  numero,
  porcentaje,
} from "../format";

type Obj = Record<string, unknown>;

export type FactSheetProps = {
  instrument?: unknown;
  mostrarHistoria?: boolean;
  nodoId?: string;
};

function miniSerie(serie: Obj[]): string | null {
  const valores = serie.map((p) => Number(p.valor_unitario)).filter(Number.isFinite);
  if (valores.length < 2) return null;
  const min = Math.min(...valores);
  const max = Math.max(...valores);
  const rango = Math.max(1e-9, max - min);
  const W = 320;
  const H = 64;
  return valores
    .map((v, i) => {
      const x = (i / (valores.length - 1)) * W;
      const y = H - ((v - min) / rango) * (H - 6) - 3;
      return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
}

export function FactSheet({ instrument, mostrarHistoria = true }: FactSheetProps) {
  const inst = (typeof instrument === "object" && instrument !== null ? instrument : {}) as Obj;
  if (!inst.instrument_id) {
    return <div className="rndr-hueco">El detalle del instrumento llegó vacío.</div>;
  }

  const historia = (typeof inst.historia === "object" && inst.historia !== null
    ? inst.historia
    : {}) as Obj;
  const serie = Array.isArray(historia.serie) ? (historia.serie as Obj[]) : [];
  const path = mostrarHistoria ? miniSerie(serie) : null;
  const peores = Array.isArray(historia.peores_meses) ? (historia.peores_meses as Obj[]) : [];

  return (
    <section className="fs">
      <header className="fs-cabeza">
        <div>
          <strong className="fs-nombre">{String(inst.nombre)}</strong>
          <span className="fs-clase">
            {ETIQUETA_CLASE[String(inst.clase)] ?? String(inst.clase)} · {String(inst.emisor)}
          </span>
        </div>
        <code className="fs-id">{String(inst.instrument_id)}</code>
      </header>

      <p className="fs-desc">{String(inst.descripcion ?? "")}</p>

      <div className="fs-grid">
        <div>
          <span>Rendimiento esperado</span>
          <strong>{porcentaje(inst.rend_esperado_anual)}</strong>
        </div>
        <div>
          <span>Volatilidad</span>
          <strong>{porcentaje(inst.volatilidad_anual)}</strong>
        </div>
        <div>
          <span>Comisión</span>
          <strong>{porcentaje(inst.comision_anual)}</strong>
        </div>
        <div>
          <span>Riesgo</span>
          <strong>{ETIQUETA_RIESGO[Number(inst.riesgo_1a5)] ?? "—"}</strong>
        </div>
        <div>
          <span>Liquidez</span>
          <strong>{ETIQUETA_LIQUIDEZ[String(inst.liquidez)] ?? "—"}</strong>
        </div>
        <div>
          <span>Mínimo</span>
          <strong>{moneda(inst.monto_minimo)}</strong>
        </div>
      </div>

      {path ? (
        <div className="fs-historia">
          <span className="fs-historia-label">
            {String(historia.meses ?? "")} meses · rendimiento realizado{" "}
            {porcentaje(historia.cagr_realizado)}
          </span>
          <svg viewBox="0 0 320 64" className="fs-spark" role="img" aria-label="Serie histórica">
            <path d={path} />
          </svg>
          {peores.length ? (
            <span className="fs-peores">
              Peor mes: {porcentaje(peores[0]?.rend_mensual)} ({String(peores[0]?.fecha ?? "")})
            </span>
          ) : null}
        </div>
      ) : null}

      <p className="fs-disclaimer">
        {String(inst.disclaimer ?? "Serie sintética. No es historia real.")}
      </p>
    </section>
  );
}

export type SpendingBreakdownProps = {
  categorias?: unknown;
  capacidadAhorro?: unknown;
  ingresoMensual?: unknown;
  nodoId?: string;
};

export function SpendingBreakdown({
  categorias,
  capacidadAhorro,
  ingresoMensual,
}: SpendingBreakdownProps) {
  const filas = Array.isArray(categorias) ? (categorias as Obj[]) : [];
  if (!filas.length) {
    return <div className="rndr-hueco">No hay gasto que desglosar.</div>;
  }
  const maximo = Math.max(...filas.map((f) => Number(f.promedio_mensual) || 0), 1);
  const ingreso = Number(ingresoMensual);

  return (
    <section className="sb">
      <div className="sb-resumen">
        <div>
          <span>Ingreso mensual</span>
          <strong>{moneda(ingreso)}</strong>
        </div>
        <div>
          <span>Te queda libre</span>
          <strong className="pos-up">{moneda(capacidadAhorro)}</strong>
        </div>
      </div>

      <ul className="sb-barras">
        {filas.map((f) => {
          const v = Number(f.promedio_mensual) || 0;
          return (
            <li key={String(f.categoria)}>
              <span className="sb-cat">
                {String(f.categoria)}
                {f.esencial ? <em className="sb-esencial">esencial</em> : null}
              </span>
              <span className="sb-barra">
                <span style={{ width: `${(v / maximo) * 100}%` }} />
              </span>
              <span className="sb-monto">{compacto(v)}</span>
            </li>
          );
        })}
      </ul>

      <p className="sb-nota">
        Promedio mensual de los últimos meses. {numero(filas.length)} categorías con movimiento.
      </p>
    </section>
  );
}
