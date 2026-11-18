"""Validação de e-mails ANTES do envio — corta bounces (gatilho nº1 de suspensão).

Endereços inválidos (domínio que não existe, typos, caixas técnicas) geram bounce.
Bounce alto é o que faz o Gmail/Workspace marcar o remetente como abusivo e suspender
a conta. Esta etapa descarta o que tem grande chance de não chegar.

O que é checado, em ordem:
  1. Sintaxe (regex conservadora).
  2. Caixas técnicas/sem-dono que não fazem sentido p/ contato comercial
     (noreply, postmaster, mailer-daemon, abuse...). NÃO descarta contato@/info@,
     que costumam ser justamente o alvo do cold outreach.
  3. Existência do domínio: registro MX (via ``dnspython``) ou, se a lib não estiver
     instalada, registro A (fallback por socket).

Filosofia: falha "fechada" só quando há CERTEZA (sintaxe ruim ou domínio inexistente).
Em dúvida de rede (timeout de DNS, etc.), DEIXA PASSAR — não vale descartar um bom
lead por uma instabilidade momentânea de resolução.
"""

from __future__ import annotations

import re

# Sintaxe conservadora (suficiente p/ pegar typos óbvios sem rejeitar válidos raros).
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

# Caixas que NÃO recebem contato comercial (envio é desperdício/bounce certo).
_BLOCKED_LOCAL = {
    "noreply", "no-reply", "no_reply", "donotreply", "do-not-reply",
    "postmaster", "mailer-daemon", "mailerdaemon", "abuse", "bounce",
    "bounces", "unsubscribe", "remove",
}

# Cache por execução: domínio -> True (aceita) / False (não existe) / None (incerto).
_mx_cache: dict[str, bool | None] = {}


def valid_syntax(email: str) -> bool:
    """True se o e-mail passa na checagem de sintaxe."""
    return bool(_EMAIL_RE.match((email or "").strip()))


def _domain_accepts_mail(domain: str) -> bool | None:
    """True se o domínio tem MX/A; False se não existe; None se não dá p/ saber.

    Usa ``dnspython`` quando disponível (checa MX e, na ausência, A). Sem a lib,
    cai num fallback por socket (resolve o A do domínio). Erros de rede => None.
    """
    domain = domain.lower().strip()
    if not domain:
        return False
    if domain in _mx_cache:
        return _mx_cache[domain]

    result: bool | None
    try:
        import dns.resolver  # type: ignore

        try:
            answers = dns.resolver.resolve(domain, "MX")
            result = len(answers) > 0
        except dns.resolver.NoAnswer:
            # Sem MX: pelo RFC 5321, o A do domínio pode receber e-mail.
            try:
                dns.resolver.resolve(domain, "A")
                result = True
            except Exception:  # noqa: BLE001
                result = False
        except dns.resolver.NXDOMAIN:
            result = False  # domínio não existe -> bounce garantido
        except Exception:  # noqa: BLE001 - timeout, sem servidor, etc.
            result = None   # incerto: não descarta
    except ImportError:
        # dnspython NÃO está no requirements deste projeto — e por isso esta função
        # devolvia "incerto" para tudo, silenciosamente: a validação de MX do
        # disparo nunca rodou de verdade e e-mails para domínios inexistentes
        # saíam, gerando bounce e queimando a reputação do remetente.
        # O caminho abaixo é o MESMO que o pipeline já usa (DNS sobre HTTPS via
        # requests, que é dependência declarada), então funciona sem lib nova.
        result = _mx_por_doh(domain)

    _mx_cache[domain] = result
    return result


def _mx_por_doh(domain: str) -> bool | None:
    """MX via DNS-over-HTTPS (Cloudflare). True/False/None (incerto).

    Só afirma que o domínio NÃO recebe e-mail quando a resposta é clara
    (NXDOMAIN, ou sem MX e sem A). Qualquer falha de rede devolve None, para
    nunca recusar um endereço bom por causa de instabilidade.
    """
    try:
        import requests
        resp = requests.get("https://cloudflare-dns.com/dns-query",
                            params={"name": domain, "type": "MX"},
                            headers={"Accept": "application/dns-json"}, timeout=4)
        if not resp.ok:
            return None
        dados = resp.json()
        if dados.get("Status") == 3:            # NXDOMAIN: o domínio não existe
            return False
        if dados.get("Status") not in (0, None):
            return None
        if any(a.get("type") == 15 for a in (dados.get("Answer") or [])):
            return True
        # Sem MX: pelo RFC 5321 o A do domínio ainda pode receber e-mail.
        resp_a = requests.get("https://cloudflare-dns.com/dns-query",
                              params={"name": domain, "type": "A"},
                              headers={"Accept": "application/dns-json"}, timeout=4)
        if not resp_a.ok:
            return None
        dados_a = resp_a.json()
        if dados_a.get("Status") == 3:
            return False
        return bool(dados_a.get("Answer")) or False
    except Exception:  # noqa: BLE001 - rede instável nunca recusa endereço bom
        return None


def check(email: str, *, check_mx: bool = True) -> tuple[bool, str]:
    """Decide se vale a pena enviar. Retorna ``(ok, motivo_se_recusado)``."""
    email = (email or "").strip()
    if not valid_syntax(email):
        return False, "sintaxe inválida"
    local, _, domain = email.lower().partition("@")
    if local in _BLOCKED_LOCAL:
        return False, "caixa técnica (não recebe contato)"
    if check_mx:
        accepts = _domain_accepts_mail(domain)
        if accepts is False:
            return False, "domínio sem e-mail (não existe)"
        # accepts True ou None (incerto) -> deixa passar
    return True, ""


def filter_sendable(emails: list[str], *, check_mx: bool = True) -> tuple[list[str], list[tuple[str, str]]]:
    """Separa uma lista em ``(enviáveis, [(email, motivo_recusado), ...])``."""
    ok: list[str] = []
    dropped: list[tuple[str, str]] = []
    for email in emails:
        valid, reason = check(email, check_mx=check_mx)
        (ok if valid else dropped).append(email if valid else (email, reason))  # type: ignore[arg-type]
    return ok, dropped
