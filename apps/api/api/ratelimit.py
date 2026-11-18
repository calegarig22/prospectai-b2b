"""Limite de tentativas em memória para as rotas públicas (login, reset, bootstrap).

Complementa o bloqueio POR CONTA que já existe em app/users.py (5 senhas
erradas = 5 min): aquele protege uma conta; este segura quem testa muitas
contas a partir do mesmo lugar. Em memória basta — a API roda numa instância
só, e reiniciar zera a contagem, o que só favorece o usuário legítimo.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

_hits: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


def client_ip(request: Request) -> str:
    # Atrás do proxy da Vercel o IP real vem no 1º item do X-Forwarded-For.
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def limit(request: Request, bucket: str, max_hits: int, window_s: int) -> None:
    key = f"{bucket}:{client_ip(request)}"
    now = time.monotonic()
    with _lock:
        q = _hits[key]
        while q and now - q[0] > window_s:
            q.popleft()
        if len(q) >= max_hits:
            espera = int(window_s - (now - q[0])) + 1
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                f"Muitas tentativas. Aguarde {espera}s.")
        q.append(now)


def reset_all() -> None:
    """Só para testes."""
    with _lock:
        _hits.clear()
