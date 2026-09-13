"""Simula que un corresponsal (OXXO, 7-Eleven...) confirma un depósito en efectivo.

    python -m scripts.simular_deposito <referencia> <monto>

No es una tool y no pasa por el servidor MCP, a propósito: acreditar dinero que
llega de fuera del banco no es algo que el agente pueda pedir. En la vida real
lo dispara la red del corresponsal cuando el cliente paga en caja; en el demo,
esta línea de comandos. Escribe en la misma base que usa `mcp_server/`
(`BANK_DB_PATH`, o `data/bank.sqlite` por omisión).
"""

from __future__ import annotations

import argparse
import json

from services.errors import ServiceError
from services.movements import liquidar_deposito_en_efectivo


def main() -> int:
    ap = argparse.ArgumentParser(description="Acredita un depósito en efectivo por su referencia.")
    ap.add_argument("referencia", help="La referencia de 16 dígitos que generó la app.")
    ap.add_argument("monto", type=float, help="Lo que el cliente pagó en caja.")
    args = ap.parse_args()
    try:
        resultado = liquidar_deposito_en_efectivo(args.referencia, args.monto)
    except ServiceError as exc:
        print(f"No se acreditó: {exc}")
        return 1
    print(json.dumps(resultado, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
