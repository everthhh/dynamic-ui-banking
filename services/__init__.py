"""Capa de servicios del banco.

Es la unica superficie que el agente puede tocar. Cada funcion de aqui:

  * valida su entrada y lanza `ServiceError` con un mensaje que el modelo
    pueda leer y corregir (el texto del error es parte del contrato);
  * devuelve solo tipos serializables a JSON;
  * no sabe nada de A2UI, de componentes ni de prompts.

`REGISTRO` es el mapa nombre -> callable del que `agent/tools.py` deriva los
schemas de tools. Agregar una tool es agregar una entrada aqui.
"""

from __future__ import annotations

from typing import Any, Callable

from services import accounts, instruments, orders, portfolio
from services.errors import ServiceError

REGISTRO: dict[str, Callable[..., Any]] = {
    # lectura: core bancario
    "get_client_snapshot": accounts.get_client_snapshot,
    "get_accounts": accounts.get_accounts,
    "get_transactions": accounts.get_transactions,
    "get_spending_summary": accounts.get_spending_summary,
    "get_credit_overview": accounts.get_credit_overview,
    # lectura: inversiones
    "list_instruments": instruments.list_instruments,
    "get_instrument_factsheet": instruments.get_instrument_factsheet,
    "get_issuer_profile": portfolio.get_issuer_profile,
    "get_fund_holdings": portfolio.get_fund_holdings,
    "get_funding_sources": portfolio.get_funding_sources,
    "get_risk_questions": portfolio.get_risk_questions,
    # calculo
    "score_risk_profile": portfolio.score_risk_profile,
    "propose_allocation": portfolio.propose_allocation,
    "simulate_portfolio": portfolio.simulate_portfolio,
    "compare_allocations": portfolio.compare_allocations,
    "check_suitability": portfolio.check_suitability,
    # efecto real
    "place_order": orders.place_order,
    "get_orders": orders.get_orders,
}

# Tools que modifican estado. El agente necesita confirmacion del usuario
# antes de llamarlas, y el gateway las registra en la bitacora aparte.
CON_EFECTO: frozenset[str] = frozenset({"place_order"})

__all__ = ["REGISTRO", "CON_EFECTO", "ServiceError",
           "accounts", "instruments", "orders", "portfolio"]
