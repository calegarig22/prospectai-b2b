"""Montagem e envio de e-mails de primeiro contato (cold outreach).

- ``build_message``: monta um e-mail (RFC822) personalizado.
- ``save_draft``: salva como arquivo ``.eml`` (abre no cliente de e-mail, pronto
  para revisar e enviar manualmente) — usado no MODO RASCUNHO (padrão).
- ``send_messages``: envia via SMTP, com limite e intervalo entre envios — só é
  usado quando ``outreach.mode = send`` e as credenciais estão configuradas.

Nada é enviado a menos que o modo de envio seja explicitamente ativado.
"""

from __future__ import annotations

import logging
import random
import re
import smtplib
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path


def _mascara(email: str) -> str:
    """E-mail parcialmente oculto para o LOG: ``jo***@empresa.com.br``.

    O log fica em arquivo e no console da nuvem, e o endereço de um contato é
    dado pessoal — não precisa estar ali inteiro para acompanhar um disparo. O
    domínio permanece, que é o que ajuda a diagnosticar (bounce, MX, bloqueio).
    """
    local, arroba, dominio = (email or "").partition("@")
    if not arroba:
        return "***"
    return f"{local[:2]}***@{dominio}" if len(local) > 2 else f"***@{dominio}"


def build_message(to_email: str, subject: str, body: str, from_name: str,
                  from_email: str, reply_to: str = "", html_body: str = "") -> EmailMessage:
    """Monta um e-mail pronto para salvar ou enviar.

    Se ``html_body`` for informado, o e-mail vira multipart/alternative: clientes
    modernos mostram o HTML (com design) e os antigos caem no ``body`` em texto
    simples. Sem ``html_body``, continua sendo um e-mail só de texto (como antes).
    """
    msg = EmailMessage()
    msg["From"] = f"{from_name} <{from_email}>" if from_name else from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    # Cabeçalhos de boa reputação: e-mail legítimo SEMPRE tem Date e Message-ID.
    # A ausência deles é um sinal forte de spam para o Gmail. O smtplib não os
    # adiciona sozinho, então preenchemos aqui.
    msg["Date"] = formatdate(localtime=True)
    domain = from_email.split("@")[-1].strip() if "@" in (from_email or "") else ""
    msg["Message-ID"] = make_msgid(domain=domain) if domain else make_msgid()
    # Opt-out padrão (LGPD) + sinal de boa reputação para o Gmail: cabeçalho
    # List-Unsubscribe. Reduz a chance de cair no spam.
    unsub = reply_to or from_email
    if unsub:
        msg["List-Unsubscribe"] = f"<mailto:{unsub}?subject=REMOVER>"
    msg.set_content(body or "")
    if html_body and html_body.strip():
        msg.add_alternative(html_body, subtype="html")
    return msg


def safe_name(text: str) -> str:
    """Nome de arquivo seguro a partir do nome da empresa."""
    text = re.sub(r"[^\w\-]+", "_", (text or "empresa").strip())
    return text[:50] or "empresa"


def save_draft(msg: EmailMessage, out_dir: str | Path, name: str) -> Path:
    """Salva o e-mail como ``.eml`` (rascunho revisável)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / (name + ".eml")
    path.write_bytes(msg.as_bytes())
    return path


def send_one(host: str, port: int, user: str, password: str, msg: EmailMessage) -> None:
    """Envia um único e-mail via SMTP (usado no teste 'enviar para mim mesmo')."""
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)


def send_messages(messages: list[tuple[str, EmailMessage]], host: str, port: int,
                  user: str, password: str, daily_limit: int, delay_min: float,
                  delay_max: float, logger: logging.Logger, sent_log,
                  warmup: bool = True, sender: str = "") -> int:
    """Envia via SMTP respeitando o cap DIÁRIO (rampa) e com pausa aleatória.

    ``sent_log`` é um :class:`app.sent_log.SentLog` (banco persistente na nuvem ou
    arquivo local). Garante que:
    - quem já recebeu (qualquer dia) é pulado;
    - para ao atingir o limite restante de HOJE (conta envios anteriores do dia);
    - espera um tempo ALEATÓRIO entre ``delay_min`` e ``delay_max`` segundos entre
      cada envio — padrão irregular parece humano e não dispara o anti-spam.
    """
    already = sent_log.contacted()
    today = datetime.now().date()
    remaining = sent_log.remaining_today(today, daily_limit, warmup, sender=sender)
    if remaining <= 0:
        logger.info("Cota de hoje já atingida (cap %d/dia). Nada será enviado agora.",
                    sent_log.warmup_cap(today, daily_limit, sender=sender) if warmup else daily_limit)
        return 0
    logger.info("Cota de hoje: até %d e-mail(s); pausa de %g–%gs entre cada um.",
                remaining, delay_min, delay_max)
    n_sent = 0
    with smtplib.SMTP(host, port, timeout=30) as server:
        server.starttls()
        server.login(user, password)
        for to_email, msg in messages:
            if to_email.lower() in already:
                logger.info("Pulando %s (já enviado antes).", _mascara(to_email))
                continue
            if n_sent >= remaining:
                logger.info("Limite diário atingido. Recomeça amanhã.")
                break
            server.send_message(msg)
            sent_log.add(to_email, datetime.now(), sender=sender)
            already.add(to_email.lower())
            n_sent += 1
            logger.info("Enviado %d/%d -> %s", n_sent, remaining, _mascara(to_email))
            if n_sent < remaining:
                time.sleep(random.uniform(delay_min, delay_max))
    return n_sent
