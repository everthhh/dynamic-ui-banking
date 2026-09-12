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

export async function reproducirAccionSimulada(
  cuerpo: { name: string },
  onEvento: ManejadorDeEvento,
): Promise<void> {
  const turno = siguienteTurno(cuerpo.name);
  if (!turno) {
    onEvento("warning", {
      mensaje: `El guion simulado no tiene un turno para la acción \`${cuerpo.name}\`.`,
    });
    onEvento("done", { turno: -1, render_ok: false });
    return;
  }
  await reproducir(turno, onEvento);
}
