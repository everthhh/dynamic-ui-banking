// bank.SpendingBudgets — control de gasto: presupuesto vs. gastado por
// categoría, con Recharts, más un slider por fila para ajustar el
// presupuesto sin salir del componente (soltar = confirmar, como en
// inv.AmountSlider).

import { useEffect, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ETIQUETA_CATEGORIA, compacto, moneda, porcentaje } from "../format";
import { useStore } from "../store";

type Alerta = {
  categoria?: string;
  presupuesto?: number;
  gastado?: number;
  restante?: number;
  porcentaje?: number;
  excedido?: boolean;
};

export type SpendingBudgetsProps = {
  alertas?: unknown;
  nodoId?: string;
};

function normalizar(entrada: unknown): Alerta[] {
  if (!Array.isArray(entrada)) return [];
  return entrada.filter((a): a is Alerta => typeof a === "object" && a !== null);
}

function FilaPresupuesto({ alerta }: { alerta: Alerta }) {
  const emitir = useStore((s) => s.emitirAccion);
  const pensando = useStore((s) => s.estado === "pensando");
  const presupuesto = Number(alerta.presupuesto) || 0;
  const [local, setLocal] = useState(presupuesto);
  const arrastrando = useRef(false);

  useEffect(() => {
    if (!arrastrando.current) setLocal(presupuesto);
  }, [presupuesto]);

  function soltar() {
    arrastrando.current = false;
    if (Math.round(local) === Math.round(presupuesto)) return;
    void emitir("set_budget", { categoria: alerta.categoria, monto_mensual: Math.round(local) });
  }

  const gastado = Number(alerta.gastado) || 0;
  const pct = Math.min(1, presupuesto ? gastado / presupuesto : 0);

  return (
    <li className={"sb2-fila" + (alerta.excedido ? " excedida" : "")}>
      <div className="sb2-fila-cabeza">
        <span className="sb2-cat">{ETIQUETA_CATEGORIA[alerta.categoria ?? ""] ?? alerta.categoria}</span>
        {alerta.excedido ? <span className="ao-estado bloqueada">Excedido</span> : null}
      </div>
      <div className="sb2-barra">
        <span style={{ width: `${pct * 100}%` }} />
      </div>
      <div className="sb2-cifras">
        <span>{moneda(gastado)} gastado</span>
        <span>{porcentaje(alerta.porcentaje)}</span>
      </div>
      <label className="sl sb2-slider">
        <span className="sl-cabeza">
          <span className="sl-label">Presupuesto</span>
          <strong className="sl-valor">{moneda(local)}</strong>
        </span>
        <input
          type="range"
          min={200}
          max={Math.max(presupuesto * 3, 5000)}
          step={100}
          value={local}
          disabled={pensando}
          onChange={(e) => {
            arrastrando.current = true;
            setLocal(Number(e.target.value));
          }}
          onMouseUp={soltar}
          onTouchEnd={soltar}
          onKeyUp={(e) => {
            if (e.key.startsWith("Arrow") || e.key === "Home" || e.key === "End") soltar();
          }}
        />
      </label>
    </li>
  );
}

export function SpendingBudgets({ alertas }: SpendingBudgetsProps) {
  const lista = normalizar(alertas);

  if (!lista.length) {
    return (
      <div className="rndr-hueco">
        Todavía no hay presupuestos configurados. Pídele al agente que te ayude a poner uno.
      </div>
    );
  }

  const datos = lista.map((a) => ({
    categoria: ETIQUETA_CATEGORIA[a.categoria ?? ""] ?? a.categoria ?? "",
    presupuesto: Number(a.presupuesto) || 0,
    gastado: Number(a.gastado) || 0,
  }));

  return (
    <section className="sb2">
      <ResponsiveContainer width="100%" height={Math.max(140, datos.length * 46)}>
        <BarChart
          data={datos}
          layout="vertical"
          margin={{ top: 4, right: 16, bottom: 4, left: 8 }}
        >
          <CartesianGrid stroke="var(--linea)" horizontal={false} />
          <XAxis
            type="number"
            tickFormatter={(v: number) => compacto(v)}
            tick={{ fontSize: 10, fill: "var(--apagado)" }}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            type="category"
            dataKey="categoria"
            width={84}
            tick={{ fontSize: 12, fill: "var(--tinta)" }}
            tickLine={false}
            axisLine={false}
          />
          <Tooltip formatter={(v: number) => moneda(v)} cursor={{ fill: "var(--fondo)" }} />
          <Bar dataKey="presupuesto" fill="var(--linea)" radius={4} barSize={10} name="Presupuesto" />
          <Bar dataKey="gastado" fill="var(--rojo)" radius={4} barSize={10} name="Gastado" />
        </BarChart>
      </ResponsiveContainer>

      <ul className="sb2-lista">
        {lista.map((a) => (
          <FilaPresupuesto key={a.categoria} alerta={a} />
        ))}
      </ul>
    </section>
  );
}
