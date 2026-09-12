// Estado del renderer.
//
// Dos invariantes que definen el proyecto:
//
//   1. El cliente NO decide layout. Solo aplica los mensajes que llegan.
//   2. Una interacción del usuario NO actualiza la pantalla por su cuenta:
//      escribe el valor local (para que el control se sienta inmediato) y manda
//      la acción al agente, que decide qué cambia. Por eso `emitirAccion` vive
//      aquí y no dentro de cada componente.

import { create } from "zustand";
import {
  esCreateSurface,
  esDeleteSurface,
  esUpdateComponents,
  esUpdateDataModel,
  type A2UIMessage,
  type ComponentNode,
} from "./a2ui";
import { CATALOG_ID, COMPONENT_NAMES, THEME, type ActionName } from "./catalog.types";
import { escribir, leer, type DataModel } from "./dataModel";
import { enviarAccion } from "./transport";

const PERMITIDOS = new Set<string>(COMPONENT_NAMES);

export type Estado = "inactivo" | "pensando" | "esperando_confirmacion" | "error";

export type EntradaTraza = {
  t: number;
  tipo: string;
  detalle: string;
};

export type Superficie = {
  surfaceId: string;
  theme: Record<string, string | number>;
  componentes: Record<string, ComponentNode>;
  rootId: string | null;
  datos: DataModel;
};

type Store = {
  sessionId: string | null;
  clientId: string;
  superficieActiva: string | null;
  superficies: Record<string, Superficie>;
  estado: Estado;
  mensajesDeChat: { rol: "usuario" | "agente"; texto: string }[];
  traza: EntradaTraza[];
  ignorados: string[];
  error: string | null;

  setSession: (id: string) => void;
  setClient: (id: string) => void;
  setEstado: (e: Estado) => void;
  setError: (m: string | null) => void;
  agregarChat: (rol: "usuario" | "agente", texto: string) => void;
  trazar: (tipo: string, detalle: string) => void;
  reset: () => void;

  aplicar: (msg: A2UIMessage) => void;
  /** Escritura local optimista: el control se siente inmediato. */
  escribirLocal: (path: string, valor: unknown) => void;
  leerRuta: (path: string) => unknown;
  /** `origenId`: el id del componente que disparó la acción (`sourceComponentId` en el wire). */
  emitirAccion: (
    nombre: ActionName,
    contexto?: Record<string, unknown>,
    origenId?: string,
  ) => Promise<void>;
};

function superficieVacia(surfaceId: string, theme?: Record<string, string | number>): Superficie {
  return {
    surfaceId,
    theme: { ...THEME, ...(theme ?? {}) },
    componentes: {},
    rootId: null,
    datos: {},
  };
}

export const useStore = create<Store>((set, get) => ({
  sessionId: null,
  clientId: "CLI-0001",
  superficieActiva: null,
  superficies: {},
  estado: "inactivo",
  mensajesDeChat: [],
  traza: [],
  ignorados: [],
  error: null,

  setSession: (id) => set({ sessionId: id }),
  setClient: (id) => set({ clientId: id }),
  setEstado: (estado) => set({ estado }),
  setError: (error) => set({ error, estado: error ? "error" : "inactivo" }),

  agregarChat: (rol, texto) =>
    set((s) => ({ mensajesDeChat: [...s.mensajesDeChat, { rol, texto }] })),

  trazar: (tipo, detalle) =>
    set((s) => ({ traza: [...s.traza.slice(-60), { t: Date.now(), tipo, detalle }] })),

  reset: () =>
    set({
      sessionId: null,
      superficieActiva: null,
      superficies: {},
      estado: "inactivo",
      mensajesDeChat: [],
      traza: [],
      ignorados: [],
      error: null,
    }),

  aplicar: (msg) => {
    // ---------------------------------------------------------- createSurface
    if (esCreateSurface(msg)) {
      const { surfaceId, catalogId, theme } = msg.createSurface;
      if (catalogId !== CATALOG_ID) {
        get().trazar(
          "catalogo_ajeno",
          `Ignoré createSurface con catalogId ${catalogId}: este renderer solo monta ${CATALOG_ID}.`,
        );
        return;
      }
      set((s) => ({
        superficieActiva: surfaceId,
        superficies: { ...s.superficies, [surfaceId]: superficieVacia(surfaceId, theme) },
      }));
      get().trazar("createSurface", surfaceId);
      return;
    }

    // ------------------------------------------------------- updateComponents
    if (esUpdateComponents(msg)) {
      const { surfaceId, components } = msg.updateComponents;
      const ignorados: string[] = [];
      const mapa: Record<string, ComponentNode> = {};
      for (const nodo of components) {
        // Allowlist: A2UI es datos, no código. Lo que no está en el catálogo
        // no se monta, pase lo que pase en el servidor.
        if (!PERMITIDOS.has(nodo.component)) {
          ignorados.push(nodo.component);
          continue;
        }
        mapa[nodo.id] = nodo;
      }
      set((s) => {
        const base = s.superficies[surfaceId] ?? superficieVacia(surfaceId);
        return {
          superficieActiva: surfaceId,
          ignorados: ignorados.length ? [...s.ignorados, ...ignorados] : s.ignorados,
          superficies: {
            ...s.superficies,
            [surfaceId]: {
              ...base,
              // Reemplaza el árbol del turno: los componentes que no vienen
              // en este mensaje dejan de existir. Es lo que hace que la
              // superficie se reescriba en lugar de acumular basura.
              componentes: mapa,
              rootId: mapa["root"] ? "root" : null,
            },
          },
        };
      });
      get().trazar(
        "updateComponents",
        `${Object.keys(mapa).length} componentes` +
          (ignorados.length ? ` · ignorados: ${ignorados.join(", ")}` : ""),
      );
      return;
    }

    // -------------------------------------------------------- updateDataModel
    if (esUpdateDataModel(msg)) {
      const { surfaceId, path, value } = msg.updateDataModel;
      set((s) => {
        const base = s.superficies[surfaceId] ?? superficieVacia(surfaceId);
        return {
          superficies: {
            ...s.superficies,
            [surfaceId]: { ...base, datos: escribir(base.datos, path, value) },
          },
        };
      });
      get().trazar("updateDataModel", path);
      return;
    }

    // -------------------------------------------------------------- deleteSurface
    if (esDeleteSurface(msg)) {
      const { surfaceId } = msg.deleteSurface;
      set((s) => {
        const { [surfaceId]: _fuera, ...resto } = s.superficies;
        return {
          superficies: resto,
          superficieActiva: s.superficieActiva === surfaceId ? null : s.superficieActiva,
        };
      });
      get().trazar("deleteSurface", surfaceId);
    }
  },

  escribirLocal: (path, valor) => {
    const sid = get().superficieActiva;
    if (!sid) return;
    set((s) => {
      const base = s.superficies[sid];
      if (!base) return s;
      return {
        superficies: { ...s.superficies, [sid]: { ...base, datos: escribir(base.datos, path, valor) } },
      };
    });
  },

  leerRuta: (path) => {
    const sid = get().superficieActiva;
    if (!sid) return undefined;
    const sup = get().superficies[sid];
    return sup ? leer(sup.datos, path) : undefined;
  },

  emitirAccion: async (nombre, contexto, origenId) => {
    const { sessionId, superficieActiva, trazar, setEstado, setError } = get();
    if (!sessionId) {
      setError("No hay sesión abierta todavía.");
      return;
    }
    if (!superficieActiva) {
      setError("No hay superficie activa para reportar la acción.");
      return;
    }
    trazar("accion -> agente", `${nombre} ${JSON.stringify(contexto ?? {})}`);
    setEstado("pensando");
    try {
      await enviarAccion(
        {
          version: "v0.9",
          session_id: sessionId,
          action: {
            name: nombre,
            surfaceId: superficieActiva,
            sourceComponentId: origenId ?? "desconocido",
            timestamp: new Date().toISOString(),
            context: contexto ?? {},
          },
        },
        manejarEvento,
      );
      setEstado("inactivo");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  },
}));

/** Puente SSE -> store. Lo usan `transport.ts` y los fixtures. */
export function manejarEvento(tipo: string, datos: Record<string, unknown>): void {
  const s = useStore.getState();
  switch (tipo) {
    case "session":
      s.setSession(String(datos.session_id));
      break;
    case "text":
      if (typeof datos.text === "string" && datos.text.trim()) {
        s.agregarChat("agente", datos.text);
      }
      break;
    case "a2ui":
      s.aplicar(datos.message as A2UIMessage);
      break;
    case "tool_call":
      s.trazar(datos.efecto ? "tool (mueve dinero)" : "tool", String(datos.name));
      break;
    case "tool_result":
      s.trazar(datos.ok ? "tool ok" : "tool error", `${datos.name}: ${datos.resumen ?? ""}`);
      break;
    case "render_rechazado":
      s.trazar(
        "blueprint rechazado",
        `intento ${datos.intento}: ${(datos.errores as string[] | undefined)?.[0] ?? ""}`,
      );
      break;
    case "warning":
      s.trazar("aviso", String(datos.mensaje ?? JSON.stringify(datos.avisos ?? "")));
      break;
    case "error":
      s.setError(String(datos.mensaje ?? "error desconocido"));
      break;
    case "done":
      s.trazar("turno listo", `turno ${datos.turno} · render_ok=${datos.render_ok}`);
      s.setEstado("inactivo");
      break;
    default:
      s.trazar(tipo, JSON.stringify(datos));
  }
}
