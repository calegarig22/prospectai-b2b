"""Pontuação de propensão a comprar o que o cliente vende (pesos vêm do nicho).

A pontuação soma pesos de três categorias (sinais de necessidade, segmentos e
tipo de empresa) encontrados no conteúdo textual do lead. O resultado classifica
a empresa em HOT, WARM ou COLD conforme os limiares configurados.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .utils import strip_accents

# Ordem de avaliação das categorias (afeta apenas a apresentação no relatório).
_CATEGORY_ORDER = ["needs", "segments", "company_types"]


@dataclass
class ScoreResult:
    """Resultado da pontuação de um lead."""

    score: int
    classification: str
    keywords_found: list[str]


def classify(score: int, hot: int, warm: int) -> str:
    """Converte um score numérico em HOT / WARM / COLD."""
    if score >= hot:
        return "HOT"
    if score >= warm:
        return "WARM"
    return "COLD"


def score_text(text: str, scoring_config: dict[str, Any]) -> ScoreResult:
    """Pontua um bloco de texto segundo as regras de ``scoring_config``.

    O casamento é por substring, em minúsculas. Cada palavra-chave encontrada
    soma seu peso uma única vez e é registrada em ``keywords_found``.
    """
    # Normaliza para minúsculas e sem acento, tornando o casamento insensível a
    # acentuação (ex.: "refeição" == "refeicao").
    blob = strip_accents((text or "").lower())
    hot = scoring_config.get("hot_threshold", 80)
    warm = scoring_config.get("warm_threshold", 50)
    max_score = scoring_config.get("max_score", 100)

    raw = 0
    found: list[str] = []

    def _hit(term_norm: str) -> bool:
        # Limite de palavra evita falso-positivo de substring ("mining" em "examining",
        # "duplex" em "duplexer"). Frases (com espaço) casam por substring (já seguro).
        return bool((term_norm in blob) if " " in term_norm else re.search(r"\b" + re.escape(term_norm) + r"\b", blob))

    needs_hit = False
    for category in _CATEGORY_ORDER:
        weights: dict[str, int] = scoring_config.get(category, {}) or {}
        for keyword, weight in weights.items():
            if _hit(strip_accents(keyword.lower())):
                raw += int(weight)
                found.append(keyword)
                if category == "needs":
                    needs_hit = True

    # CONCORRENTES: quem JÁ VENDE o que o cliente vende não é comprador -> PENALIDADE
    # (peso negativo). Fora de keywords_found p/ não poluir a detecção de necessidade.
    for keyword, weight in (scoring_config.get("competitors", {}) or {}).items():
        if _hit(strip_accents(keyword.lower())):
            raw += int(weight)

    # Normaliza para a faixa 0-100 (teto configurável). Clampa em 0 (penalidades
    # de concorrente podem levar a soma a negativo).
    score = max(0, min(raw, max_score))
    classification = classify(score, hot, warm)
    # QUALIFICAÇÃO: exige ao menos um SINAL DE NECESSIDADE do nicho. Só o setor
    # pontuar não basta — sem evidência de necessidade não é comprador -> COLD.
    # Desligável no nicho (pontuacao.exige_sinal_de_necessidade: false).
    if scoring_config.get("require_need_signal", True) and not needs_hit:
        classification = "COLD"
    return ScoreResult(score=score, classification=classification, keywords_found=found)
