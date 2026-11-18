"""Lotes de leads, SEMPRE escopados por empresa (e por dono, para vendedor).

O banco é a única fonte (não há disco persistente) e toda consulta carrega o
``org_id`` da sessão — inclusive as do admin.
"""

from __future__ import annotations

import io
import re
from datetime import datetime

from fastapi import HTTPException, status
from openpyxl import Workbook
from openpyxl.styles import Font

from app import db, leads, planos
from app.excel_writer import _neutraliza_formulas
from app.models import EXCEL_COLUMNS_HOT

from .plan import PlanCtx
from .security import Ctx

LOTE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}$")

# Colunas que só existem em planos com o recurso. Cortadas no SERVIDOR (tela e
# planilha): o que o plano não inclui não sai da API.
_COLS_POR_RECURSO = {"porte": ("Porte", "Situação", "Desde"), "linkedin": ("LinkedIn",)}
_NOME_RECURSO = {"porte": "Porte e situação na Receita",
                 "linkedin": "LinkedIn da empresa"}


def valida_id(lote: str) -> str:
    if not LOTE_RE.match(lote or ""):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Lote inválido.")
    return lote


def dentro_do_historico(lote_id: str, plan: PlanCtx) -> bool:
    dias = plan.limite("historico_dias")
    if planos.ilimitado(dias):
        return True
    try:
        d = datetime.strptime(lote_id[:10], "%Y-%m-%d").date()
    except ValueError:
        return True
    return (datetime.now().date() - d).days <= dias


def listar(ctx: Ctx, plan: PlanCtx) -> tuple[list[dict], int]:
    """(lotes visíveis, quantos o plano esconde por idade)."""
    with db.conn() as c:
        todos = leads.lotes(c, ctx.org_id, ctx.owner_filter)
    visiveis = [l for l in todos if dentro_do_historico(l["id"], plan)]
    return visiveis, len(todos) - len(visiveis)


def colunas(plan: PlanCtx) -> list[str]:
    cortadas = {col for rec, cols in _COLS_POR_RECURSO.items() if not plan.tem(rec)
                for col in cols}
    return [c for c in EXCEL_COLUMNS_HOT if c not in cortadas]


def bloqueios(plan: PlanCtx) -> list[dict]:
    return [{"recurso": r, "nome": _NOME_RECURSO[r], "selo": planos.selo_upgrade(r)}
            for r in _COLS_POR_RECURSO if not plan.tem(r)]


def detalhe(ctx: Ctx, plan: PlanCtx, lote: str) -> dict:
    valida_id(lote)
    meta = next((l for l in listar(ctx, plan)[0] if l["id"] == lote), None)
    if meta is None:
        # Mesmo 404 para "não existe", "é de outro dono" e "fora do histórico":
        # a resposta não pode revelar que o lote de outra pessoa existe.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Lote não encontrado.")
    cols = colunas(plan)
    with db.conn() as c:
        rows = [{k: _cell(p.get(k)) for k in cols}
                for p in leads.payloads(c, ctx.org_id, ctx.owner_filter, lote)]
    return {"lote": meta, "columns": cols, "rows": rows, "bloqueios": bloqueios(plan)}


def _cell(v):
    if v is None:
        return ""
    return v if isinstance(v, (int, float)) else str(v)


def leads_para_email(ctx: Ctx, plan: PlanCtx, lote: str | None) -> list[dict]:
    """Payloads completos (com Cargo, para personalizar), sem lote fora do histórico
    e sem empresa repetida entre lotes."""
    if lote:
        valida_id(lote)
    with db.conn() as c:
        itens = leads.payloads(c, ctx.org_id, ctx.owner_filter, lote)
    vistos, out = set(), []
    for it in itens:
        if not dentro_do_historico(it.get("_lote", ""), plan):
            continue
        site = str(it.get("Website", "")).strip().lower()
        if site and site in vistos:
            continue
        vistos.add(site)
        out.append(it)
    return out


def xlsx(detail: dict) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Leads"
    cols = detail["columns"]
    ws.append(cols)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in detail["rows"]:
        ws.append([row.get(c, "") for c in cols])
        _neutraliza_formulas(ws[ws.max_row])     # célula "=..." não vira fórmula no Excel
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
