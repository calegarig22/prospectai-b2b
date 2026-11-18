"""Sessão, CSRF e autorização.

Sessão
    Um JWT assinado (HS256) num cookie httpOnly — o JavaScript da página não
    consegue lê-lo, então um XSS não rouba a sessão. O token guarda só o id do
    usuário e uma impressão do hash da senha: trocar a senha derruba TODAS as
    sessões abertas daquela conta. Papel, empresa e "ativo" (do usuário E da
    empresa) são relidos do banco a cada requisição — rebaixar, desativar alguém
    ou suspender uma empresa vale na hora, não no fim do token.

CSRF
    Toda requisição que muda estado precisa do cabeçalho ``X-Requested-With``.
    Um formulário de outro site não consegue enviá-lo, e um fetch de outra
    origem com ele exige preflight de CORS, que a API nega.

Isolamento entre empresas (multi-tenant)
    ``Ctx`` carrega usuário + empresa (org). O ``org_id`` vem SEMPRE do banco,
    nunca da requisição: não existe parâmetro que o cliente mande para "trocar de
    empresa". Toda consulta de dado de cliente usa ``ctx.org_id``; vendedor ainda
    é restrito ao próprio ``owner_id``. O superadmin vive na empresa
    ``plataforma`` e não tem rota para ler leads de ninguém.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, Response, status

from app import db
from app.orgs import PLATAFORMA_ID

from .settings import SESSION_HOURS, SESSION_REFRESH_MIN

COOKIE = "tp_session"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "prospectai"
_ALG = "HS256"
_SAFE = {"GET", "HEAD", "OPTIONS"}


@dataclass(frozen=True)
class Ctx:
    """Quem está chamando. Montado do BANCO a cada requisição, não do token."""
    id: str
    email: str
    name: str
    role: str
    org_id: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_superadmin(self) -> bool:
        return self.role == "superadmin" and self.org_id == PLATAFORMA_ID

    @property
    def owner_filter(self) -> str | None:
        """Vendedor vê só os próprios leads; admin vê todos os da conta."""
        return None if self.is_admin else self.id

    def as_user(self) -> dict:
        """Formato que app/audit.py e afins esperam."""
        return {"id": self.id, "email": self.email, "name": self.name,
                "role": self.role, "org_id": self.org_id}


def _pw_fingerprint(password_hash: str) -> str:
    return hashlib.sha256((password_hash or "").encode()).hexdigest()[:16]


def issue(response: Response, request: Request, user_id: str, password_hash: str) -> None:
    settings = request.app.state.settings
    now = int(time.time())
    token = jwt.encode({"sub": user_id, "pwf": _pw_fingerprint(password_hash),
                        "iat": now, "exp": now + SESSION_HOURS * 3600},
                       settings.jwt_secret, algorithm=_ALG)
    response.set_cookie(COOKIE, token, max_age=SESSION_HOURS * 3600, httponly=True,
                        secure=settings.cookie_secure, samesite="lax", path="/")


def clear(response: Response, request: Request) -> None:
    response.delete_cookie(COOKIE, path="/", httponly=True,
                           secure=request.app.state.settings.cookie_secure, samesite="lax")


def _load_user(user_id: str) -> tuple | None:
    """Usuário + situação da empresa dele, numa consulta só."""
    with db.conn() as c:
        return c.one(f"SELECT u.id, u.email, u.name, u.role, u.password_hash, u.active, "
                     f"u.org_id, o.active FROM users u JOIN orgs o ON o.id = u.org_id "
                     f"WHERE u.id = {c.ph}", (user_id,))


def csrf_guard(request: Request) -> None:
    if request.method not in _SAFE and request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requisição sem o cabeçalho de origem.")


def current_user(request: Request, response: Response) -> Ctx:
    csrf_guard(request)
    token = request.cookies.get(COOKIE, "")
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Faça login.")
    try:
        claims = jwt.decode(token, request.app.state.settings.jwt_secret, algorithms=[_ALG],
                            options={"require": ["sub", "exp", "iat"]})
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sua sessão expirou. Entre novamente.")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão inválida.")
    row = _load_user(str(claims["sub"]))
    if not row or not row[5] or _pw_fingerprint(row[4]) != claims.get("pwf"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sessão encerrada. Entre novamente.")
    if not row[7]:
        raise HTTPException(status.HTTP_403_FORBIDDEN,
                            "O acesso desta empresa está suspenso. Fale com o suporte.")
    ctx = Ctx(id=row[0], email=row[1], name=row[2] or "", role=row[3], org_id=row[6])
    # Janela deslizante: quem está usando não cai no meio do trabalho.
    if time.time() - int(claims["iat"]) > SESSION_REFRESH_MIN * 60:
        issue(response, request, ctx.id, row[4])
    return ctx


def require_member(ctx: Ctx = Depends(current_user)) -> Ctx:
    """Usuário de uma EMPRESA cliente (admin ou vendedor). O superadmin não entra:
    ele administra a plataforma, não prospecta nem vê leads de cliente."""
    if ctx.role not in ("admin", "vendedor") or ctx.org_id == PLATAFORMA_ID:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Área das empresas clientes.")
    return ctx


def require_admin(ctx: Ctx = Depends(require_member)) -> Ctx:
    if not ctx.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso restrito à administração.")
    return ctx


def require_superadmin(ctx: Ctx = Depends(current_user)) -> Ctx:
    if not ctx.is_superadmin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Acesso restrito ao dono da plataforma.")
    return ctx
