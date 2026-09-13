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

from services import (accounts, banking, credit, instruments, movements, orders,
                      payments, portfolio, profile)
from services.errors import ServiceError

REGISTRO: dict[str, Callable[..., Any]] = {
    # lectura: core bancario
    "get_client_snapshot": accounts.get_client_snapshot,
    "get_accounts": accounts.get_accounts,
    "get_transactions": accounts.get_transactions,
    "get_spending_summary": accounts.get_spending_summary,
    "get_credit_overview": accounts.get_credit_overview,
    # lectura: perfil financiero, base de toda recomendacion
    "get_financial_profile": profile.get_financial_profile,
    "get_recommendations": profile.get_recommendations,
    # lectura: banca personal (busqueda, presupuestos y alertas)
    "search_transactions": accounts.search_transactions,
    "get_budgets": accounts.get_budgets,
    "get_spending_alerts": accounts.get_spending_alerts,
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
    "simulate_debt_payoff": credit.simulate_debt_payoff,
    # efecto: banca personal (no mueven dinero, pero cambian estado)
    "block_card": banking.block_card,
    "unblock_card": banking.unblock_card,
    "set_card_limit": banking.set_card_limit,
    "set_card_alias": banking.set_card_alias,
    "set_account_alias": banking.set_account_alias,
    "set_budget": banking.set_budget,
    # efecto real: inversiones
    "place_order": orders.place_order,
    "get_orders": orders.get_orders,
    # lectura: pagos
    "get_bills": payments.get_bills,
    "get_billers": payments.get_billers,
    "get_beneficiaries": payments.get_beneficiaries,
    "get_payment_history": payments.get_payment_history,
    "get_received_money": payments.get_received_money,
    "get_deposit_options": payments.get_deposit_options,
    # efecto: pagos que preparan pero no mueven dinero
    "register_service": movements.register_service,
    "save_beneficiary": movements.save_beneficiary,
    "create_deposit_reference": movements.create_deposit_reference,
    # efecto real: pagos. Los tres primeros solo registran (paso 1); el dinero
    # se mueve en `confirm_payment` (paso 2) o regresa en `cancel_payment`.
    "pay_service": movements.pay_service,
    "transfer_money": movements.transfer_money,
    "withdraw_cash": movements.withdraw_cash,
    "confirm_payment": movements.confirm_payment,
    "cancel_payment": movements.cancel_payment,
}
# `movements.liquidar_deposito_en_efectivo` NO va aquí, a propósito: acreditar
# un depósito en efectivo lo dispara el corresponsal, no el agente (ver
# scripts/simular_deposito.py). Ninguna tool puede crear dinero.

# Tools que modifican estado. Solo `place_order` y los pagos mueven dinero y
# llevan el candado de dos pasos; las demás (tarjetas, alias, presupuestos,
# servicios, contactos, referencias) se llaman directo, pero el front las marca
# distinto en la traza.
CON_EFECTO: frozenset[str] = frozenset({
    "place_order",
    "block_card", "unblock_card", "set_card_limit", "set_card_alias",
    "set_account_alias", "set_budget",
    "register_service", "save_beneficiary", "create_deposit_reference",
    "pay_service", "transfer_money", "withdraw_cash", "confirm_payment", "cancel_payment",
})

__all__ = ["REGISTRO", "CON_EFECTO", "ServiceError",
           "accounts", "banking", "credit", "instruments", "movements", "orders",
           "payments", "portfolio", "profile"]
