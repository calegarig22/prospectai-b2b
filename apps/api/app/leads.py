"""Leads gerados, SEMPRE por empresa (org_id obrigatório em toda função).

``owner_id`` opcional restringe ao dono (vendedor vê só os seus); o admin passa
``None`` e vê os da empresa inteira — nunca os de outra empresa.
"""

from __future__ import annotations

import json

from .db import Conn
from .models import HotLead
from .utils import normalize_domain


def _escopo(c: Conn, org_id: str, owner_id: str | None) -> tuple[str, tuple]:
    if not org_id:
        raise ValueError("org_id é obrigatório")      # nunca consultar sem empresa
    clause, params = f" org_id = {c.ph}", (org_id,)
    if owner_id:
        clause += f" AND owner_id = {c.ph}"
        params += (owner_id,)
    return clause, params


def dominios_vistos(c: Conn, org_id: str) -> set[str]:
    clause, params = _escopo(c, org_id, None)
    return {r[0] for r in c.all(f"SELECT website FROM leads WHERE{clause}", params)}


def gravar(c: Conn, org_id: str, leads: list[HotLead], now: str, lote: str,
           gen_seconds: float = 0.0, device: str = "", region: str = "",
           owner_id: str = "") -> int:
    """Grava o lote. Em conflito (lead já visto pela MESMA empresa) refresca os
    dados, mas mantém lote, dono e data de entrada originais."""
    if not org_id:
        raise ValueError("org_id é obrigatório")
    sql = (f"INSERT INTO leads (org_id, website, company, first_seen, last_seen, score, lote, "
           f"payload, gen_seconds, device, region, owner_id, generated_by) "
           f"VALUES ({', '.join([c.ph] * 13)}) "
           f"ON CONFLICT (org_id, website) DO UPDATE SET last_seen = excluded.last_seen, "
           f"score = excluded.score, company = excluded.company, payload = excluded.payload")
    n = 0
    for lead in leads:
        domain = normalize_domain(lead.website)
        if not domain:
            continue
        payload = json.dumps(lead.to_row(), ensure_ascii=False)
        c.run(sql, (org_id, domain, lead.company, now, now, int(lead.score), lote, payload,
                    float(gen_seconds), device, region, owner_id or None, owner_id or None))
        n += 1
    return n


def leads_desde(c: Conn, org_id: str, data_iso: str) -> int:
    """Leads que ENTRARAM a partir de uma data — base da cota mensal."""
    clause, params = _escopo(c, org_id, None)
    r = c.one(f"SELECT COUNT(*) FROM leads WHERE{clause} AND first_seen >= {c.ph}",
              params + (data_iso,))
    return int(r[0]) if r else 0


def lotes(c: Conn, org_id: str, owner_id: str | None) -> list[dict]:
    clause, params = _escopo(c, org_id, owner_id)
    rows = c.all(f"SELECT lote, COUNT(*), MIN(first_seen), MAX(gen_seconds), MAX(device), "
                 f"MAX(region) FROM leads WHERE{clause} GROUP BY lote "
                 f"ORDER BY MIN(first_seen) DESC", params)
    return [{"id": r[0], "count": int(r[1]), "created_at": r[2] or "",
             "gen_seconds": float(r[3] or 0), "device": r[4] or "", "region": r[5] or ""}
            for r in rows]


def payloads(c: Conn, org_id: str, owner_id: str | None, lote: str | None = None) -> list[dict]:
    clause, params = _escopo(c, org_id, owner_id)
    if lote:
        clause += f" AND lote = {c.ph}"
        params += (lote,)
    out = []
    for payload, lote_id in c.all(f"SELECT payload, lote FROM leads WHERE{clause} "
                                  f"ORDER BY score DESC", params):
        try:
            item = json.loads(payload or "")
        except ValueError:
            continue
        if isinstance(item, dict):
            item["_lote"] = lote_id
            out.append(item)
    return out


def lotes_admin(c: Conn, org_id: str) -> list[dict]:
    clause, params = _escopo(c, org_id, None)
    rows = c.all(f"SELECT lote, MAX(generated_by), COUNT(*), MIN(first_seen), MAX(device), "
                 f"MAX(owner_id) FROM leads WHERE{clause} GROUP BY lote "
                 f"ORDER BY MIN(first_seen) DESC", params)
    return [{"id": r[0], "generated_by": r[1] or "", "count": int(r[2]), "created_at": r[3] or "",
             "device": r[4] or "", "owner_id": r[5] or ""} for r in rows]


def atribuir_lote(c: Conn, org_id: str, lote: str, user_id: str) -> int:
    clause, params = _escopo(c, org_id, None)
    return c.run(f"UPDATE leads SET owner_id = {c.ph} WHERE{clause} AND lote = {c.ph}",
                 (user_id,) + params + (lote,))
