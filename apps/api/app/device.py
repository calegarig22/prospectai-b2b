"""Identifica o dispositivo de origem da geração de leads pelo User-Agent.

Usado pelo painel para marcar de qual aparelho cada lote foi gerado. Vai além do
"celular vs note": distingue iPhone, iPad, Android, Mac, Windows e Linux.
"""

from __future__ import annotations

COMPUTADOR = "Computador"


def classify_device(user_agent: str | None) -> str:
    """Retorna um rótulo legível do aparelho a partir do User-Agent.

    Ex.: ``iPhone``, ``iPad``, ``Android``, ``Mac``, ``Windows``, ``Linux``.
    Sem User-Agent (execução automática/agendada, sem navegador) -> ``Computador``.
    """
    ua = (user_agent or "").lower()
    if not ua:
        return COMPUTADOR
    if "iphone" in ua or "ipod" in ua:
        return "iPhone"
    if "ipad" in ua:
        return "iPad"
    if "android" in ua:
        return "Android" if "mobile" in ua else "Android (tablet)"
    if "windows phone" in ua or "iemobile" in ua:
        return "Windows Phone"
    if "windows" in ua:
        return "Windows"
    if "macintosh" in ua or "mac os" in ua:
        # iPad/iPhone recente pode se anunciar como "Macintosh"; toque/mobile desempata.
        if "mobile" in ua or "touch" in ua:
            return "iPad"
        return "Mac"
    if "cros" in ua:
        return "Chromebook"
    if "linux" in ua:
        return "Linux"
    if any(sig in ua for sig in ("mobile", "tablet", "phone")):
        return "Celular"
    return COMPUTADOR


def is_mobile(device: str | None) -> bool:
    """True se o aparelho é móvel (celular/tablet) — útil p/ ajustes de layout."""
    d = (device or "").lower()
    return any(sig in d for sig in ("iphone", "ipad", "android", "celular", "phone", "tablet"))
