// Chequeo en tiempo de compilación: el registry cubre el catálogo completo,
// ni un componente de más ni uno de menos.
//
// `tsc --noEmit` falla si alguien agrega un componente a catalog.json, regenera
// los tipos y se olvida del React. Es la mitad del front del test de contrato
// (la otra mitad está en a2ui/tests/test_contract.py).

import { COMPONENT_NAMES, type ComponentName } from "./catalog.types";
import { REGISTRY } from "./registry";

type LlavesDelRegistry = keyof typeof REGISTRY;

// Si falta un componente del catálogo en el registry, esta línea no compila.
const _cobertura: Record<ComponentName, LlavesDelRegistry> = Object.fromEntries(
  COMPONENT_NAMES.map((n) => [n, n]),
) as Record<ComponentName, LlavesDelRegistry>;

/** Componentes registrados que NO están en el catálogo. Debe ser vacío. */
export function sobrantesEnRegistry(): string[] {
  const delCatalogo = new Set<string>(COMPONENT_NAMES);
  return Object.keys(REGISTRY).filter((k) => !delCatalogo.has(k));
}

/** Componentes del catálogo sin implementación. Debe ser vacío. */
export function faltantesEnRegistry(): string[] {
  return COMPONENT_NAMES.filter((n) => !(n in REGISTRY));
}

export function verificarRegistry(): void {
  const sobran = sobrantesEnRegistry();
  const faltan = faltantesEnRegistry();
  if (sobran.length || faltan.length) {
    throw new Error(
      "El registry y el catálogo no coinciden." +
        (faltan.length ? ` Sin implementar: ${faltan.join(", ")}.` : "") +
        (sobran.length ? ` Fuera del catálogo: ${sobran.join(", ")}.` : ""),
    );
  }
}

void _covertura_usada(_cobertura);
function _covertura_usada(_: unknown): void {
  /* solo para que el chequeo de tipos no quede como variable sin usar */
}
