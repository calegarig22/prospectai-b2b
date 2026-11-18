"""Preferências duráveis POR EMPRESA (ex.: o template de e-mail de cada usuário)."""

from __future__ import annotations

from datetime import datetime

from .db import Conn


def get(c: Conn, org_id: str, key: str, default: str = "") -> str:
    r = c.one(f"SELECT value FROM app_settings WHERE org_id = {c.ph} AND key = {c.ph}",
              (org_id, key))
    return r[0] if r and r[0] is not None else default


def put(c: Conn, org_id: str, key: str, value: str) -> None:
    c.run(f"INSERT INTO app_settings (org_id, key, value, updated_at) "
          f"VALUES ({c.ph}, {c.ph}, {c.ph}, {c.ph}) ON CONFLICT (org_id, key) DO UPDATE "
          f"SET value = excluded.value, updated_at = excluded.updated_at",
          (org_id, key, value, datetime.now().isoformat(timespec="seconds")))
