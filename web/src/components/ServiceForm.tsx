// pay.ServiceForm — dar de alta un servicio.
//
// La referencia se revisa aquí con la misma regex que publica el convenio
// (`referencia_regex` de get_billers), para no gastar un viaje al agente por un
// dígito de menos. La validación que cuenta es la del servidor.

import { useMemo, useState } from "react";
import { ETIQUETA_SERVICIO } from "../format";
import { useStore } from "../store";

type Convenio = {
  biller_id?: string;
  nombre?: string;
  categoria?: string;
  referencia_etiqueta?: string;
  referencia_regex?: string;
};

export type ServiceFormProps = {
  billers?: unknown;
  categoria?: string;
  nodoId?: string;
};

function cumpleFormato(regex: string | undefined, valor: string): boolean {
  if (!valor) return false;
  if (!regex) return true;
  try {
    return new RegExp(regex).test(valor);
  } catch {
    return true;
  }
}

export function ServiceForm({ nodoId, billers, categoria }: ServiceFormProps) {
  const emitir = useStore((s) => s.emitirAccion);
  const pensando = useStore((s) => s.estado === "pensando");
  const convenios = useMemo(
    () => (Array.isArray(billers) ? (billers as Convenio[]) : []),
    [billers],
  );
  const categorias = useMemo(
    () => [...new Set(convenios.map((c) => c.categoria ?? ""))].filter(Boolean),
    [convenios],
  );

  const [cat, setCat] = useState(
    categoria && categorias.includes(categoria) ? categoria : (categorias[0] ?? ""),
  );
  const [billerId, setBillerId] = useState("");
  const [referencia, setReferencia] = useState("");
  const [alias, setAlias] = useState("");

  if (!convenios.length) {
    return <div className="rndr-hueco">No llegó el catálogo de convenios.</div>;
  }

  const opciones = convenios.filter((c) => c.categoria === cat);
  const elegido = opciones.find((c) => c.biller_id === billerId) ?? opciones[0];
  const limpia = referencia.replace(/[\s-]/g, "");
  const valida = !!elegido && cumpleFormato(elegido.referencia_regex, limpia);

  return (
    <section className="pg-form">
      <div className="ts-chips">
        {categorias.map((c) => (
          <button
            key={c}
            type="button"
            className={"ts-chip" + (c === cat ? " activo" : "")}
            onClick={() => {
              setCat(c);
              setBillerId("");
            }}
          >
            {ETIQUETA_SERVICIO[c] ?? c}
          </button>
        ))}
      </div>

      <label className="pg-campo">
        <span>Empresa</span>
        <select value={elegido?.biller_id ?? ""} onChange={(e) => setBillerId(e.target.value)}>
          {opciones.map((c) => (
            <option key={c.biller_id} value={c.biller_id}>
              {c.nombre}
            </option>
          ))}
        </select>
      </label>

      <label className="pg-campo">
        <span>{elegido?.referencia_etiqueta ?? "Referencia"}</span>
        <input
          inputMode="numeric"
          autoComplete="off"
          value={referencia}
          className={referencia && !valida ? "invalido" : ""}
          placeholder="Cópiala tal cual de tu recibo"
          onChange={(e) => setReferencia(e.target.value)}
        />
        {referencia && !valida ? (
          <small className="pg-error">No coincide con el formato: {elegido?.referencia_etiqueta}.</small>
        ) : null}
      </label>

      <label className="pg-campo">
        <span>Apodo (opcional)</span>
        <input
          maxLength={40}
          value={alias}
          placeholder="Ej. Luz de la casa"
          onChange={(e) => setAlias(e.target.value)}
        />
      </label>

      <div>
        <button
          type="button"
          className="c-button c-button-primary"
          disabled={!valida || pensando}
          onClick={() =>
            void emitir(
              "register_service",
              { biller_id: elegido?.biller_id, referencia: limpia, alias: alias.trim() || null },
              nodoId,
            )
          }
        >
          Registrar y consultar adeudo
        </button>
      </div>
    </section>
  );
}
