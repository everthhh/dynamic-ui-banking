// Transporte al gateway.
//
// SSE sobre POST: `EventSource` solo hace GET y necesitamos mandar cuerpo, así
// que se lee el stream de `fetch` a mano. El parser es tolerante — un evento
// puede llegar partido en dos chunks — porque el agente emite cada mensaje A2UI
// en cuanto cierra, no al final del turno.

export type ManejadorDeEvento = (tipo: string, datos: Record<string, unknown>) => void;

export type ModoTransporte = "gateway" | "simulado";

let modo: ModoTransporte =
  (new URLSearchParams(location.search).get("mock") === "1" ? "simulado" : "gateway");

export function getModo(): ModoTransporte {
  return modo;
}

export function setModo(m: ModoTransporte): void {
  modo = m;
}

async function leerSSE(respuesta: Response, onEvento: ManejadorDeEvento): Promise<void> {
  if (!respuesta.ok) {
    throw new Error(`el gateway respondió ${respuesta.status}: ${await respuesta.text()}`);
  }
  if (!respuesta.body) throw new Error("la respuesta no trae stream");

  const lector = respuesta.body.getReader();
  const decodificador = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await lector.read();
    if (done) break;
    buffer += decodificador.decode(value, { stream: true });

    // Un evento SSE termina en línea en blanco.
    let corte: number;
    while ((corte = buffer.indexOf("\n\n")) !== -1) {
      const bloque = buffer.slice(0, corte);
      buffer = buffer.slice(corte + 2);

      let tipo = "message";
      const datos: string[] = [];
      for (const linea of bloque.split("\n")) {
        if (linea.startsWith("event:")) tipo = linea.slice(6).trim();
        else if (linea.startsWith("data:")) datos.push(linea.slice(5).trim());
        // se ignoran comentarios (`:`) y `id:` — no los usamos
      }
      if (!datos.length) continue;
      try {
        onEvento(tipo, JSON.parse(datos.join("\n")) as Record<string, unknown>);
      } catch {
        onEvento("parse_error", { crudo: datos.join("\n") });
      }
    }
  }
}

export type ChatIn = { message: string; session_id: string | null; client_id: string };

/** Envelope real de client_to_server.json (spec A2UI v0.9) + `session_id` de ruteo. */
export type AccionIn = {
  version: "v0.9";
  session_id: string;
  action: {
    name: string;
    surfaceId: string;
    sourceComponentId: string;
    timestamp: string;
    context: Record<string, unknown>;
  };
};

export async function enviarMensaje(cuerpo: ChatIn, onEvento: ManejadorDeEvento): Promise<void> {
  if (modo === "simulado") {
    const { reproducirChatSimulado } = await import("./fixtures/simulado");
    return reproducirChatSimulado(cuerpo, onEvento);
  }
  const r = await fetch("/chat", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(cuerpo),
  });
  return leerSSE(r, onEvento);
}

export async function enviarAccion(cuerpo: AccionIn, onEvento: ManejadorDeEvento): Promise<void> {
  if (modo === "simulado") {
    const { reproducirAccionSimulada } = await import("./fixtures/simulado");
    return reproducirAccionSimulada(cuerpo, onEvento);
  }
  const r = await fetch("/action", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(cuerpo),
  });
  return leerSSE(r, onEvento);
}

export type ClienteDemo = {
  client_id: string;
  nombre: string;
  segmento: string;
  ingreso_mensual: number;
  perfil_vigente: boolean;
};

export async function listarClientes(): Promise<ClienteDemo[]> {
  if (modo === "simulado") {
    const { CLIENTES_SIMULADOS } = await import("./fixtures/simulado");
    return CLIENTES_SIMULADOS;
  }
  const r = await fetch("/api/clients");
  if (!r.ok) return [];
  const j = (await r.json()) as { clientes: ClienteDemo[] };
  return j.clientes;
}
