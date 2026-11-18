"""Remetente de cada vendedor (de qual caixa ele dispara).

A senha de app precisa ser recuperável (para autenticar no SMTP), então é
CIFRADA com Fernet (``secret_box``), nunca gravada em texto puro. Toda função
recebe ``org_id``: o remetente de outra empresa não existe para quem consulta.
"""

from __future__ import annotations

from datetime import datetime

from . import secret_box
from .db import Conn

_COLS = "user_id, from_name, from_email, smtp_host, smtp_port, smtp_user, smtp_password_enc, reply_to"


def _row(r, com_senha: bool) -> dict:
    d = {"user_id": r[0], "from_name": r[1] or "", "from_email": r[2] or "",
         "smtp_host": r[3] or "smtp.gmail.com", "smtp_port": int(r[4] or 587),
         "smtp_user": r[5] or "", "reply_to": r[7] or "", "has_password": bool(r[6])}
    if com_senha:
        d["smtp_password"] = secret_box.decrypt(r[6] or "")
    return d


def get(c: Conn, org_id: str, user_id: str, com_senha: bool = False) -> dict | None:
    r = c.one(f"SELECT {_COLS} FROM email_senders WHERE user_id = {c.ph} AND org_id = {c.ph}",
              (user_id, org_id))
    return _row(r, com_senha) if r else None


def todos(c: Conn, org_id: str) -> dict[str, dict]:
    """Remetentes da empresa, SEM a senha (para a tela)."""
    return {r[0]: _row(r, False) for r in c.all(
        f"SELECT {_COLS} FROM email_senders WHERE org_id = {c.ph}", (org_id,))}


def salvar(c: Conn, org_id: str, user_id: str, from_email: str, from_name: str,
           smtp_host: str, smtp_port: int, smtp_password: str = "") -> None:
    """Cria/atualiza. Senha em branco MANTÉM a atual; na 1ª vez é obrigatória."""
    from_email = (from_email or "").strip()
    if "@" not in from_email:
        raise ValueError("E-mail remetente inválido.")
    atual = c.one(f"SELECT smtp_password_enc FROM email_senders WHERE user_id = {c.ph} "
                  f"AND org_id = {c.ph}", (user_id, org_id))
    if smtp_password:
        if not secret_box.available():
            raise ValueError("Cifragem indisponível: defina EMAIL_ENC_KEY no servidor.")
        enc = secret_box.encrypt(smtp_password)
    elif atual and atual[0]:
        enc = atual[0]
    else:
        raise ValueError("Informe a senha de app na primeira vez.")
    agora = datetime.now().isoformat(timespec="seconds")
    c.run(f"INSERT INTO email_senders (user_id, org_id, from_name, from_email, smtp_host, smtp_port, "
          f"smtp_user, smtp_password_enc, reply_to, updated_at) VALUES ({', '.join([c.ph] * 10)}) "
          f"ON CONFLICT (user_id) DO UPDATE SET from_name = excluded.from_name, "
          f"from_email = excluded.from_email, smtp_host = excluded.smtp_host, "
          f"smtp_port = excluded.smtp_port, smtp_user = excluded.smtp_user, "
          f"smtp_password_enc = excluded.smtp_password_enc, reply_to = excluded.reply_to, "
          f"updated_at = excluded.updated_at",
          (user_id, org_id, (from_name or "").strip(), from_email, (smtp_host or "").strip(),
           int(smtp_port or 587), from_email, enc, from_email, agora))


def remover(c: Conn, org_id: str, user_id: str) -> None:
    c.run(f"DELETE FROM email_senders WHERE user_id = {c.ph} AND org_id = {c.ph}", (user_id, org_id))
