// Data model de una superficie: un árbol JSON direccionable por ruta
// (`/sim/escenarios/p50`). Las escrituras son inmutables para que React vea el
// cambio, pero solo clonan la rama tocada, no todo el árbol: mover un slider
// con 5000 puntos de serie a un lado no debe copiar la serie.

export type DataModel = Record<string, unknown>;

function segmentos(path: string): string[] {
  if (!path.startsWith("/")) {
    throw new Error(`ruta inválida (debe empezar con '/'): ${path}`);
  }
  return path.split("/").filter((s) => s.length > 0);
}

export function leer(modelo: DataModel, path: string): unknown {
  let actual: unknown = modelo;
  for (const seg of segmentos(path)) {
    if (actual === null || actual === undefined) return undefined;
    if (Array.isArray(actual)) {
      const i = Number(seg);
      if (!Number.isInteger(i)) return undefined;
      actual = actual[i];
    } else if (typeof actual === "object") {
      actual = (actual as Record<string, unknown>)[seg];
    } else {
      return undefined;
    }
  }
  return actual;
}

export function escribir(modelo: DataModel, path: string, valor: unknown): DataModel {
  const segs = segmentos(path);
  if (segs.length === 0) {
    return (valor ?? {}) as DataModel;
  }

  const clonar = (nodo: unknown, nivel: number): unknown => {
    const seg = segs[nivel]!;
    const esIndice = /^\d+$/.test(seg);
    const ultimo = nivel === segs.length - 1;

    if (esIndice) {
      const arr = Array.isArray(nodo) ? [...nodo] : [];
      const i = Number(seg);
      arr[i] = ultimo ? valor : clonar(arr[i], nivel + 1);
      return arr;
    }

    const obj: Record<string, unknown> =
      nodo !== null && typeof nodo === "object" && !Array.isArray(nodo)
        ? { ...(nodo as Record<string, unknown>) }
        : {};
    obj[seg] = ultimo ? valor : clonar(obj[seg], nivel + 1);
    return obj;
  };

  return clonar(modelo, 0) as DataModel;
}

/** Rutas que el data model ya conoce, para depuración. */
export function rutas(modelo: DataModel, prefijo = ""): string[] {
  const salida: string[] = [];
  for (const [k, v] of Object.entries(modelo)) {
    const ruta = `${prefijo}/${k}`;
    salida.push(ruta);
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      salida.push(...rutas(v as DataModel, ruta));
    }
  }
  return salida;
}
