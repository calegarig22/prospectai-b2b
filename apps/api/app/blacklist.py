"""Filtragem de domínios irrelevantes (blacklist).

Descarta imediatamente enciclopédias, buscadores, redes sociais, marketplaces,
diretórios e agregadores genéricos — fontes que não representam uma empresa
real com potencial de compra.
"""

from __future__ import annotations

import re

from .utils import strip_accents

import logging

from .models import Lead
from .utils import normalize_domain


def matched_blacklist_entry(domain: str, blacklist: list[str]) -> str | None:
    """Retorna a entrada da blacklist que casa com o domínio, ou ``None``.

    O casamento cobre subdomínios: ``en.wikipedia.org`` casa com
    ``wikipedia.org``.
    """
    domain = (domain or "").lower()
    if not domain:
        return None

    for entry in blacklist:
        clean = entry.lower().lstrip(".")
        if domain == clean or domain.endswith("." + clean):
            return entry
    return None


def filter_blacklist(
    leads: list[Lead],
    blacklist: list[str],
    logger: logging.Logger | None = None,
) -> tuple[list[Lead], list[tuple[Lead, str]]]:
    """Separa os leads em (mantidos, descartados).

    Cada descartado vem acompanhado da entrada da blacklist que o eliminou,
    para que o relatório final possa explicar o motivo.
    """
    log = logger or logging.getLogger("prospectai")

    kept: list[Lead] = []
    discarded: list[tuple[Lead, str]] = []

    for lead in leads:
        domain = normalize_domain(lead.website)
        entry = matched_blacklist_entry(domain, blacklist)
        if entry:
            discarded.append((lead, entry))
        else:
            kept.append(lead)

    log.info(
        "Blacklist: %d mantido(s), %d descartado(s) de %d.",
        len(kept), len(discarded), len(leads),
    )
    return kept, discarded


# ---------------------------------------------------------------------------
# Portal de notícia disfarçado de empresa
# ---------------------------------------------------------------------------
# Achado em produção: portais de notícia do setor do cliente entraram como leads.
# Falam do assunto do nicho o dia inteiro, então passam por qualquer filtro de
# palavra-chave. Bloquear domínio a domínio não
# escala: aparecem portais novos toda semana.
#
# O que os denuncia é a ESTRUTURA: muitas datas, assinatura de redação, paginação
# e verbos de cobertura jornalística. Uma empresa comum tem 1 ou 2 datas no site
# inteiro; um portal tem dezenas.

_MARCAS_JORNALISTICAS = (
    "posted by", "por redacao", "redacao", "leia mais", "leia tambem",
    "compartilhe", "publicado em", "ultimas noticias", "editoria",
    "arquivo do autor", "categoria:", "tags:", "proxima pagina",
    "deixe um comentario", "assine a newsletter",
)
_DATA_RE = re.compile(r"\b\d{1,2}/\d{1,2}/20\d{2}\b|\bde\s+\w+\s+de\s+20\d{2}\b")


def parece_portal_de_noticia(texto: str) -> bool:
    """True quando o conteúdo é de portal/blog jornalístico, não de empresa.

    Exige DOIS sinais independentes — só datas não basta (uma empresa comum pode
    ter um blog), e só uma marca isolada também não. Juntos, o falso positivo
    fica raro.
    """
    t = strip_accents((texto or "").lower())
    if not t:
        return False
    datas = len(_DATA_RE.findall(t))
    marcas = sum(1 for m in _MARCAS_JORNALISTICAS if m in t)
    # Dois caminhos, porque nem todo portal usa as mesmas marcas. Medido em sites
    # reais: empresa comum tem ~3 datas no site inteiro; portal tem 31 e 47.
    #   - poucas datas + marcas de redação  -> portal com assinatura jornalística
    #   - MUITAS datas                      -> portal sem marca (feed de manchetes)
    return (datas >= 6 and marcas >= 2) or datas >= 15
