// Tipos de los CUATRO mensajes de servidor->cliente del spec A2UI v0.9
// (createSurface, updateComponents, updateDataModel, deleteSurface). Los tipos
// de los COMPONENTES no van aquí: se generan desde a2ui/catalog.json (ver
// catalog.types.ts).
//
// `action` NO es uno de estos cuatro: en el spec (client_to_server.json) es el
// mensaje que el CLIENTE manda de vuelta al agente, nunca al revés. Por eso no
// hay `ActionMsg` en esta unión — ver `AccionSaliente` en transport.ts.

import type { A2UIAction } from "./catalog.types";

export type ComponentNode = {
  id: string;
  component: string;
  children?: string[];
  [prop: string]: unknown;
};

export type CreateSurfaceMsg = {
  version: "v0.9";
  createSurface: {
    surfaceId: string;
    catalogId: string;
    theme?: Record<string, string | number>;
  };
};

export type UpdateComponentsMsg = {
  version: "v0.9";
  updateComponents: { surfaceId: string; components: ComponentNode[] };
};

export type UpdateDataModelMsg = {
  version: "v0.9";
  updateDataModel: { surfaceId: string; path: string; value: unknown };
};

export type DeleteSurfaceMsg = {
  version: "v0.9";
  deleteSurface: { surfaceId: string };
};

export type A2UIMessage =
  | CreateSurfaceMsg
  | UpdateComponentsMsg
  | UpdateDataModelMsg
  | DeleteSurfaceMsg;

export function esCreateSurface(m: A2UIMessage): m is CreateSurfaceMsg {
  return "createSurface" in m;
}
export function esUpdateComponents(m: A2UIMessage): m is UpdateComponentsMsg {
  return "updateComponents" in m;
}
export function esUpdateDataModel(m: A2UIMessage): m is UpdateDataModelMsg {
  return "updateDataModel" in m;
}
export function esDeleteSurface(m: A2UIMessage): m is DeleteSurfaceMsg {
  return "deleteSurface" in m;
}

/** Desenvuelve el prop `action` de un componente: `{event: {name, context}}`. */
export function leerAccion(
  action: A2UIAction | undefined,
): { name: A2UIAction["event"]["name"]; context: Record<string, unknown> } | null {
  if (!action?.event?.name) return null;
  return { name: action.event.name, context: action.event.context ?? {} };
}

/** Un binding: `{"path": "/sim/escenarios"}`. */
export type Binding = { path: string };

export function esBinding(v: unknown): v is Binding {
  return (
    typeof v === "object" &&
    v !== null &&
    !Array.isArray(v) &&
    Object.keys(v).length === 1 &&
    typeof (v as Binding).path === "string"
  );
}

export type { A2UIAction };
