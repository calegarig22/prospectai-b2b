"""E-mails já enviados, POR EMPRESA: quem recebeu nunca recebe de novo, a cota
diária por remetente e a rampa de aquecimento (que protege a reputação do domínio)."""

from __future__ import annotations

from datetime import date, datetime

from .db import Conn

# Teto de envios por dia conforme a "idade" do remetente. Índice 0 = 1º dia.
WARMUP_SCHEDULE = [3, 4, 6, 8, 10, 12, 15, 18, 20]


def contatados(c: Conn, org_id: str) -> set[str]:
    return {r[0].lower() for r in c.all(f"SELECT email FROM sent_emails WHERE org_id = {c.ph}",
                                         (org_id,)) if r[0]}


def enviados_no_dia(c: Conn, org_id: str, dia: date, sender: str) -> int:
    r = c.one(f"SELECT COUNT(*) FROM sent_emails WHERE org_id = {c.ph} AND sender = {c.ph} "
              f"AND sent_at LIKE {c.ph}", (org_id, sender.lower(), dia.isoformat() + "%"))
    return int(r[0]) if r else 0


def primeiro_envio(c: Conn, org_id: str, sender: str) -> date | None:
    r = c.one(f"SELECT MIN(sent_at) FROM sent_emails WHERE org_id = {c.ph} AND sender = {c.ph}",
              (org_id, sender.lower()))
    return date.fromisoformat(r[0][:10]) if r and r[0] else None


def registrar(c: Conn, org_id: str, email: str, quando: datetime, sender: str) -> None:
    c.run(f"INSERT INTO sent_emails (org_id, email, sent_at, sender) "
          f"VALUES ({c.ph}, {c.ph}, {c.ph}, {c.ph}) ON CONFLICT (org_id, email) DO NOTHING",
          (org_id, email.lower().strip(), quando.isoformat(timespec="seconds"), sender.lower()))


def teto_hoje(c: Conn, org_id: str, hoje: date, limite: int, sender: str, warmup: bool) -> int:
    if not warmup:
        return limite
    inicio = primeiro_envio(c, org_id, sender)
    idx = 0 if inicio is None else max(0, (hoje - inicio).days)
    rampa = WARMUP_SCHEDULE[idx] if idx < len(WARMUP_SCHEDULE) else limite
    return min(limite, rampa)


def restante_hoje(c: Conn, org_id: str, hoje: date, limite: int, sender: str, warmup: bool) -> int:
    return max(0, teto_hoje(c, org_id, hoje, limite, sender, warmup)
               - enviados_no_dia(c, org_id, hoje, sender))
