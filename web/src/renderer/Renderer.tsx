// El renderer: ~100 líneas que convierten el árbol de componentes en React.
//
// Lo único que hace es:
//   1. resolver los bindings (`{"path": "/sim"}` -> valor del data model),
//   2. buscar el componente en el registry,
//   3. montar los hijos por id.
//
// No decide layout, no calcula nada y no sabe qué significa ningún prop. Si
// aquí hubiera lógica de negocio, el agente dejaría de ser quien diseña la
// pantalla.

import { Fragment, type ReactNode } from "react";
import { esBinding, type ComponentNode } from "../a2ui";
import { REGISTRY } from "../registry";
import { useStore } from "../store";

const MAX_PROFUNDIDAD = 12;

export type PropsResueltas = Record<string, unknown>;

/** Sustituye cada binding por su valor actual del data model. */
export function resolverProps(nodo: ComponentNode, leerRuta: (p: string) => unknown): PropsResueltas {
  const salida: PropsResueltas = {};
  for (const [clave, valor] of Object.entries(nodo)) {
    if (clave === "id" || clave === "component" || clave === "children") continue;
    salida[clave] = esBinding(valor) ? leerRuta(valor.path) : valor;
  }
  return salida;
}

export type NodoProps = {
  id: string;
  profundidad?: number;
};

export function Nodo({ id, profundidad = 0 }: NodoProps): ReactNode {
  const sid = useStore((s) => s.superficieActiva);
  const superficie = useStore((s) => (sid ? s.superficies[sid] : undefined));
  const leerRuta = useStore((s) => s.leerRuta);

  if (!superficie) return null;
  const nodo = superficie.componentes[id];
  if (!nodo) {
    return (
      <div className="rndr-hueco" role="note">
        Falta el componente <code>{id}</code>.
      </div>
    );
  }
  if (profundidad > MAX_PROFUNDIDAD) {
    return <div className="rndr-hueco">Árbol demasiado profundo en <code>{id}</code>.</div>;
  }

  const Componente = REGISTRY[nodo.component];
  if (!Componente) {
    // No debería pasar: el store ya filtra por allowlist. Queda como red de
    // seguridad visible en lugar de una pantalla a medias.
    return (
      <div className="rndr-hueco">
        <code>{nodo.component}</code> no está en el registry.
      </div>
    );
  }

  const props = resolverProps(nodo, leerRuta);
  const hijos = (nodo.children ?? []).map((hijoId) => (
    <Nodo key={hijoId} id={hijoId} profundidad={profundidad + 1} />
  ));

  return (
    <Componente {...props} nodoId={nodo.id}>
      {hijos.length ? hijos : null}
    </Componente>
  );
}

export function Superficie(): ReactNode {
  const sid = useStore((s) => s.superficieActiva);
  const superficie = useStore((s) => (sid ? s.superficies[sid] : undefined));

  if (!superficie || !superficie.rootId) {
    return (
      <div className="rndr-vacio">
        <p>Aquí va a aparecer la pantalla que arme el agente.</p>
        <p className="rndr-vacio-nota">
          Escribe algo abajo. Por ejemplo: «tengo 80 mil pesos parados y los podría dejar 5 años».
        </p>
      </div>
    );
  }

  const estilo = Object.fromEntries(
    Object.entries(superficie.theme).map(([k, v]) => [`--${k}`, String(v)]),
  ) as Record<string, string>;

  return (
    <Fragment>
      <div className="rndr-superficie" style={estilo} data-surface={superficie.surfaceId}>
        <Nodo id={superficie.rootId} />
      </div>
    </Fragment>
  );
}
