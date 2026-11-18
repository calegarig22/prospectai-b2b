"""Registro de atividade POR EMPRESA (quem fez o quê e quando).

Nunca derruba a ação principal: falha de auditoria só vai para o log.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from .db import Conn

log = logging.getLogger("prospectai")


def registrar(c: Conn, org_id: str, user: dict | None, action: str, detail: str = "") -> None:
    u = user or {}
    try:
        c.run(f"INSERT INTO audit_log (id, org_id, ts, user_id, user_name, action, detail) "
              f"VALUES ({', '.join([c.ph] * 7)})",
              (uuid.uuid4().hex, org_id, datetime.now().isoformat(timespec="seconds"),
               u.get("id", ""), u.get("name") or u.get("email") or "—", action, detail[:500]))
    except Exception:  # noqa: BLE001 - auditoria não pode derrubar o app
        log.exception("Falha ao registrar auditoria (%s)", action)


def recentes(c: Conn, org_id: str, limit: int = 200, user_id: str | None = None) -> list[dict]:
    sql = f"SELECT ts, user_name, action, detail FROM audit_log WHERE org_id = {c.ph}"
    params: tuple = (org_id,)
    if user_id:
        sql += f" AND user_id = {c.ph}"
        params += (user_id,)
    rows = c.all(sql + f" ORDER BY ts DESC LIMIT {int(limit)}", params)
    return [{"ts": r[0] or "", "user": r[1] or "", "action": r[2] or "", "detail": r[3] or ""}
            for r in rows]
