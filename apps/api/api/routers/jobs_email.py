"""Acompanhamento de tarefas e disparo de e-mail."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status

from app import audit, db

from .. import email_service, jobs
from ..plan import load as load_plan
from ..schemas import EmailJobIn, JobOut, Msg, SelectionIn, SelectionOut, TemplateIn, TemplateOut
from ..security import Ctx, require_member

router = APIRouter(tags=["jobs", "email"])


@router.get("/jobs/active", response_model=JobOut | None)
def ativo(kind: Literal["discover", "email"], ctx: Ctx = Depends(require_member)):
    """Tarefa em andamento do usuário — o front retoma o acompanhamento após recarregar."""
    job = jobs.latest_active(ctx, kind)
    return jobs.public(job) if job else None


@router.get("/jobs/{job_id}", response_model=JobOut)
def ver(job_id: str, ctx: Ctx = Depends(require_member)):
    return jobs.public(jobs.get_for(ctx, job_id))


@router.post("/email/selection", response_model=SelectionOut)
def selecao(body: SelectionIn, ctx: Ctx = Depends(require_member)):
    sel = email_service.selection(ctx, load_plan(ctx.org_id), body.lote, body.classes)
    return {k: v for k, v in sel.items() if not k.startswith("_")}


@router.post("/jobs/email", response_model=JobOut, status_code=202)
def disparar(body: EmailJobIn, ctx: Ctx = Depends(require_member)):
    if not body.confirmar:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Confirme o envio.")
    job = jobs.start_email(ctx, load_plan(ctx.org_id), body.lote, list(body.classes))
    return jobs.public(job)


@router.get("/email/template", response_model=TemplateOut)
def template(ctx: Ctx = Depends(require_member)):
    html, origem = email_service.preview(ctx)
    return {"origem": origem, "preview_html": html, "campos": email_service.CAMPOS}


@router.put("/email/template", response_model=Msg)
def salvar_template(body: TemplateIn, ctx: Ctx = Depends(require_member)):
    email_service.set_user_html(ctx, body.html)
    with db.conn() as c:
        audit.registrar(c, ctx.org_id, ctx.as_user(), "Trocou o template de e-mail")
    return {"detail": "Template atualizado."}


@router.delete("/email/template", response_model=Msg)
def voltar_padrao(ctx: Ctx = Depends(require_member)):
    email_service.set_user_html(ctx, "")
    return {"detail": "Voltou ao modelo padrão."}
