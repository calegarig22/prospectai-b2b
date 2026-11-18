"""Usuários: login por pessoa, papéis, bloqueio por tentativas e reset de senha.

Papéis:
- ``superadmin``: dono da plataforma. Vive na empresa ``plataforma`` e só
  administra empresas (cria, define plano e nicho). Não vê leads de ninguém.
- ``admin``: administra a PRÓPRIA empresa (usuários, remetentes, lotes).
- ``vendedor``: trabalha os próprios leads.

Toda leitura/alteração de usuário de empresa recebe ``org_id`` e o usa no WHERE:
um id de outra empresa simplesmente não é encontrado. Senhas em PBKDF2-HMAC-SHA256.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import datetime, timedelta

from . import planos
from .db import Conn

ROLES = ("superadmin", "admin", "vendedor")
ROLES_DE_EMPRESA = ("admin", "vendedor")
_ITERATIONS = 200_000
_RESET_MAX_ATTEMPTS = 5
_RESET_TTL_MIN = 15        # validade do código (min)
_LOGIN_MAX_FAILS = 5
_LOGIN_LOCK_MINUTES = 5
_COLS = "id, org_id, email, name, role, active, created_at"


# --- hashing de senha (PBKDF2, stdlib) -------------------------------------
def hash_password(password: str, *, iterations: int = _ITERATIONS) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:  # noqa: BLE001 - hash malformado = não confere
        return False


def _valida_email(email: str) -> tuple[bool, str]:
    """Valida o e-mail de login com o MESMO validador do disparo.

    Antes bastava conter "@", então "a@" era aceito — e um login que não recebe
    e-mail é um usuário que não consegue redefinir a própria senha.

    O ``check_mx`` só recusa quando o DNS afirma que o domínio NÃO existe; se a
    consulta falha ou é incerta, deixa passar. Ou seja, rede instável nunca
    impede um cadastro legítimo. Domínio interno inventado (``@empresa.local``)
    é recusado de propósito: reset de senha não chegaria lá.
    """
    if not email:
        return False, "vazio"
    try:
        from .email_validate import check
        return check(email, check_mx=True)
    except Exception:  # noqa: BLE001 - validador indisponível não pode travar o cadastro
        return ("@" in email and "." in email.partition("@")[2]), "formato"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def _row(r) -> dict:
    return {"id": r[0], "org_id": r[1], "email": r[2], "name": r[3] or "", "role": r[4],
            "active": bool(r[5]), "created_at": r[6] or ""}


# ------------------------------------------------------------------ leitura
def count_all(c: Conn) -> int:
    return int(c.one("SELECT COUNT(*) FROM users")[0])


def get_by_email(c: Conn, email: str) -> dict | None:
    """Para o LOGIN (antes de saber a empresa). Inclui o hash da senha."""
    r = c.one(f"SELECT {_COLS}, password_hash FROM users WHERE email = {c.ph}",
              (_norm_email(email),))
    if not r:
        return None
    u = _row(r)
    u["password_hash"] = r[7]
    return u


def get_by_id(c: Conn, user_id: str) -> dict | None:
    """Para a SESSÃO. Inclui o hash (a sessão cai quando a senha muda)."""
    r = c.one(f"SELECT {_COLS}, password_hash FROM users WHERE id = {c.ph}", (user_id,))
    if not r:
        return None
    u = _row(r)
    u["password_hash"] = r[7]
    return u


def get_in_org(c: Conn, org_id: str, user_id: str) -> dict | None:
    r = c.one(f"SELECT {_COLS} FROM users WHERE id = {c.ph} AND org_id = {c.ph}",
              (user_id, org_id))
    return _row(r) if r else None


def list_users(c: Conn, org_id: str) -> list[dict]:
    rows = c.all(f"SELECT {_COLS} FROM users WHERE org_id = {c.ph} ORDER BY created_at",
                 (org_id,))
    return [_row(r) for r in rows]


def usuarios_da_org(c: Conn, org_id: str) -> int:
    """Cadastrados (ativos E inativos): a vaga do plano é do CADASTRO.

    Desativar não devolve vaga, só remover devolve. Contar só ativos deixava a
    conta estufar — desativa um, cria outro, e o cadastro cresce sem fim.
    """
    return int(c.one(f"SELECT COUNT(*) FROM users WHERE org_id = {c.ph}", (org_id,))[0])


def _teto_usuarios(c: Conn, org_id: str) -> tuple[int, str]:
    r = c.one(f"SELECT plano, trial_ate FROM orgs WHERE id = {c.ph}", (org_id,))
    if not r:
        raise ValueError("Empresa não encontrada.")
    return planos.limite(r[0], "usuarios", r[1]), planos.nome(r[0], r[1])


# ------------------------------------------------------------------ escrita
def create_user(c: Conn, org_id: str, email: str, password: str, name: str = "",
                role: str = "vendedor", *, check_mx: bool = True) -> dict:
    email = _norm_email(email)
    if check_mx:
        ok, motivo = _valida_email(email)
        if not ok:
            raise ValueError(f"E-mail inválido: {motivo}.")
    elif "@" not in email:
        raise ValueError("E-mail inválido.")
    if not password or len(password) < 6:
        raise ValueError("A senha precisa ter ao menos 6 caracteres.")
    if role not in ROLES:
        raise ValueError("Papel inválido.")
    if get_by_email(c, email):
        raise ValueError("Já existe um usuário com esse e-mail.")
    if role != "superadmin":
        teto, plano_nome = _teto_usuarios(c, org_id)
        cadastrados = usuarios_da_org(c, org_id)
        if not planos.ilimitado(teto) and cadastrados >= teto:
            raise ValueError(
                f"O plano {plano_nome} permite {teto} usuário(s) e a empresa já tem "
                f"{cadastrados} (contando os inativos). REMOVA um usuário ou mude de "
                f"plano — desativar não libera a vaga.")
    uid = uuid.uuid4().hex
    c.run(f"INSERT INTO users (id, org_id, email, name, role, password_hash, active, created_at) "
          f"VALUES ({', '.join([c.ph] * 8)})",
          (uid, org_id, email, (name or "").strip(), role, hash_password(password), 1, _now()))
    return get_in_org(c, org_id, uid)


def verify(c: Conn, email: str, password: str) -> dict | None:
    """Usuário (com hash) se e-mail+senha conferem e ele está ativo."""
    u = get_by_email(c, email)
    if not u or not u["active"] or not verify_password(password, u["password_hash"]):
        return None
    return u


def set_password(c: Conn, org_id: str, user_id: str, new_password: str) -> None:
    if not new_password or len(new_password) < 6:
        raise ValueError("A senha precisa ter ao menos 6 caracteres.")
    c.run(f"UPDATE users SET password_hash = {c.ph} WHERE id = {c.ph} AND org_id = {c.ph}",
          (hash_password(new_password), user_id, org_id))


def set_name(c: Conn, org_id: str, user_id: str, name: str) -> None:
    c.run(f"UPDATE users SET name = {c.ph} WHERE id = {c.ph} AND org_id = {c.ph}",
          ((name or "").strip(), user_id, org_id))


def set_role(c: Conn, org_id: str, user_id: str, role: str) -> None:
    if role not in ROLES_DE_EMPRESA:
        raise ValueError("Papel inválido.")
    c.run(f"UPDATE users SET role = {c.ph} WHERE id = {c.ph} AND org_id = {c.ph}",
          (role, user_id, org_id))


def set_active(c: Conn, org_id: str, user_id: str, active: bool) -> None:
    """Ativa/desativa o acesso. Não mexe na vaga do plano (a vaga é do cadastro)."""
    c.run(f"UPDATE users SET active = {c.ph} WHERE id = {c.ph} AND org_id = {c.ph}",
          (1 if active else 0, user_id, org_id))


def delete_user(c: Conn, org_id: str, user_id: str) -> None:
    c.run(f"DELETE FROM users WHERE id = {c.ph} AND org_id = {c.ph}", (user_id, org_id))


# ------------------------------------------------ bloqueio por tentativas
def login_lock_seconds(c: Conn, email: str) -> int:
    r = c.one(f"SELECT locked_until FROM login_attempts WHERE email = {c.ph}",
              (_norm_email(email),))
    if not r or not r[0]:
        return 0
    try:
        return max(0, int((datetime.fromisoformat(r[0]) - datetime.now()).total_seconds()))
    except ValueError:
        return 0


def record_login_fail(c: Conn, email: str) -> None:
    email = _norm_email(email)
    r = c.one(f"SELECT fails FROM login_attempts WHERE email = {c.ph}", (email,))
    n = ((r[0] or 0) if r else 0) + 1
    locked = ""
    if n >= _LOGIN_MAX_FAILS:
        locked = (datetime.now() + timedelta(minutes=_LOGIN_LOCK_MINUTES)).isoformat(timespec="seconds")
        n = 0
    c.run(f"DELETE FROM login_attempts WHERE email = {c.ph}", (email,))
    c.run(f"INSERT INTO login_attempts (email, fails, locked_until) VALUES ({c.ph}, {c.ph}, {c.ph})",
          (email, n, locked or None))


def clear_login_fails(c: Conn, email: str) -> None:
    c.run(f"DELETE FROM login_attempts WHERE email = {c.ph}", (_norm_email(email),))


# ------------------------------------------------------- esqueci a senha
def _code_hash(code: str) -> str:
    return hashlib.sha256((code or "").strip().encode("utf-8")).hexdigest()


def start_reset(c: Conn, email: str) -> tuple[str, dict] | None:
    """(código, usuário) se a conta existe e está ativa; senão None."""
    u = get_by_email(c, email)
    if not u or not u["active"]:
        return None
    code = f"{int.from_bytes(os.urandom(3), 'big') % 1_000_000:06d}"
    expires = (datetime.now() + timedelta(minutes=_RESET_TTL_MIN)).isoformat(timespec="seconds")
    c.run(f"DELETE FROM password_resets WHERE user_id = {c.ph}", (u["id"],))
    c.run(f"INSERT INTO password_resets (user_id, code_hash, expires_at, attempts) "
          f"VALUES ({c.ph}, {c.ph}, {c.ph}, 0)", (u["id"], _code_hash(code), expires))
    return code, u


def _code_ok(c: Conn, email: str, code: str) -> dict | None:
    u = get_by_email(c, email)
    if not u or not u["active"]:
        return None
    r = c.one(f"SELECT code_hash, expires_at, attempts FROM password_resets WHERE user_id = {c.ph}",
              (u["id"],))
    if not r:
        return None
    if not hmac.compare_digest(_code_hash(code), str(r[0])):
        n = (r[2] or 0) + 1      # palpite errado conta; no limite o código morre
        if n >= _RESET_MAX_ATTEMPTS:
            c.run(f"DELETE FROM password_resets WHERE user_id = {c.ph}", (u["id"],))
        else:
            c.run(f"UPDATE password_resets SET attempts = {c.ph} WHERE user_id = {c.ph}", (n, u["id"]))
        return None
    try:
        if datetime.fromisoformat(r[1]) < datetime.now():
            return None
    except ValueError:
        return None
    return u


def check_reset_code(c: Conn, email: str, code: str) -> bool:
    return _code_ok(c, email, code) is not None


def reset_with_code(c: Conn, email: str, code: str, new_password: str) -> bool:
    if not new_password or len(new_password) < 6:
        raise ValueError("A senha precisa ter ao menos 6 caracteres.")
    u = _code_ok(c, email, code)
    if not u:
        return False
    set_password(c, u["org_id"], u["id"], new_password)
    c.run(f"DELETE FROM password_resets WHERE user_id = {c.ph}", (u["id"],))
    return True
