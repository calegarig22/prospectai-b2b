"""Cifragem simétrica de segredos sensíveis (ex.: senha de app SMTP por vendedor).

A senha de envio precisa ser RECUPERÁVEL (para autenticar no SMTP), então não dá
para "hashear". Aqui ela é cifrada com **Fernet** (AES, da lib `cryptography`),
usando a chave em ``EMAIL_ENC_KEY`` (Secrets/env). No banco fica só o texto cifrado.

Sem a chave OU sem a lib instalada, a cifragem fica INDISPONÍVEL — o app avisa e
NÃO guarda nada em texto puro. Gere a chave uma vez com ``Fernet.generate_key()``
e coloque em EMAIL_ENC_KEY nas variáveis secretas do servidor.
"""

from __future__ import annotations

import os


def _key() -> bytes:
    return (os.environ.get("EMAIL_ENC_KEY", "") or "").strip().encode()


def available() -> bool:
    """True se há chave válida E a lib cryptography está instalada."""
    k = _key()
    if not k:
        return False
    try:
        from cryptography.fernet import Fernet
        Fernet(k)            # valida o formato da chave (32 bytes base64 url-safe)
        return True
    except Exception:        # noqa: BLE001 - sem lib ou chave inválida = indisponível
        return False


def encrypt(plaintext: str) -> str:
    """Cifra um texto. Lança se a cifragem não estiver disponível (proposital:
    nunca grava segredo em claro)."""
    from cryptography.fernet import Fernet
    return Fernet(_key()).encrypt((plaintext or "").encode()).decode()


def decrypt(token: str) -> str:
    """Decifra um texto cifrado. Devolve '' se o token for vazio/ inválido."""
    if not token:
        return ""
    try:
        from cryptography.fernet import Fernet
        return Fernet(_key()).decrypt(token.encode()).decode()
    except Exception:        # noqa: BLE001 - token inválido/chave trocada = vazio
        return ""
