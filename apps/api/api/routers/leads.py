"""Lotes e leads do usuário logado (vendedor: os seus; admin: os da empresa)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response

from app import db, orgs
from app.regions import CONTINENTS, WORLD

from .. import jobs, lotes
from ..plan import load as load_plan, matriz
from ..schemas import DiscoverIn, JobOut, LoteDetail, LotesOut, MetaOut
from ..security import Ctx, require_member

router = APIRouter(tags=["leads"])


@router.get("/meta", response_model=MetaOut)
def meta(ctx: Ctx = Depends(require_member)):
    """Dados de tela que dependem do nicho DA EMPRESA (nomes curtos das soluções)."""
    with db.conn() as c:
        n = orgs.nicho_de(c, ctx.org_id)
    return {"regions": list(CONTINENTS.keys()), "world": WORLD, "plans": matriz(),
            "nicho_nome": n.nome, "porte_rotulo": n.porte.rotulo,
            "solucoes": [{"nome": s.nome, "curto": s.curto} for s in n.solucoes]}


@router.get("/lotes", response_model=LotesOut)
def listar(ctx: Ctx = Depends(require_member)):
    plan = load_plan(ctx.org_id)
    visiveis, ocultos = lotes.listar(ctx, plan)
    return {"lotes": visiveis, "ocultos_por_plano": ocultos,
            "historico_dias": plan.limite("historico_dias")}


@router.get("/lotes/{lote}", response_model=LoteDetail)
def detalhe(lote: str, ctx: Ctx = Depends(require_member)):
    return lotes.detalhe(ctx, load_plan(ctx.org_id), lote)


@router.get("/lotes/{lote}/xlsx", response_class=Response,
            responses={200: {"content": {"application/vnd.openxmlformats-officedocument."
                                         "spreadsheetml.sheet": {}}}})
def baixar(lote: str, ctx: Ctx = Depends(require_member)):
    data = lotes.xlsx(lotes.detalhe(ctx, load_plan(ctx.org_id), lote))
    return Response(data, media_type="application/vnd.openxmlformats-officedocument."
                                      "spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="lote_{lote}.xlsx"',
                             "Cache-Control": "no-store"})


@router.post("/jobs/discover", response_model=JobOut, status_code=202)
def gerar(body: DiscoverIn, request: Request, ctx: Ctx = Depends(require_member)):
    job = jobs.start_discover(ctx, load_plan(ctx.org_id), body.quantidade, body.regiao,
                              body.so_com_contato, request.headers.get("user-agent", ""))
    return jobs.public(job)
