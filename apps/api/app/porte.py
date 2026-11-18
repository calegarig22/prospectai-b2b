"""Porte do lead: o tamanho que ele mesmo publica e a classificação da empresa.

Duas fontes, nessa ordem:
  1. O número que a empresa publica ("rede com 40 lojas", "120 unidades"). As
     palavras que contam vêm do nicho (``porte.unidades`` e ``porte.contexto``).
  2. Os dados abertos da Receita (capital social + porte). Cobre quem não
     divulga números, que é a maioria — vale para qualquer nicho no Brasil.
"""

from __future__ import annotations

import re

from . import nicho as _nicho

# Acima disso quase certamente não é porte (CEP, telefone, valor).
_TETO_PLAUSIVEL = 20000
# Abaixo disso não diz nada útil sobre porte.
_PISO_PLAUSIVEL = 2
# ANOS disfarçados de quantidade: "...de agosto de 2026 | 12 unidades" virava 2026.
_FAIXA_ANO = range(1900, 2101)
_CONTEXTO_DATA = re.compile(
    r"(\d{1,2}/\d{1,2}/|\bde\s+(janeiro|fevereiro|marco|abril|maio|junho|julho|"
    r"agosto|setembro|outubro|novembro|dezembro)\s+de\s*$)")


def _alternativas(termos) -> str:
    return "|".join(re.escape(_nicho.norm(t)) for t in termos if t)


def detectar_numero(texto: str, cfg: _nicho.Porte | None = None) -> int:
    """Maior quantidade declarada no texto (0 quando a empresa não publica).

    Pega o MAIOR e não o primeiro: sites citam o total num lugar e recortes em
    outros ("3 unidades no centro", "rede com 40 lojas"). O total é o que qualifica.
    """
    cfg = cfg or _nicho.ativo().porte
    if not cfg.ativo:
        return 0
    blob = _nicho.norm(texto)
    padroes = []
    if cfg.unidades:            # "40 lojas", "120 unidades"
        padroes.append(re.compile(rf"\b(\d{{1,5}})\s+(?:{_alternativas(cfg.unidades)})\b"))
    if cfg.contexto:            # "rede de 40", "rede com mais de 12"
        padroes.append(re.compile(
            rf"(?:{_alternativas(cfg.contexto)})[^.\n]{{0,25}}?\b(\d{{1,5}})\b"))
    achados: list[int] = []
    for padrao in padroes:
        for m in padrao.finditer(blob):
            n = int(m.group(1))
            if not (_PISO_PLAUSIVEL <= n <= _TETO_PLAUSIVEL) or n in _FAIXA_ANO:
                continue
            if _CONTEXTO_DATA.search(blob[max(0, m.start(1) - 30):m.start(1)]):
                continue            # o número está dentro de uma data
            achados.append(n)
    return max(achados) if achados else 0


def classificar(numero: int = 0, capital_social: float = 0.0, porte_receita: str = "",
                cfg: _nicho.Porte | None = None) -> str:
    """Grande / Média / Pequena. Vazio se não há base nenhuma.

    O número publicado manda quando existe (é o dado do negócio). Sem ele, o
    capital social da Receita é o melhor substituto público disponível.
    """
    cfg = cfg or _nicho.ativo().porte
    if numero:
        if numero >= cfg.grande_a_partir_de:
            return "Grande"
        if numero >= cfg.media_a_partir_de:
            return "Média"
        return "Pequena"
    p = _nicho.norm(porte_receita).upper()
    if capital_social >= 10_000_000:
        return "Grande"
    if capital_social >= 1_000_000:
        return "Média"
    if "MICRO EMPRESA" in p or "PEQUENO PORTE" in p:
        return "Pequena"
    if capital_social >= 100_000:
        return "Média"
    if capital_social > 0:
        return "Pequena"
    # "DEMAIS" na Receita = "nem micro nem pequena": sinal fraco demais para "Grande".
    if "DEMAIS" in p:
        return "Média"
    return ""


def rotulo(numero: int, porte: str, cfg: _nicho.Porte | None = None) -> str:
    """Texto curto para a planilha e a tela: '40 lojas' ou só o porte."""
    cfg = cfg or _nicho.ativo().porte
    return f"{numero} {cfg.rotulo}" if numero else (porte or "")
