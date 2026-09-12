// Registry: id del catálogo -> componente React.
//
// Es la allowlist ejecutable. Si un id no está aquí, no existe para el
// renderer, y el test de abajo (web/src/registry.check.ts, que corre en el
// typecheck) garantiza que el registry y el catálogo tengan exactamente las
// mismas llaves.

import type { ComponentType } from "react";
import { AllocationDonut } from "./components/AllocationDonut";
import { AmountSlider } from "./components/AmountSlider";
import { ComparePanel } from "./components/ComparePanel";
import { FactSheet, SpendingBreakdown } from "./components/FactSheet";
import { OrderTicket } from "./components/OrderTicket";
import { ProjectionChart } from "./components/ProjectionChart";
import { RiskProfiler } from "./components/RiskProfiler";
import {
  Badge,
  Button,
  Card,
  Column,
  Divider,
  Row,
  Stat,
  Text,
} from "./components/primitives";
import { InstrumentTable, PositionsTable } from "./components/tablas";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type ComponenteDelCatalogo = ComponentType<any>;

export const REGISTRY: Record<string, ComponenteDelCatalogo> = {
  // primitivos
  Column,
  Row,
  Card,
  Text,
  Divider,
  Button,
  Badge,
  Stat,
  // dominio
  "inv.RiskProfiler": RiskProfiler,
  "inv.AllocationDonut": AllocationDonut,
  "inv.ProjectionChart": ProjectionChart,
  "inv.InstrumentTable": InstrumentTable,
  "inv.ComparePanel": ComparePanel,
  "inv.AmountSlider": AmountSlider,
  "inv.OrderTicket": OrderTicket,
  "inv.FactSheet": FactSheet,
  "inv.PositionsTable": PositionsTable,
  "inv.SpendingBreakdown": SpendingBreakdown,
};
