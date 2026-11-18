"""Login, sessão, troca de senha, "esqueci a senha" e criação do dono da plataforma.

Regra anti-enumeração: nenhuma resposta pública pode revelar se um e-mail tem
conta. Login errado e conta inativa dão a MESMA mensagem (e o mesmo tempo); o
pedido de código de reset responde igual exista ou não a conta, e o envio
acontece em segundo plano.
"""

from __future__ import annotations

import hmac
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app import audit, db, orgs, planos, users
from app.mailer import build_message, send_one

from .. import ratelimit
from ..plan import leads_no_mes, load as load_plan, renova_em
from ..schemas import (AuthStatus, BootstrapIn, ChangePasswordIn, LoginIn, MeOut, Msg,
                       ResetConfirmIn, ResetStartIn, ResetVerifyIn)
from ..security import Ctx, clear, current_user, issue

router = APIRouter(prefix="/auth", tags=["auth"])

_RESET_MSG = ("Se este e-mail estiver cadastrado, enviamos um código de 6 dígitos. "
              "Veja a caixa de entrada (e o spam).")
_reset_last: dict[str, float] = {}       # cooldown de 60s por e-mail (em memória)
_reset_guard = threading.Lock()
_DUMMY_HASH = users.hash_password("senha-que-nao-existe")


def _audit(org_id: str, user: dict | None, action: str, detail: str = "") -> None:
    with db.conn() as c:
        audit.registrar(c, org_id, user, action, detail)


@router.get("/status", response_model=AuthStatus)
def auth_status(request: Request):
    with db.conn() as c:
        vazio = users.count_all(c) == 0
    return {"needs_bootstrap": vazio,
            "bootstrap_enabled": bool(request.app.state.settings.app_password)}


@router.post("/bootstrap", response_model=Msg)
def bootstrap(body: BootstrapIn, request: Request, response: Response):
    """Cria o DONO DA PLATAFORMA (superadmin). Só funciona com o banco vazio e a
    senha do time (APP_PASSWORD). As empresas clientes nascem depois, pela tela."""
    ratelimit.limit(request, "bootstrap", 5, 600)
    senha_time = request.app.state.settings.app_password
    if not senha_time:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "Defina APP_PASSWORD no servidor para criar o primeiro acesso.")
    if not hmac.compare_digest(body.app_password.encode(), senha_time.encode()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Senha do time incorreta.")
    with db.conn() as c:
        if users.count_all(c) > 0:
            raise HTTPException(status.HTTP_409_CONFLICT, "O primeiro acesso já foi criado.")
        orgs.garantir_plataforma(c)
        try:
            user = users.create_user(c, orgs.PLATAFORMA_ID, body.email, body.password,
                                     name=body.name, role="superadmin")
        except ValueError as erro:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))
        full = users.get_by_id(c, user["id"])
    issue(response, request, user["id"], full["password_hash"])
    _audit(orgs.PLATAFORMA_ID, user, "Criou o dono da plataforma (bootstrap)")
    return {"detail": "Acesso criado."}


@router.post("/login", response_model=Msg)
def login(body: LoginIn, request: Request, response: Response):
    ratelimit.limit(request, "login", 20, 300)
    with db.conn() as c:
        lock = users.login_lock_seconds(c, body.email)
        if lock > 0:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                f"Muitas tentativas. Tente novamente em {max(1, lock // 60)} min.")
        user = users.verify(c, body.email, body.password)
        org = orgs.get(c, user["org_id"]) if user else None
        if not user or not org or not org["active"]:
            if not user and not users.get_by_email(c, body.email):
                # Gasta o mesmo PBKDF2 de uma conta real: sem isso, o tempo de
                # resposta diria quais e-mails têm conta.
                users.verify_password(body.password, _DUMMY_HASH)
            users.record_login_fail(c, body.email)
            lock = users.login_lock_seconds(c, body.email)
            if lock > 0:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                    "Muitas tentativas de senha. Acesso bloqueado por "
                                    f"{max(1, lock // 60)} min por segurança.")
            raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                                "E-mail ou senha inválidos (ou acesso inativo).")
        users.clear_login_fails(c, body.email)
    issue(response, request, user["id"], user["password_hash"])
    _audit(user["org_id"], user, "Login")
    return {"detail": "ok"}


@router.post("/logout", response_model=Msg)
def logout(request: Request, response: Response):
    try:
        ctx = current_user(request, Response())
        _audit(ctx.org_id, ctx.as_user(), "Logout")
    except HTTPException:
        pass                          # sessão já inválida: só limpa o cookie
    clear(response, request)
    return {"detail": "ok"}


@router.get("/me", response_model=MeOut)
def me(ctx: Ctx = Depends(current_user)):
    with db.conn() as c:
        org = orgs.get(c, ctx.org_id)
    out = {"user": {"id": ctx.id, "email": ctx.email, "name": ctx.name, "role": ctx.role},
           "org": {"id": org["id"], "name": org["name"], "marca": org["marca"]},
           "plan": None}
    if ctx.is_superadmin:
        return out
    plan = load_plan(ctx.org_id)
    efetivo = plan.efetivo
    out["plan"] = {"contratado": plan.contratado, "efetivo": efetivo,
                   "nome": planos.PLANOS[efetivo]["nome"], "em_teste": plan.em_teste,
                   "trial_ate": plan.trial_ate, "limites": planos.PLANOS[efetivo]["limites"],
                   "recursos": planos.PLANOS[efetivo]["recursos"],
                   "uso_leads_mes": leads_no_mes(ctx.org_id), "renova_em": renova_em(),
                   "ilimitado": planos.ILIMITADO}
    return out


@router.post("/password", response_model=Msg)
def change_password(body: ChangePasswordIn, request: Request, response: Response,
                    ctx: Ctx = Depends(current_user)):
    with db.conn() as c:
        if not users.verify(c, ctx.email, body.current):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Senha atual incorreta.")
        try:
            users.set_password(c, ctx.org_id, ctx.id, body.new)
        except ValueError as erro:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))
        full = users.get_by_id(c, ctx.id)
    # Nova impressão da senha: esta sessão continua, as outras caem.
    issue(response, request, ctx.id, full["password_hash"])
    _audit(ctx.org_id, ctx.as_user(), "Trocou a própria senha")
    return {"detail": "Senha alterada."}


# ------------------------------------------------------------ esqueci a senha
def _send_reset_code(settings, to_email: str, code: str) -> None:
    if not (settings.smtp_from and settings.smtp_password and settings.smtp_host):
        return
    body = (f"Olá,\n\nSeu código para redefinir a senha é: {code}\n\n"
            "Ele vale por 15 minutos e só pode ser usado uma vez. "
            "Se você não solicitou, ignore este e-mail.\n\nProspectAI")
    msg = build_message(to_email, "Código para redefinir sua senha — ProspectAI", body,
                        "ProspectAI", settings.smtp_from, settings.smtp_from)
    try:
        send_one(settings.smtp_host, settings.smtp_port, settings.smtp_user,
                 settings.smtp_password, msg)
    except Exception:  # noqa: BLE001 - falha de envio não pode vazar na resposta
        pass


def _reset_job(settings, email: str) -> None:
    try:
        with db.conn() as c:
            r = users.start_reset(c, email)
        if r:
            _send_reset_code(settings, r[1]["email"], r[0])
    except Exception:  # noqa: BLE001
        pass


@router.post("/reset/start", response_model=Msg)
def reset_start(body: ResetStartIn, request: Request):
    ratelimit.limit(request, "reset", 6, 600)
    email = body.email.strip().lower()
    with _reset_guard:
        agora = time.time()
        recente = agora - _reset_last.get(email, 0) < 60
        if not recente:
            _reset_last[email] = agora
    if email and not recente:
        threading.Thread(target=_reset_job, args=(request.app.state.settings, email),
                         daemon=True).start()
    return {"detail": _RESET_MSG}


@router.post("/reset/verify", response_model=Msg)
def reset_verify(body: ResetVerifyIn, request: Request):
    ratelimit.limit(request, "reset-code", 15, 600)
    with db.conn() as c:
        ok = users.check_reset_code(c, body.email, body.code)
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Código inválido ou expirado. Confira o e-mail ou reenvie.")
    return {"detail": "ok"}


@router.post("/reset/confirm", response_model=Msg)
def reset_confirm(body: ResetConfirmIn, request: Request):
    ratelimit.limit(request, "reset-code", 15, 600)
    with db.conn() as c:
        try:
            ok = users.reset_with_code(c, body.email, body.code, body.password)
        except ValueError as erro:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))
        if ok:
            users.clear_login_fails(c, body.email)
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "O código expirou. Recomece o processo.")
    return {"detail": "Senha redefinida. Entre com a nova senha."}
