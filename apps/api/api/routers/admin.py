"""Administração da PRÓPRIA empresa: usuários, lotes, remetentes e atividade.

Tudo exige papel admin e é escopado pelo ``org_id`` da sessão: um id de
usuário, lote ou remetente de OUTRA empresa responde 404, como se não existisse.
O plano é só leitura aqui — quem muda plano é o dono da plataforma.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app import audit, db, email_senders, leads, planos, secret_box, users

from .. import lotes
from ..plan import load as load_plan, matriz
from ..schemas import (AdminLote, AssignIn, AuditEntry, Msg, PlanAdminOut, SenderIn,
                       SendersOut, UserCreateIn, UserPatchIn, UsersOut)
from ..security import Ctx, require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


def _audit(c, ctx: Ctx, action: str, detail: str = "") -> None:
    audit.registrar(c, ctx.org_id, ctx.as_user(), action, detail)


def _user_da_empresa(c, ctx: Ctx, user_id: str) -> dict:
    u = users.get_in_org(c, ctx.org_id, user_id)
    if not u:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Usuário não encontrado.")
    return u


def _admins_ativos(c, ctx: Ctx) -> int:
    return sum(1 for x in users.list_users(c, ctx.org_id) if x["role"] == "admin" and x["active"])


@router.get("/plan", response_model=PlanAdminOut)
def ver_plano(ctx: Ctx = Depends(require_admin)):
    p = load_plan(ctx.org_id)
    return {"matriz": matriz(), "contratado": p.contratado, "efetivo": p.efetivo,
            "trial_ate": p.trial_ate, "em_teste": p.em_teste}


# ------------------------------------------------------------------- usuários
@router.get("/users", response_model=UsersOut)
def listar_usuarios(ctx: Ctx = Depends(require_admin)):
    with db.conn() as c:
        lista = users.list_users(c, ctx.org_id)
        com_remetente = set(email_senders.todos(c, ctx.org_id))
    teto = load_plan(ctx.org_id).limite("usuarios")
    return {
        "users": [{**{k: u[k] for k in ("id", "email", "name", "role", "active", "created_at")},
                   "has_sender": u["id"] in com_remetente} for u in lista],
        "limite": teto, "ilimitado": planos.ilimitado(teto), "total": len(lista),
        "ativos": sum(1 for u in lista if u["active"]),
        "admins": sum(1 for u in lista if u["role"] == "admin" and u["active"]),
    }


@router.post("/users", response_model=Msg, status_code=201)
def criar_usuario(body: UserCreateIn, ctx: Ctx = Depends(require_admin)):
    with db.conn() as c:
        try:   # o teto do plano é conferido DENTRO do create_user
            users.create_user(c, ctx.org_id, body.email, body.password, name=body.name,
                              role=body.role)
        except ValueError as erro:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))
        _audit(c, ctx, "Criou usuário", f"{body.email} ({body.role})")
    return {"detail": "Usuário criado."}


@router.patch("/users/{user_id}", response_model=Msg)
def editar_usuario(user_id: str, body: UserPatchIn, ctx: Ctx = Depends(require_admin)):
    with db.conn() as c:
        u = _user_da_empresa(c, ctx, user_id)
        ultimo_admin = u["role"] == "admin" and u["active"] and _admins_ativos(c, ctx) <= 1
        if ultimo_admin and ((body.role and body.role != "admin") or body.active is False):
            raise HTTPException(status.HTTP_409_CONFLICT,
                                "Não dá para rebaixar ou desativar o último admin ativo.")
        if body.active is False and u["id"] == ctx.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "Você não pode desativar a si mesmo.")
        mudou = []
        try:
            if body.role and body.role != u["role"]:
                users.set_role(c, ctx.org_id, u["id"], body.role); mudou.append("papel")
            if body.name is not None and body.name.strip() != u["name"].strip():
                users.set_name(c, ctx.org_id, u["id"], body.name); mudou.append("nome")
            if body.password:
                users.set_password(c, ctx.org_id, u["id"], body.password); mudou.append("senha")
            if body.active is not None and body.active != u["active"]:
                users.set_active(c, ctx.org_id, u["id"], body.active)
                mudou.append("ativado" if body.active else "desativado")
        except ValueError as erro:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))
        if mudou:
            _audit(c, ctx, "Editou usuário", f"{u['email']}: {', '.join(mudou)}")
    return {"detail": "Alterações salvas." if mudou else "Nenhuma alteração."}


@router.delete("/users/{user_id}", response_model=Msg)
def remover_usuario(user_id: str, ctx: Ctx = Depends(require_admin)):
    with db.conn() as c:
        u = _user_da_empresa(c, ctx, user_id)
        if u["id"] == ctx.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "Você não pode remover a si mesmo.")
        if u["role"] == "admin" and u["active"] and _admins_ativos(c, ctx) <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "Não dá para remover o último admin ativo.")
        email_senders.remover(c, ctx.org_id, u["id"])
        users.delete_user(c, ctx.org_id, u["id"])
        _audit(c, ctx, "Removeu usuário", u["email"])
    return {"detail": "Usuário removido."}


# ---------------------------------------------------------------------- lotes
@router.get("/lotes", response_model=list[AdminLote])
def lotes_da_empresa(ctx: Ctx = Depends(require_admin)):
    with db.conn() as c:
        nomes = {u["id"]: (u["name"] or u["email"]) for u in users.list_users(c, ctx.org_id)}
        rows = leads.lotes_admin(c, ctx.org_id)
    return [{"id": r["id"], "count": r["count"], "created_at": r["created_at"],
             "device": r["device"],
             "generated_by_name": nomes.get(r["generated_by"], "— (sem dono)"),
             "owner_id": r["owner_id"], "owner_name": nomes.get(r["owner_id"], "— (sem dono)")}
            for r in rows]


@router.post("/lotes/{lote}/owner", response_model=Msg)
def atribuir_lote(lote: str, body: AssignIn, ctx: Ctx = Depends(require_admin)):
    lotes.valida_id(lote)
    with db.conn() as c:
        alvo = _user_da_empresa(c, ctx, body.user_id)
        if not alvo["active"] or alvo["role"] != "vendedor":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Escolha um vendedor ativo.")
        n = leads.atribuir_lote(c, ctx.org_id, lote, alvo["id"])
        if not n:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Lote não encontrado.")
        nome = alvo["name"] or alvo["email"]
        _audit(c, ctx, "Atribuiu lote", f"{lote} ({n}) -> {nome}")
    return {"detail": f"{n} lead(s) atribuído(s) a {nome}."}


# ----------------------------------------------------------------- remetentes
@router.get("/senders", response_model=SendersOut)
def remetentes(ctx: Ctx = Depends(require_admin)):
    with db.conn() as c:
        todos = email_senders.todos(c, ctx.org_id)
        lista = users.list_users(c, ctx.org_id)
    out = []
    for u in lista:
        cfg = todos.get(u["id"]) or {}
        out.append({"user_id": u["id"], "user_name": u["name"] or u["email"],
                    "user_email": u["email"], "configured": bool(cfg.get("from_email")),
                    "from_email": cfg.get("from_email", ""), "from_name": cfg.get("from_name", ""),
                    "smtp_host": cfg.get("smtp_host", "smtp.gmail.com"),
                    "smtp_port": int(cfg.get("smtp_port") or 587),
                    "has_password": bool(cfg.get("has_password"))})   # a senha NUNCA sai
    return {"encryption_available": secret_box.available(), "senders": out}


@router.put("/senders/{user_id}", response_model=Msg)
def salvar_remetente(user_id: str, body: SenderIn, ctx: Ctx = Depends(require_admin)):
    with db.conn() as c:
        u = _user_da_empresa(c, ctx, user_id)
        if not secret_box.available():
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                                "Sem EMAIL_ENC_KEY no servidor não dá para guardar a senha com segurança.")
        try:
            email_senders.salvar(c, ctx.org_id, u["id"], body.from_email, body.from_name,
                                 body.smtp_host, body.smtp_port, (body.smtp_password or "").strip())
        except ValueError as erro:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))
        _audit(c, ctx, "Configurou remetente", u["email"])
    return {"detail": f"Remetente de {u['email']} salvo."}


@router.delete("/senders/{user_id}", response_model=Msg)
def remover_remetente(user_id: str, ctx: Ctx = Depends(require_admin)):
    with db.conn() as c:
        u = _user_da_empresa(c, ctx, user_id)
        email_senders.remover(c, ctx.org_id, u["id"])
        _audit(c, ctx, "Removeu remetente", u["email"])
    return {"detail": "Remetente removido."}


# ------------------------------------------------------------------- atividade
@router.get("/audit", response_model=list[AuditEntry])
def atividade(user_id: str | None = None, ctx: Ctx = Depends(require_admin)):
    with db.conn() as c:
        if user_id:
            _user_da_empresa(c, ctx, user_id)
        return audit.recentes(c, ctx.org_id, 200, user_id)
