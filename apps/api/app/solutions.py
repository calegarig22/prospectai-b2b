"""Identificação da NECESSIDADE: quais soluções do catálogo do cliente cabem no lead.

O catálogo e as pistas de cada solução vêm do nicho (``app/nicho.py``). O texto
do lead quase nunca cita o produto pelo nome — ele cita a OPERAÇÃO ("cozinha
industrial", "rede com 12 unidades"). As pistas são essas palavras de operação,
e o que volta é o rótulo do produto do cliente.
"""

from __future__ import annotations

from . import nicho as _nicho


def detect_solutions(text: str, n: _nicho.Nicho | None = None) -> list[str]:
    """Soluções que o conteúdo justifica, sem repetir, na ordem do catálogo."""
    n = n or _nicho.ativo()
    blob = _nicho.norm(text)
    found = {s.nome for s in n.solucoes
             if any(_nicho.casa(_nicho.norm(t), blob) for t in s.sinais)}
    # "oculta_se": um item que já vem incluído em outro não é oferecido duas vezes.
    escondidas = {s.nome for s in n.solucoes if s.nome in found
                  and any(o in found for o in s.oculta_se)}
    return [s.nome for s in n.solucoes if s.nome in found - escondidas]
