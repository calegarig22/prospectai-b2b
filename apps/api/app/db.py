"""Conexão com o banco: Postgres (Neon) com DATABASE_URL, senão SQLite local.

Tudo que fala com o banco — a API e o motor de busca — passa por ``conn()``.
Duas garantias moram aqui:

1. Um POOL de conexões aberto uma vez por processo (o Neon fecha conexões
   ociosas e reconectar a cada requisição custa ~300 ms).
2. A mesma interface (``all``/``one``/``run`` e o placeholder ``ph``) nos dois
   bancos, para as consultas serem escritas uma vez só.

O schema NÃO é criado aqui: ele vem só das migrations versionadas
(``migrations/*.sql``, aplicadas por ``python -m api.migrate``).
"""

from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parent.parent      # apps/api
# Testes apontam para um arquivo temporário com PROSPECT_SQLITE_PATH.
SQLITE_PATH = Path(os.environ.get("PROSPECT_SQLITE_PATH") or (ROOT / "data" / "prospect.db"))

_pool = None
_pool_lock = threading.Lock()


def database_url() -> str:
    return (os.environ.get("DATABASE_URL", "") or "").strip()


def is_postgres() -> bool:
    return bool(database_url())


def pool():
    """Pool psycopg2 compartilhado (None em SQLite)."""
    global _pool
    if not is_postgres():
        return None
    with _pool_lock:
        if _pool is None:
            from psycopg2.pool import ThreadedConnectionPool
            _pool = ThreadedConnectionPool(1, 12, dsn=database_url(), connect_timeout=15)
    return _pool


def close_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.closeall()
            _pool = None


class Conn:
    """Conexão crua com a mesma interface nos dois bancos."""

    def __init__(self, raw, pg: bool) -> None:
        self.raw = raw
        self.pg = pg
        self.ph = "%s" if pg else "?"

    def all(self, sql: str, params: tuple = ()) -> list[tuple]:
        if self.pg:
            with self.raw.cursor() as cur:
                cur.execute(sql, params)
                return cur.fetchall() if cur.description else []
        return self.raw.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple = ()):
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def run(self, sql: str, params: tuple = ()) -> int:
        if self.pg:
            with self.raw.cursor() as cur:
                cur.execute(sql, params)
                return cur.rowcount
        cur = self.raw.execute(sql, params)
        self.raw.commit()
        return cur.rowcount


def _acquire_pg(p):
    """Conexão VIVA do pool (testa com SELECT 1; troca se o Neon a derrubou)."""
    raw = p.getconn()
    try:
        raw.autocommit = True
        with raw.cursor() as cur:
            cur.execute("SELECT 1")
        return raw
    except Exception:  # noqa: BLE001 - conexão morta -> descarta e pega outra
        try:
            p.putconn(raw, close=True)
        except Exception:  # noqa: BLE001
            pass
        raw = p.getconn()
        raw.autocommit = True
        return raw


@contextmanager
def conn() -> Iterator[Conn]:
    p = pool()
    if p is not None:
        raw = _acquire_pg(p)         # valida a conexão (o Neon derruba as ociosas)
        try:
            yield Conn(raw, True)
        finally:
            p.putconn(raw)
        return
    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(str(SQLITE_PATH), timeout=15)
    raw.execute("PRAGMA foreign_keys = ON")
    try:
        yield Conn(raw, False)
    finally:
        raw.close()
