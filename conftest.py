"""Configuracion de pytest para todo el repo.

Los tests NO tocan `data/bank.sqlite`. Se genera una base nueva en un
directorio temporal al arrancar la sesion de pruebas y se apunta `bank.db`
ahi. Asi los tests que ejecutan ordenes (que si mueven saldos) son
reproducibles y no dejan basura en la base del demo.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def base_de_pruebas(tmp_path_factory: pytest.TempPathFactory) -> Path:
    from bank import db, seed

    destino = tmp_path_factory.mktemp("bank") / "bank.sqlite"
    os.environ["BANK_DB_PATH"] = str(destino)
    db.DB_PATH = destino
    seed.construir(destino)

    problemas = seed.verificar(destino)
    assert not problemas, f"la base de pruebas nació mal: {problemas}"
    return destino
