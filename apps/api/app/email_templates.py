"""Templates de e-mail: personalização, HTML e ritmo de envio.

Campos que o template pode usar: ``{company}``, ``{solucoes}``, ``{cargo}``, ``{city}``.
"""

from __future__ import annotations

import re


def delay_range(out: dict) -> tuple[float, float]:
    """Intervalo (min, max) de pausa entre envios, com compat ao antigo delay_seconds."""
    if out.get("delay_min") is not None or out.get("delay_max") is not None:
        lo = float(out.get("delay_min", out.get("delay_seconds", 30)))
        hi = float(out.get("delay_max", lo))
    else:  # config antiga: só delay_seconds
        lo = hi = float(out.get("delay_seconds", 30))
    return (min(lo, hi), max(lo, hi))


def personalize(template: str, lead: dict) -> tuple[str, str]:
    """Extrai o assunto (1a linha 'Assunto:') e preenche os campos do corpo."""
    lines = [ln for ln in template.splitlines() if not ln.lstrip().startswith("#")]
    subject = "Uma ideia para a {company}"
    if lines and lines[0].lower().startswith("assunto:"):
        subject = lines[0].split(":", 1)[1].strip()
        lines = lines[1:]
    body = "\n".join(lines).strip("\n")
    for key, value in (("{company}", lead["company"]), ("{solucoes}", lead["solucoes"]),
                       ("{cargo}", lead["cargo"]), ("{city}", lead["city"])):
        subject = subject.replace(key, value)
        body = body.replace(key, value)
    return subject, body


def render_html(html_template: str, lead: dict) -> str:
    """Preenche {company}/{solucoes}/{cargo}/{city} no template HTML do e-mail."""
    out = html_template
    for key, value in (("{company}", lead.get("company", "")), ("{solucoes}", lead.get("solucoes", "")),
                       ("{cargo}", lead.get("cargo", "")), ("{city}", lead.get("city", ""))):
        out = out.replace(key, value or "")
    return out


def _strip_div_block(html: str, marker: str) -> str:
    """Remove o <div ...marker...> ... </div> inteiro, casando o aninhamento."""
    start = html.find(marker)
    if start < 0:
        return html
    pos, depth = start, 0
    while pos < len(html):
        nd = html.find("<div", pos)
        nc = html.find("</div>", pos)
        if nc < 0:
            return html  # HTML malformado: não arrisca, devolve como está
        if nd != -1 and nd < nc:
            depth += 1
            pos = nd + 4
        else:
            depth -= 1
            pos = nc + 6
            if depth == 0:
                return html[:start] + html[pos:]
    return html


def sanitize_email_html(html: str, unsubscribe_mailto: str = "") -> str:
    """Limpa o HTML exportado do Mailchimp para um disparo por SMTP saudável.

    1. Remove o 'cromo' de arquivo (barra superior: Campaign URL, Twitter, RSS...).
    2. Conserta os links de descadastro do Mailchimp: ``list-manage.com/unsubscribe``
       e ``/profile`` usam o merge tag ``[UNIQID]``, que SÓ o Mailchimp substitui —
       num envio por SMTP eles ficam quebrados (e link de descadastro morto derruba a
       entregabilidade). Trocamos por um opt-out real (``mailto:...REMOVER``).
    Só age se os marcadores existirem.
    """
    if not html:
        return html
    html = _strip_div_block(html, '<div id="awesomewrap"')
    html = re.sub(r"<link[^>]*archivebar[^>]*>", "", html, flags=re.IGNORECASE)
    html = html.replace('<body id="archivebody">', "<body>")
    # Links de descadastro/perfil do Mailchimp -> opt-out por e-mail (funciona no SMTP).
    if unsubscribe_mailto:
        target = f"mailto:{unsubscribe_mailto}?subject=REMOVER"
        html = re.sub(r'href="https?://[^"]*list-manage\.com/[^"]*"',
                      f'href="{target}"', html, flags=re.IGNORECASE)
    # Remove merge tags do Mailchimp que sobraram (ex.: [UNIQID], *|MC:...|*).
    html = html.replace("[UNIQID]", "")
    html = re.sub(r"\*\|[^|]*\|\*", "", html)
    return html


def html_to_text(html: str) -> str:
    """Extrai um texto simples do HTML — só quando NÃO existe o template .txt.

    A parte de texto precisa dizer a mesma coisa que o HTML, senão o Gmail
    desconfia do mismatch e pontua como spam. Quem faz isso bem é o
    ``email_template.txt``, escrito em par com o HTML. Raspar o HTML é o
    último recurso: o resultado sai com o logo picado em linhas soltas e os
    botões viram texto sem link.
    """
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "head", "title"]):
            tag.decompose()
        text = soup.get_text("\n")
    except Exception:  # noqa: BLE001 - fallback simples se o parser falhar
        text = re.sub(r"<[^>]+>", " ", html)
    out_lines, blanks = [], 0
    for raw in text.splitlines():
        line = raw.strip()
        if line:
            out_lines.append(line)
            blanks = 0
        elif blanks == 0:
            out_lines.append("")
            blanks = 1
    return "\n".join(out_lines).strip()


def subject_for(out: dict, template_subject: str) -> str:
    """Assunto fixo do config (se houver) ou o extraído do template .txt."""
    fixed = str(out.get("subject", "") or "").strip()
    return fixed or template_subject
