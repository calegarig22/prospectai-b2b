"""Funções utilitárias compartilhadas.

Sem dependências externas: usa apenas a biblioteca padrão para garantir
portabilidade e funcionamento offline da lógica que não precisa de rede.
"""

from __future__ import annotations

import unicodedata
from urllib.parse import urlparse


def strip_accents(text: str) -> str:
    """Remove acentos de um texto (ex.: ``refeição`` -> ``refeicao``).

    Usado para tornar a busca de palavras-chave insensível a acentuação, de modo
    que termos em português casem mesmo quando o site varia o uso de acentos.
    """
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_domain(url: str) -> str:
    """Extrai e normaliza o domínio de uma URL.

    Remove o esquema, o prefixo ``www.`` e a porta, retornando algo como
    ``empresa.com``. Usado como chave de deduplicação.

    Retorna string vazia quando a URL é inválida ou ausente.
    """
    if not url:
        return ""

    candidate = url.strip()
    # urlparse precisa de um esquema para preencher netloc corretamente.
    if "://" not in candidate:
        candidate = "http://" + candidate

    netloc = urlparse(candidate).netloc.lower()
    if not netloc:
        return ""

    # Remove credenciais e porta, se houver (ex.: user:pass@host:8080).
    netloc = netloc.split("@")[-1].split(":")[0]

    if netloc.startswith("www."):
        netloc = netloc[4:]

    # Colapsa subdomínios que são claramente da MESMA empresa (versões/idiomas/loja),
    # para que a empresa NUNCA apareça duas vezes sob endereços diferentes.
    for sub in ("www2.", "ww2.", "loja.", "shop.", "store.", "portal.",
                "site.", "home.", "global.", "en.", "pt.", "br.", "m."):
        if netloc.startswith(sub) and netloc.count(".") >= 2:
            netloc = netloc[len(sub):]
            break

    return netloc


def company_name_from_domain(domain: str) -> str:
    """Deriva um nome de empresa legível a partir do domínio.

    Ex.: ``empresa-abc.com.br`` -> ``Empresa Abc``. É uma aproximação para a V1;
    versões futuras podem enriquecer o nome a partir do conteúdo do site.
    """
    if not domain:
        return ""

    label = domain.split(".")[0]
    words = label.replace("-", " ").replace("_", " ").split()
    return " ".join(word.capitalize() for word in words) if words else domain
