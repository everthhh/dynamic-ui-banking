"""Acceso a la base simulada del banco.

Un solo punto de entrada: `connect()`. Nadie mas en el repo abre un sqlite3
directo, para que cambiar de SQLite a Postgres sea tocar este archivo.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("BANK_DB_PATH", ROOT / "data" / "bank.sqlite"))
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
SERIES_PARQUET = ROOT / "data" / "series.parquet"

# Semilla fija: el seed es reproducible byte a byte. Si alguien cambia esto,
# los numeros del demo cambian y el guion deja de cuadrar.
SEED = 20260912


def _row_to_dict(cursor: sqlite3.Cursor, row: tuple) -> dict[str, Any]:
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def connect(path: Path | None = None, *, readonly: bool = False) -> sqlite3.Connection:
    """Conexion con foreign keys activas y filas como dict."""
    target = Path(path or DB_PATH)
    if readonly:
        if not target.exists():
            raise FileNotFoundError(
                f"No existe {target}. Corre `make seed` para generar la base simulada."
            )
        conn = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(target)
    conn.row_factory = _row_to_dict
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session(path: Path | None = None, *, readonly: bool = False) -> Iterator[sqlite3.Connection]:
    conn = connect(path, readonly=readonly)
    try:
        yield conn
        if not readonly:
            conn.commit()
    except Exception:
        if not readonly:
            conn.rollback()
        raise
    finally:
        conn.close()


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


def reset(path: Path | None = None) -> Path:
    """Borra y recrea la base vacia. Devuelve la ruta."""
    target = Path(path or DB_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(target) + suffix)
        if candidate.exists():
            candidate.unlink()
    with session(target) as conn:
        init_schema(conn)
    return target


def query(conn: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> list[dict[str, Any]]:
    return conn.execute(sql, params).fetchall()


def query_one(conn: sqlite3.Connection, sql: str, params: tuple | dict = ()) -> dict[str, Any] | None:
    rows = conn.execute(sql, params).fetchall()
    return rows[0] if rows else None
