// Tipos de los cuatro mensajes A2UI v0.9. Los tipos de los COMPONENTES no van
// aquí: se generan desde a2ui/catalog.json (ver catalog.types.ts).

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

export type ActionMsg = {
  version: "v0.9";
  action: { name: string; surfaceId?: string; context?: Record<string, unknown> };
};

export type A2UIMessage =
  | CreateSurfaceMsg
  | UpdateComponentsMsg
  | UpdateDataModelMsg
  | ActionMsg;

export function esCreateSurface(m: A2UIMessage): m is CreateSurfaceMsg {
  return "createSurface" in m;
}
export function esUpdateComponents(m: A2UIMessage): m is UpdateComponentsMsg {
  return "updateComponents" in m;
}
export function esUpdateDataModel(m: A2UIMessage): m is UpdateDataModelMsg {
  return "updateDataModel" in m;
}
export function esAction(m: A2UIMessage): m is ActionMsg {
  return "action" in m;
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
