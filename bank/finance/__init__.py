"""Motor financiero determinista.

Regla del proyecto: el modelo de lenguaje no hace aritmetica. Todo numero que
llega a la pantalla sale de aqui, y dos llamadas con la misma entrada dan
exactamente el mismo resultado (las simulaciones derivan su semilla de los
argumentos, no del reloj).
"""

from bank.finance import compare, montecarlo, rules, risk  # noqa: F401
