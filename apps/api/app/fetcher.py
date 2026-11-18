"""Acesso à homepage de cada empresa para enriquecer os dados.

Coleta o ``<title>``, a meta description e até N caracteres de texto visível.
Toda falha de rede é tratada de forma silenciosa (retorna conteúdo vazio com
``ok=False``), para que um site fora do ar não interrompa o pipeline.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .utils import normalize_domain

# Tags cujo conteúdo não é texto visível relevante e deve ser removido.
_NON_VISIBLE_TAGS = ["script", "style", "noscript", "template", "svg", "head"]
_WHITESPACE = re.compile(r"\s+")

# --- Proteção de saída (SSRF e exaustão de memória) --------------------------
# As URLs vêm de BUSCA NA WEB: quem escolhe o destino, no fim, é um terceiro.
_ESQUEMAS_OK = ("http", "https")
_MAX_BYTES = 3 * 1024 * 1024      # 3 MB por página: título/description/texto cabem folgado
_MAX_REDIRECTS = 4


_host_cache: dict[str, bool] = {}


def _ip_interno(host: str) -> bool:
    """O host aponta para a rede interna, loopback ou metadata da nuvem?

    Resolve o nome antes de decidir: um domínio comum pode apontar para
    127.0.0.1 ou 169.254.169.254 de propósito (DNS rebinding simples).
    Falha de resolução devolve True — não vale arriscar num destino que nem
    resolve, e o pipeline trata a recusa como site fora do ar.
    """
    host = (host or "").strip().strip(".").lower()
    if not host:
        return True
    # Um lead rende ~10 páginas do MESMO host (contato, sobre, equipe, serviços):
    # sem cache, cada uma pagaria a resolução de novo.
    if host in _host_cache:
        return _host_cache[host]
    veredito = True
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:  # noqa: BLE001 - não resolveu: trata como inacessível
        infos = []
    if infos:
        veredito = False
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except ValueError:
                veredito = True
                break
            if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                    or ip.is_multicast or ip.is_unspecified):
                veredito = True
                break
    _host_cache[host] = veredito
    return veredito


def destino_publico(url: str) -> bool:
    """Só http(s) para host PÚBLICO. É o portão de saída do pipeline.

    Sem isto, um site de lead responde 302 para ``169.254.169.254`` e o servidor
    busca o metadata da instância na nuvem — o clássico SSRF por redirecionamento.
    """
    try:
        p = urlparse(url)
    except Exception:  # noqa: BLE001
        return False
    if p.scheme.lower() not in _ESQUEMAS_OK:
        return False
    return not _ip_interno(p.hostname or "")


def _get_seguro(url: str, timeout: int, headers: dict, logger: logging.Logger):
    """GET que valida CADA salto de redirecionamento e limita o corpo lido.

    ``allow_redirects=True`` do requests seguiria o 302 sem passar pela validação
    — a requisição interna já teria acontecido. Por isso os saltos são seguidos
    à mão. O corpo é lido em pedaços com teto: ``response.text`` traria um
    arquivo de 5 GB inteiro para a memória, e o pipeline roda 20 páginas em
    paralelo.
    """
    atual = url
    for _ in range(_MAX_REDIRECTS + 1):
        if not destino_publico(atual):
            logger.debug("Destino recusado (host interno ou esquema inválido): %s", atual)
            return None
        resp = requests.get(atual, timeout=timeout, headers=headers,
                            allow_redirects=False, stream=True)
        if resp.is_redirect or resp.is_permanent_redirect:
            proximo = resp.headers.get("Location") or ""
            resp.close()
            if not proximo:
                return None
            atual = requests.compat.urljoin(atual, proximo)
            continue
        resp.raise_for_status()
        # Lê com teto. decode_content=True desfaz o gzip — um corpo comprimido
        # pequeno que explode ao descomprimir para dentro do limite.
        try:
            bruto = resp.raw.read(_MAX_BYTES + 1, decode_content=True) or b""
        finally:
            # FECHAR é obrigatório com stream=True. Sem isto a conexão fica presa
            # até o GC, o pool do urllib3 (10 por host) esgota e os 20 workers do
            # pipeline passam a esperar vaga — o tempo por empresa dobra.
            resp.close()
        if len(bruto) > _MAX_BYTES:
            logger.debug("Página acima de %d bytes, truncada: %s", _MAX_BYTES, atual)
            bruto = bruto[:_MAX_BYTES]
        resp._content = bruto          # noqa: SLF001 - alimenta .text/.apparent_encoding
        resp._content_consumed = True  # noqa: SLF001
        return resp
    logger.debug("Redirecionamentos demais em %s", url)
    return None


@dataclass
class PageContent:
    """Conteúdo extraído de uma homepage."""

    ok: bool
    title: str = ""
    description: str = ""
    text: str = ""
    error: str = ""


@dataclass
class FetchedPage:
    """Página baixada com HTML cru (para descoberta de links) e texto visível."""

    ok: bool
    final_url: str = ""
    html: str = ""
    text: str = ""
    lang: str = ""
    error: str = ""


def homepage_url(url: str) -> str:
    """Reduz uma URL qualquer à raiz da homepage (esquema + domínio)."""
    domain = normalize_domain(url)
    if not domain:
        return ""
    parsed = urlparse(url if "://" in url else "https://" + url)
    scheme = parsed.scheme or "https"
    return f"{scheme}://{domain}/"


def _extract_description(soup: BeautifulSoup) -> str:
    """Lê a meta description (ou og:description como alternativa)."""
    for attrs in ({"name": "description"}, {"property": "og:description"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content"):
            return tag["content"].strip()
    return ""


def _extract_visible_text(soup: BeautifulSoup, max_chars: int) -> str:
    """Remove tags não visíveis e devolve o texto colapsado, limitado a N chars."""
    for tag in soup(_NON_VISIBLE_TAGS):
        tag.decompose()
    text = soup.get_text(separator=" ")
    text = _WHITESPACE.sub(" ", text).strip()
    return text[:max_chars]


def fetch_homepage(
    url: str,
    timeout: int = 10,
    max_chars: int = 10000,
    user_agent: str = "Mozilla/5.0 (compatible; ProspectAI/1.0)",
    logger: logging.Logger | None = None,
) -> PageContent:
    """Baixa a homepage e extrai title, description e texto visível."""
    log = logger or logging.getLogger("prospectai")
    target = homepage_url(url)
    if not target:
        return PageContent(ok=False, error="URL inválida")

    try:
        response = _get_seguro(
            target, timeout,
            {"User-Agent": user_agent, "Accept-Language": "en,pt;q=0.8"}, log)
        if response is None:
            return PageContent(ok=False, error="destino recusado ou inacessível")
    except Exception as error:  # noqa: BLE001 - site quebrado (até redirect malformado) nunca derruba o lote
        log.debug("Falha ao acessar %s: %s", target, error)
        return PageContent(ok=False, error=str(error))

    soup = BeautifulSoup(response.text, "lxml")

    title = soup.title.get_text(strip=True) if soup.title else ""
    description = _extract_description(soup)
    text = _extract_visible_text(soup, max_chars)

    return PageContent(ok=True, title=title, description=description, text=text)


def fetch_page(
    url: str,
    timeout: int = 10,
    max_chars: int = 10000,
    user_agent: str = "Mozilla/5.0 (compatible; ProspectAI/1.0)",
    logger: logging.Logger | None = None,
) -> FetchedPage:
    """Baixa uma página arbitrária e devolve HTML cru + texto visível.

    Diferente de ``fetch_homepage``, preserva o HTML para que a etapa de
    enriquecimento (V1.3) possa descobrir links internos (Contact/About/etc.).
    Aceita a URL exata informada (não a reduz à raiz do domínio).
    """
    log = logger or logging.getLogger("prospectai")
    target = url if "://" in (url or "") else ("https://" + url if url else "")
    if not target:
        return FetchedPage(ok=False, error="URL inválida")

    try:
        response = _get_seguro(
            target, timeout,
            {"User-Agent": user_agent, "Accept-Language": "en,pt;q=0.8"}, log)
        if response is None:
            return FetchedPage(ok=False, error="destino recusado ou inacessível")
    except Exception as error:  # noqa: BLE001 - site quebrado (até redirect malformado) nunca derruba o lote
        log.debug("Falha ao acessar %s: %s", target, error)
        return FetchedPage(ok=False, error=str(error))

    html = response.text
    soup = BeautifulSoup(html, "lxml")
    lang = ""
    if soup.html and soup.html.get("lang"):
        lang = str(soup.html.get("lang")).strip()
    text = _extract_visible_text(soup, max_chars)

    return FetchedPage(ok=True, final_url=str(response.url), html=html, text=text, lang=lang)
