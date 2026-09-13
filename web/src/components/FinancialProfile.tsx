// bank.FinancialProfile — la radiografía financiera del cliente.
//
// Todo lo que se pinta viene calculado en `get_financial_profile`
// (bank/finance/perfil.py): el componente no suma, no promedia ni decide qué
// es "gasto hormiga" o "paga el mínimo". Solo acomoda lo que llegó.

import { ETIQUETA_CATEGORIA, compacto as cifraCompacta, moneda } from "../format";

type Obj = Record<string, unknown>;

const obj = (v: unknown): Obj =>
  typeof v === "object" && v !== null && !Array.isArray(v) ? (v as Obj) : {};
const lista = (v: unknown): Obj[] =>
  Array.isArray(v) ? (v as unknown[]).filter((x): x is Obj => typeof x === "object" && x !== null) : [];
const num = (v: unknown): number => {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
};
// En un tablero de un vistazo, "68%" se lee mejor que "67.76%".
const pct = (v: unknown): string => `${Math.round(num(v) * 100)}%`;

export type FinancialProfileProps = {
  perfil?: unknown;
  compacto?: boolean;
  nodoId?: string;
};

const TONO_NIVEL: Record<string, string> = {
  "sólida": "positive",
  estable: "info",
  "frágil": "warning",
  "en riesgo": "danger",
};

function Anillo({ score, nivel }: { score: number; nivel: string }) {
  const radio = 42;
  const circunferencia = 2 * Math.PI * radio;
  const lleno = (Math.max(0, Math.min(100, score)) / 100) * circunferencia;
  return (
    <div className={`fp-anillo fp-${TONO_NIVEL[nivel] ?? "info"}`}>
      <svg viewBox="0 0 100 100" role="img" aria-label={`Salud financiera: ${Math.round(score)} de 100`}>
        <circle cx="50" cy="50" r={radio} className="fp-anillo-fondo" />
        <circle
          cx="50"
          cy="50"
          r={radio}
          className="fp-anillo-valor"
          strokeDasharray={`${lleno} ${circunferencia}`}
          transform="rotate(-90 50 50)"
        />
      </svg>
      <div className="fp-anillo-centro">
        <strong>{Math.round(score)}</strong>
        <span>de 100</span>
      </div>
    </div>
  );
}

const SEGMENTOS = [
  { clave: "consumo_esencial_mensual", etiqueta: "Gasto esencial", color: "#3c4350" },
  { clave: "consumo_discrecional_mensual", etiqueta: "Gasto discrecional", color: "#f97066" },
  { clave: "pagos_credito_mensual", etiqueta: "Créditos", color: "#dc6803" },
  { clave: "costo_financiero_mensual", etiqueta: "Intereses y comisiones", color: "#b42318" },
  { clave: "ahorro_mensual", etiqueta: "Te queda", color: "#067647" },
] as const;

function RepartoIngreso({ flujo }: { flujo: Obj }) {
  const ingreso = num(flujo.ingreso_mensual);
  const valores = SEGMENTOS.map((s) => ({ ...s, valor: Math.max(0, num(flujo[s.clave])) }));
  const total = Math.max(ingreso, valores.reduce((a, s) => a + s.valor, 0), 1);
  const deficit = num(flujo.ahorro_mensual) < 0;
  return (
    <div className="fp-seccion">
      <h4>¿A dónde se va tu ingreso?</h4>
      <div className="fp-reparto" role="img" aria-label="Reparto del ingreso mensual">
        {valores.map((s) =>
          s.valor > 0 ? (
            <span
              key={s.clave}
              style={{ width: `${(s.valor / total) * 100}%`, background: s.color }}
              title={`${s.etiqueta}: ${moneda(s.valor)}`}
            />
          ) : null,
        )}
      </div>
      <ul className="fp-leyenda">
        {valores.map((s) =>
          s.valor > 0 ? (
            <li key={`leyenda-${s.clave}`}>
              <span className="fp-punto" style={{ background: s.color }} />
              {s.etiqueta} <strong>{moneda(s.valor)}</strong>
            </li>
          ) : null,
        )}
      </ul>
      {deficit ? (
        <p className="fp-alerta">
          Gastas más de lo que entra: te faltan {moneda(-num(flujo.ahorro_mensual))} al mes.
        </p>
      ) : null}
    </div>
  );
}

function Consumo({ consumo }: { consumo: Obj }) {
  const categorias = lista(consumo.por_categoria).slice(0, 6);
  const maximo = Math.max(1, ...categorias.map((c) => num(c.promedio_mensual)));
  const subs = obj(consumo.suscripciones);
  const hormiga = obj(consumo.gasto_hormiga);
  return (
    <div className="fp-seccion">
      <h4>Tus hábitos de consumo</h4>
      <ul className="fp-cats">
        {categorias.map((c) => {
          const tendencia = c.tendencia === null || c.tendencia === undefined ? null : num(c.tendencia);
          const marca =
            tendencia !== null && tendencia >= 0.25 ? (
              <span className="fp-tend sube">▲ {pct(tendencia)}</span>
            ) : tendencia !== null && tendencia <= -0.25 ? (
              <span className="fp-tend baja">▼ {pct(-tendencia)}</span>
            ) : null;
          return (
            <li key={String(c.categoria)} className="fp-cat">
              <span className="fp-cat-nombre">
                {ETIQUETA_CATEGORIA[String(c.categoria)] ?? String(c.categoria)}
                {marca}
              </span>
              <span className="fp-cat-barra">
                <span style={{ width: `${(num(c.promedio_mensual) / maximo) * 100}%` }} />
              </span>
              <span className="fp-cat-monto">{cifraCompacta(num(c.promedio_mensual))}</span>
            </li>
          );
        })}
      </ul>
      <ul className="fp-lista">
        <li>
          <span>
            Suscripciones detectadas <span className="fp-sub">({lista(subs.detectadas).length})</span>
          </span>
          <span>{moneda(subs.total_mensual)} al mes</span>
        </li>
        <li>
          <span>
            Compras chicas <span className="fp-sub">({num(hormiga.compras_mes).toFixed(0)} al mes)</span>
          </span>
          <span>
            {moneda(hormiga.gasto_mensual)} · {pct(hormiga.pct_ingreso)}
          </span>
        </li>
        <li>
          <span>Pagado con tarjeta de crédito</span>
          <span>{pct(consumo.pct_con_tarjeta_credito)}</span>
        </li>
      </ul>
    </div>
  );
}

function Credito({ credito, liquidez }: { credito: Obj; liquidez: Obj }) {
  const tarjetas = lista(credito.tarjetas);
  const prestamos = lista(credito.prestamos);
  const salud = obj(credito.salud_crediticia);
  return (
    <div className="fp-seccion">
      <h4>Tu crédito y tu colchón</h4>
      <ul className="fp-lista">
        {tarjetas.map((t) => (
          <li key={String(t.card_id)}>
            <span>
              Tarjeta •••• {String(t.last4)}
              <span className="fp-sub">
                {" "}
                · {String(t.habito_etiqueta ?? "")} ({num(t.pagos_completos)} de {num(t.cortes_evaluados)} cortes
                completos)
              </span>
            </span>
            <span>
              {moneda(t.saldo)}
              {num(t.costo_12m) > 0 ? (
                <span className="fp-sub fp-costo"> · {moneda(t.costo_12m)} en intereses</span>
              ) : null}
            </span>
          </li>
        ))}
        {prestamos.map((p) => (
          <li key={String(p.loan_id)}>
            <span>
              {String(p.etiqueta)}
              <span className="fp-sub"> · {num(p.mensualidades_restantes)} mensualidades</span>
            </span>
            <span>{moneda(p.pago_mensual)} al mes</span>
          </li>
        ))}
        <li>
          <span>
            Comportamiento de crédito <span className="fp-sub">({String(salud.nivel ?? "—")})</span>
          </span>
          <span>{Math.round(num(salud.score))}/100</span>
        </li>
        <li>
          <span>
            Colchón para emergencias{" "}
            <span className="fp-sub">(objetivo {num(liquidez.colchon_objetivo_meses)} meses)</span>
          </span>
          <span>{num(liquidez.meses_de_colchon).toFixed(1)} meses</span>
        </li>
        <li>
          <span>Efectivo sin invertir</span>
          <span>{moneda(liquidez.efectivo_ocioso)}</span>
        </li>
      </ul>
    </div>
  );
}

export function FinancialProfile({ perfil, compacto = false }: FinancialProfileProps) {
  const p = obj(perfil);
  if (!p.client_id) {
    return <div className="rndr-hueco">El perfil financiero llegó vacío.</div>;
  }
  const salud = obj(p.salud_financiera);
  const flujo = obj(p.flujo);
  const credito = obj(p.credito);
  const liquidez = obj(p.liquidez);
  const identidad = obj(p.identidad);
  const productos = obj(p.productos);
  const rasgos = lista(p.rasgos);
  const ingreso = num(flujo.ingreso_mensual);
  const nivel = String(salud.nivel ?? "");

  return (
    <section className="fp">
      <header className="fp-cabeza">
        <Anillo score={num(salud.score)} nivel={nivel} />
        <div className="fp-intro">
          <span className="fp-nivel">
            Salud financiera <strong>{nivel}</strong>
            {identidad.ocupacion ? ` · ${String(identidad.ocupacion)}` : ""}
            {identidad.edad ? ` · ${num(identidad.edad)} años` : ""}
          </span>
          <p className="fp-resumen">{String(p.resumen ?? "")}</p>
          <div className="fp-rasgos">
            {rasgos.map((r) => (
              <span
                key={String(r.rasgo)}
                className={`fp-rasgo fp-rasgo-${String(r.tono)}`}
                title={String(r.dato ?? "")}
              >
                {String(r.etiqueta)}
              </span>
            ))}
          </div>
        </div>
      </header>

      <div className="fp-kpis">
        <div className="fp-kpi">
          <span>Ingreso mensual</span>
          <strong>{moneda(ingreso)}</strong>
          <small>{flujo.tipo_ingreso === "variable" ? "variable" : "fijo"}</small>
        </div>
        <div className="fp-kpi">
          <span>Gasto en consumo</span>
          <strong>{moneda(flujo.consumo_mensual)}</strong>
          <small>{ingreso ? pct(num(flujo.consumo_mensual) / ingreso) : "—"} del ingreso</small>
        </div>
        <div className="fp-kpi">
          <span>Te queda al mes</span>
          <strong className={num(flujo.ahorro_mensual) < 0 ? "pos-down" : undefined}>
            {moneda(flujo.ahorro_mensual)}
          </strong>
          <small>{pct(flujo.tasa_ahorro)} de tu ingreso</small>
        </div>
        <div className="fp-kpi">
          <span>Deuda total</span>
          <strong>{moneda(credito.deuda_total)}</strong>
          <small>pagos: {pct(flujo.carga_deuda)} del ingreso</small>
        </div>
      </div>

      {compacto ? null : (
        <>
          <RepartoIngreso flujo={flujo} />
          <div className="fp-grid">
            <Consumo consumo={obj(p.consumo)} />
            <Credito credito={credito} liquidez={liquidez} />
          </div>
          <div className="fp-seccion">
            <h4>Productos que usas ({num(productos.total)})</h4>
            <div className="fp-productos">
              {lista(productos.lista).map((x, i) => (
                <span key={`${String(x.producto)}-${i}`} className="fp-producto">
                  {String(x.etiqueta)}
                </span>
              ))}
            </div>
          </div>
          <details className="fp-detalle">
            <summary>¿Cómo se calcula tu salud financiera?</summary>
            <div className="tbl-wrap">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>Factor</th>
                    <th>Dato</th>
                    <th className="der">Puntos</th>
                    <th className="der">Peso</th>
                    <th className="der">Aporte</th>
                  </tr>
                </thead>
                <tbody>
                  {lista(salud.desglose).map((f) => (
                    <tr key={String(f.factor)}>
                      <td>{String(f.etiqueta)}</td>
                      <td>{String(f.dato ?? "")}</td>
                      <td className="der">{Math.round(num(f.valor))}</td>
                      <td className="der">{pct(f.peso)}</td>
                      <td className="der">{num(f.aporte).toFixed(1)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </>
      )}
    </section>
  );
}
