"""Disparo de e-mail: remetente, template, seleção e envio — tudo POR EMPRESA.

- Cada vendedor dispara da PRÓPRIA caixa (cadastrada pelo admin da empresa,
  senha cifrada). Sem caixa cadastrada, não dispara: melhor bloquear do que
  mandar do e-mail errado. Não há remetente "da plataforma".
- Teto diário = plano da empresa; rampa de aquecimento por remetente.
- Quem já recebeu da empresa nunca recebe de novo dela.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime

from app import db, email_senders, email_templates, email_validate, sent_log, settings
from app.config_loader import load_config
from app.mailer import build_message, send_one

from . import lotes
from .plan import PlanCtx
from .security import Ctx

ROOT = db.ROOT
TPL_TXT = ROOT / "config" / "email_template.txt"
TPL_HTML = ROOT / "config" / "email_template.html"
CAMPOS = ["{company}", "{solucoes}", "{cargo}", "{city}"]
_EXEMPLO = {"company": "Empresa Exemplo", "city": "São Paulo",
            "solucoes": "Solução A, Solução B", "cargo": "Diretor de Operações"}


@dataclass
class Sender:
    out: dict            # ritmo do config + remetente aplicado
    password: str

    @property
    def email(self) -> str:
        return (self.out.get("from_email") or "").strip().lower()

    @property
    def ready(self) -> bool:
        return bool(self.password and self.out.get("smtp_host") and self.out.get("smtp_user"))


def resolve_sender(ctx: Ctx) -> Sender | None:
    out = dict(load_config()["outreach"])
    with db.conn() as c:
        cfg = email_senders.get(c, ctx.org_id, ctx.id, com_senha=True)
    if not cfg or not cfg.get("smtp_password"):
        return None
    out.update({"from_name": cfg["from_name"], "from_email": cfg["from_email"],
                "smtp_user": cfg["smtp_user"] or cfg["from_email"],
                "smtp_host": cfg["smtp_host"], "smtp_port": cfg["smtp_port"],
                "reply_to": cfg["reply_to"] or cfg["from_email"]})
    return Sender(out, cfg["smtp_password"])


def _html_key(ctx: Ctx) -> str:
    return f"email_template_html:{ctx.id}"


def user_html(ctx: Ctx) -> str:
    with db.conn() as c:
        return settings.get(c, ctx.org_id, _html_key(ctx), "")


def set_user_html(ctx: Ctx, html: str) -> None:
    with db.conn() as c:
        settings.put(c, ctx.org_id, _html_key(ctx), html)


def html_template(ctx: Ctx, unsub: str) -> tuple[str, str]:
    """(html sanitizado, origem). Upload do usuário > modelo genérico do repositório."""
    saved = user_html(ctx)
    raw = saved or (TPL_HTML.read_text(encoding="utf-8") if TPL_HTML.exists() else "")
    if not raw:
        return "", "nenhum"
    return email_templates.sanitize_email_html(raw, unsub), ("upload" if saved else "padrao")


def preview(ctx: Ctx) -> tuple[str, str]:
    sender = resolve_sender(ctx)
    html, origem = html_template(ctx, sender.email if sender else "")
    return (email_templates.render_html(html, _EXEMPLO) if html else ""), origem


def text_template() -> str:
    return TPL_TXT.read_text(encoding="utf-8") if TPL_TXT.exists() else ""


def _mail_leads(itens: list[dict]) -> list[dict]:
    out = []
    for r in itens:
        email = str(r.get("Email", "")).strip()
        company = str(r.get("Company", "")).strip()
        if "@" not in email or company.lower() in ("", "sua empresa"):   # trava anti-genérico
            continue
        out.append({"company": company, "email": email,
                    "solucoes": str(r.get("Soluções", "")).strip(),
                    "cargo": str(r.get("Cargo", "")).strip(),
                    "city": str(r.get("City", "")).strip()})
    return out


def selection(ctx: Ctx, plan: PlanCtx, lote: str | None, classes: list[str]) -> dict:
    sender = resolve_sender(ctx)
    out = sender.out if sender else dict(load_config()["outreach"])
    itens = lotes.leads_para_email(ctx, plan, lote)
    itens_sel = [r for r in itens if not classes or str(r.get("Classification", "")) in classes]
    leads = _mail_leads(itens_sel)
    limite = plan.limite("emails_dia") or int(out.get("daily_limit", 10))
    warmup = bool(out.get("warmup", True))
    hoje = datetime.now().date()
    remetente = sender.email if sender else ""
    with db.conn() as c:
        enviados = sent_log.contatados(c, ctx.org_id)
        teto = sent_log.teto_hoje(c, ctx.org_id, hoje, limite, remetente, warmup)
        resta = sent_log.restante_hoje(c, ctx.org_id, hoje, limite, remetente, warmup)
    pendentes = [l for l in leads if l["email"].lower() not in enviados]
    dmin, dmax = email_templates.delay_range(out)
    n = min(len(pendentes), resta)
    motivo = ""
    if not sender:
        motivo = ("Seu e-mail de envio ainda não foi cadastrado. Peça ao admin da sua "
                  "empresa para configurar seu remetente.")
    elif not sender.ready or not text_template():
        motivo = "Remetente cadastrado, mas falta a senha de app ou o template de e-mail."
    elif not pendentes:
        motivo = "Nada pendente: nenhum lead desta lista tem e-mail, ou todos já foram contatados."
    elif resta <= 0:
        motivo = "Cota de hoje atingida. O restante sai amanhã."
    return {
        "selecionadas": len(itens_sel), "pendentes": len(pendentes), "cota_restante": resta,
        "teto_hoje": teto, "warmup": warmup, "envia_agora": n,
        "delay_min": int(dmin), "delay_max": int(dmax),
        "eta_min": round(n * ((dmin + dmax) / 2) / 60),
        "remetente": ({"from_name": out.get("from_name", ""), "from_email": sender.email,
                       "origem": "sua caixa"} if sender else None),
        "pode_enviar": not motivo, "motivo": motivo,
        "_pendentes": pendentes[:max(0, resta)], "_sender": sender,
    }


def send_batch(ctx: Ctx, plan: PlanCtx, lote: str | None, classes: list[str],
               on_progress, sleep=time.sleep) -> dict:
    """Envia o lote pendente de hoje. ``on_progress(texto)`` atualiza o job."""
    sel = selection(ctx, plan, lote, classes)
    if not sel["pode_enviar"]:
        raise RuntimeError(sel["motivo"])
    sender: Sender = sel["_sender"]
    out = sender.out
    fila = sel["_pendentes"]
    template = text_template()
    html_tpl, _ = html_template(ctx, sender.email)
    dmin, dmax = email_templates.delay_range(out)
    enviados, falhas, pulados = 0, [], []
    for i, lead in enumerate(fila):
        ok, motivo = (email_validate.check(lead["email"])
                      if out.get("validate_emails", True) else (True, ""))
        if not ok:
            pulados.append(f"{lead['company']} ({lead['email']}): {motivo}")
        else:
            try:
                assunto, corpo = email_templates.personalize(template, lead)
                assunto = email_templates.subject_for(out, assunto)
                htm = email_templates.render_html(html_tpl, lead) if html_tpl else ""
                msg = build_message(lead["email"], assunto, corpo, out.get("from_name", ""),
                                    out["from_email"], out.get("reply_to", ""), htm)
                send_one(out["smtp_host"], int(out["smtp_port"]), out["smtp_user"],
                         sender.password, msg)
                with db.conn() as c:
                    sent_log.registrar(c, ctx.org_id, lead["email"], datetime.now(), sender.email)
                enviados += 1
            except Exception as erro:  # noqa: BLE001 - uma falha não para o lote
                falhas.append(f"{lead['company']}: {type(erro).__name__}: {str(erro)[:120]}")
        on_progress(f"E-mail {i + 1} de {len(fila)} · {enviados} enviado(s)")
        if i < len(fila) - 1 and ok:
            sleep(random.uniform(dmin, dmax))
    return {"enviados": enviados, "falhas": falhas[:20], "pulados": pulados[:20],
            "total": len(fila)}
