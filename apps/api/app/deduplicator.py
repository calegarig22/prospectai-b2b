"""Remoção de duplicidades entre leads.

Dois resultados são considerados a mesma empresa quando compartilham o mesmo
domínio normalizado (ex.: ``http://www.acme.com/a`` e ``https://acme.com/b``).
O primeiro lead encontrado para cada domínio é mantido.
"""

from __future__ import annotations

import logging

from .models import Lead
from .utils import normalize_domain


def deduplicate(leads: list[Lead], logger: logging.Logger | None = None) -> list[Lead]:
    """Devolve a lista de leads sem domínios repetidos, preservando a ordem."""
    log = logger or logging.getLogger("prospectai")

    seen: set[str] = set()
    unique: list[Lead] = []

    for lead in leads:
        # Quando não há domínio extraível, usa a URL bruta como chave de fallback.
        key = normalize_domain(lead.website) or lead.website.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(lead)

    removed = len(leads) - len(unique)
    log.info("Deduplicação: %d entrada(s) -> %d única(s) (%d removida(s)).", len(leads), len(unique), removed)
    return unique
