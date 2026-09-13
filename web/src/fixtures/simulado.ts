// Transporte simulado: reproduce web/src/fixtures/demo.json en lugar de hablar
// con el gateway. Se activa con `?mock=1`.
//
// Para qué sirve:
//   · el renderer se desarrolla sin API key y sin backend corriendo;
//   · si la API se cae en la presentación, la demo sigue (es el video de
//     respaldo, pero interactivo);
//   · los blueprints son los mismos que valida el catálogo en Python, así que
//     si el catálogo cambia, este guion deja de validar y nos enteramos.
//
// Los números NO están escritos a mano: salen de services/ con la semilla fija.

import type { ManejadorDeEvento } from "../transport";
import demo from "./demo.json";

type Evento = { type: string } & Record<string, unknown>;
type Turno = {
  disparador: { tipo: string; name?: string; texto?: string };
  eventos: Evento[];
};

const GUION = demo.turnos as unknown as Turno[];
// Tablero inicial grabado por cliente (scripts/gen_fixtures.py).
const INICIOS = ((demo as unknown as { inicio?: Record<string, Evento[]> }).inicio ?? {});
export const CLIENTES_SIMULADOS = demo.clientes as {
  client_id: string;
  nombre: string;
  segmento: string;
  ingreso_mensual: number;
  perfil_vigente: boolean;
}[];

let cursor = 0;
const SESSION_ID = "ses-simulada";

/** Ritmo: suficiente para que se vea el streaming, no tanto como para aburrir. */
const RETARDO: Record<string, number> = {
  tool_call: 260,
  tool_result: 180,
  text: 140,
  a2ui: 220,
  done: 60,
};

function dormir(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

async function reproducir(turno: Turno, onEvento: ManejadorDeEvento): Promise<void> {
  for (const evento of turno.eventos) {
    await dormir(RETARDO[evento.type] ?? 120);
    onEvento(evento.type, evento);
  }
}

function siguienteTurno(nombreAccion?: string): Turno | null {
  // Primero, el turno que coincide con la acción pedida a partir del cursor:
  // así arrastrar un slider dos veces no adelanta el guion de más.
  if (nombreAccion) {
    for (let i = cursor; i < GUION.length; i++) {
      if (GUION[i]!.disparador.name === nombreAccion) {
        cursor = i + 1;
        return GUION[i]!;
      }
    }
    // `simulate` repetido: vuelve a tocar el último turno de simulación.
    for (let i = GUION.length - 1; i >= 0; i--) {
      if (GUION[i]!.disparador.name === nombreAccion) return GUION[i]!;
    }
    return null;
  }
  if (cursor >= GUION.length) return null;
  return GUION[cursor++]!;
}

export function reiniciarSimulacion(): void {
  cursor = 0;
}

export async function reproducirChatSimulado(
  _cuerpo: { message: string },
  onEvento: ManejadorDeEvento,
): Promise<void> {
  onEvento("session", { session_id: SESSION_ID });
  const turno = siguienteTurno();
  if (!turno) {
    onEvento("text", {
      text:
        "Aquí se acaba el guion grabado. Quita `?mock=1` de la URL para hablar con " +
        "el agente de verdad.",
    });
    onEvento("done", { turno: -1, render_ok: false });
    return;
  }
  await reproducir(turno, onEvento);
}

export async function reproducirInicioSimulado(
  cuerpo: { client_id: string },
  onEvento: ManejadorDeEvento,
): Promise<void> {
  cursor = 0; // sesión nueva, guion desde el principio
  onEvento("session", { session_id: SESSION_ID });
  const eventos = INICIOS[cuerpo.client_id];
  if (!eventos) {
    onEvento("warning", { mensaje: "El guion simulado no trae tablero para este cliente." });
    onEvento("done", { turno: -1, render_ok: false });
    return;
  }
  await reproducir({ disparador: { tipo: "inicio" }, eventos }, onEvento);
}

export async function reproducirAccionSimulada(
  cuerpo: { action: { name: string; context?: Record<string, unknown> } },
  onEvento: ManejadorDeEvento,
): Promise<void> {
  const nombre = cuerpo.action.name;
  if (nombre === "follow_recommendation") {
    // El guion grabado solo recorre una recomendación: invertir el efectivo
    // de Ana, que arranca con el perfilador (el turno 1 del guion).
    const herramienta = cuerpo.action.context?.herramienta_id;
    const turno = herramienta === "perfilador_inversion" ? siguienteTurno() : null;
    if (!turno) {
      onEvento("warning", {
        mensaje:
          "El guion simulado solo recorre la recomendación de invertir de Ana. " +
          "Quita `?mock=1` para seguir esta con el agente.",
      });
      onEvento("done", { turno: -1, render_ok: false });
      return;
    }
    await reproducir(turno, onEvento);
    return;
  }
  const turno = siguienteTurno(nombre);
  if (!turno) {
    onEvento("warning", {
      mensaje: `El guion simulado no tiene un turno para la acción \`${nombre}\`.`,
    });
    onEvento("done", { turno: -1, render_ok: false });
    return;
  }
  await reproducir(turno, onEvento);
}
