"""Enriquecimento de um lead.

Acessa a homepage, descobre e visita as páginas Contato / Sobre / Locais /
Operação, extrai contatos públicos, detecta país, cidade e idioma, identifica
as soluções do nicho, o decisor e o porte, e classifica o potencial de compra.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin

from html import unescape as html_unescape

from bs4 import BeautifulSoup

from .contacts import (extract_email, extract_emails_ranked, extract_phone,
                       promover_decisor, rotulo_email, temperatura_email)
from .fetcher import fetch_page
from .geo_lang import count_countries, detect_city_consistent, detect_country, detect_language
from .decisor import _LINKEDIN_RE, find_decisor
from . import nicho as _nicho
from . import porte as _porte
from .solutions import detect_solutions
from .models import HotLead, Lead
from .utils import normalize_domain, strip_accents

# Palavras (multilíngues) que identificam cada tipo de página interna.
_PAGE_KEYWORDS = {
    "contact": ["contact", "contato", "contacto", "kontakt", "contatti", "contactez"],
    "about": ["about", "sobre", "quienes-somos", "quem-somos", "uber-uns", "ueber-uns",
              "chi-siamo", "a-propos", "propos", "company", "empresa", "about-us"],
    "locations": ["location", "standort", "ubicacion", "localizacao", "filiali",
                  "find-us", "offices", "where-to-buy", "global-network"],
    # A "página de produto" do lead é a que descreve a OPERAÇÃO dele. Estas são as
    # genéricas; as do nicho (busca.paginas_operacao) entram em _paginas_operacao().
    "products": ["servico", "serviços", "servicos", "solucoes", "soluções", "product",
                 "produto", "unidades", "atuacao", "atuação"],
    # Páginas onde o DECISOR costuma aparecer com nome e cargo.
    "team": ["equipe", "time", "diretoria", "nossa-equipe", "quem-faz", "gestao",
             "gestão", "governanca", "lideranca", "liderança", "team", "management"],
}

def _paginas_operacao() -> list[str]:
    return _PAGE_KEYWORDS["products"] + [p.lower() for p in _nicho.ativo().paginas_operacao]


# Sinais de presença internacional (ExportPotential).
_EXPORT_SIGNALS = [
    "global", "worldwide", "international", "export", "overseas", "multinational",
    "subsidiaries", "distributors", "offices in", "around the world", "five continents",
    "exportacao", "exportacion", "weltweit", "internacional", "mundial", "filiais",
]


# --- Dados OFICIAIS da Receita Federal (gratuito, sem chave) ------------------
_CNPJ_RE = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/\d{4}-\d{2}\b")
# CNPJ rotulado, com ou sem barra: "CNPJ: 12.345.678/0001-90" ou "CNPJ 12345678000190".
_CNPJ_LABEL_RE = re.compile(r"cnpj[^0-9]{0,10}(\d{2}[.\s]?\d{3}[.\s]?\d{3}[/.\s]?\d{4}[-.\s]?\d{2})", re.I)


def _find_cnpj(html: str) -> str:
    """Acha o CNPJ na página: formatado (barra) ou rotulado 'CNPJ ...'. Vazio se não houver."""
    for match in _CNPJ_RE.finditer(html or ""):
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) == 14 and len(set(digits)) > 1:
            return digits
    for match in _CNPJ_LABEL_RE.finditer(html or ""):
        digits = re.sub(r"\D", "", match.group(1))
        if len(digits) == 14 and len(set(digits)) > 1:
            return digits
    return ""


# minhareceita = dados abertos (sem limite estrito); BrasilAPI reserva.
_CNPJ_PROVIDERS = (
    "https://minhareceita.org/{cnpj}",
    "https://brasilapi.com.br/api/cnpj/v1/{cnpj}",
)
_CNPJ_SEM = threading.Semaphore(10)

# --- Verifica se o domínio ACEITA e-mail (tem servidor MX) via DNS-over-HTTPS ---
_MX_SEM = threading.Semaphore(20)
_mx_cache: dict[str, bool] = {}


def _domain_has_mx(domain: str) -> bool:
    """True se o domínio tem servidor de e-mail (MX). Usado para inferir contato@ confiável."""
    if not domain or "." not in domain:
        return False
    if domain in _mx_cache:
        return _mx_cache[domain]
    import requests
    has = False
    with _MX_SEM:
        try:
            resp = requests.get("https://cloudflare-dns.com/dns-query",
                                params={"name": domain, "type": "MX"},
                                headers={"Accept": "application/dns-json"}, timeout=4)
            if resp.ok:
                has = any(a.get("type") == 15 for a in (resp.json().get("Answer") or []))
        except Exception:  # noqa: BLE001 - sem MX confirmado, não infere
            has = False
    _mx_cache[domain] = has
    return has


def _email_has_mx(email: str) -> bool:
    """True se o DOMÍNIO do e-mail aceita mensagens (tem MX) — descarta endereço morto."""
    dom = email.split("@")[-1].strip().lower() if email and "@" in email else ""
    return _domain_has_mx(dom)


def _norm_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", strip_accents((text or "").lower()))


def _receita_lookup(cnpj: str) -> dict[str, str]:
    """Consulta a Receita (minhareceita -> BrasilAPI) e normaliza os campos. Robusto a rate-limit."""
    if len(cnpj) != 14 or len(set(cnpj)) <= 1:
        return {}
    import requests
    with _CNPJ_SEM:
        for url in _CNPJ_PROVIDERS:
            # FAIL-FAST: 1 tentativa por provedor, timeout curto. Se a API está lenta,
            # não vale travar o lote — os dados da própria página já cobrem o lead.
            try:
                resp = requests.get(url.format(cnpj=cnpj), timeout=6,
                                    headers={"User-Agent": "Mozilla/5.0"})
                if not resp.ok:          # inclui 429 -> tenta a próxima fonte, sem esperar
                    continue
                data = resp.json()
            except Exception:  # noqa: BLE001 - tenta a próxima fonte
                continue
            out: dict[str, str] = {}
            phone_off = (str(data.get("ddd_telefone_1") or "").strip()
                         or str(data.get("ddd_telefone_2") or "").strip())
            if phone_off:
                out["phone"] = phone_off
            if (data.get("email") or "").strip():
                out["email"] = str(data["email"]).strip().lower()
            if (data.get("municipio") or "").strip():
                out["city"] = str(data["municipio"]).strip().title()
            if (data.get("uf") or "").strip():
                out["uf"] = str(data["uf"]).strip()
            if (data.get("cnae_fiscal_descricao") or "").strip():
                out["sector"] = str(data["cnae_fiscal_descricao"]).strip()
            # Dados de PORTE e VIDA da empresa — já vinham na mesma resposta e eram
            # descartados. Capital social é o melhor substituto público do tamanho
            # quando a empresa não divulga números; situação cadastral evita
            # entregar empresa baixada como se estivesse operando.
            try:
                out["capital_social"] = float(data.get("capital_social") or 0)
            except (TypeError, ValueError):
                out["capital_social"] = 0.0
            if (data.get("porte") or "").strip():
                out["porte_receita"] = str(data["porte"]).strip()
            if (data.get("descricao_situacao_cadastral") or "").strip():
                out["situacao"] = str(data["descricao_situacao_cadastral"]).strip().title()
            if (data.get("data_inicio_atividade") or "").strip():
                out["desde"] = str(data["data_inicio_atividade"]).strip()[:4]
            out["_name"] = _norm_name(str(data.get("razao_social") or "") + str(data.get("nome_fantasia") or ""))
            # Nome COMERCIAL oficial (fantasia > razão social) — vira o nome exibido do
            # lead quando o derivado do domínio ficou esmagado ("Empresaexemplobrasil").
            legal = (str(data.get("nome_fantasia") or "").strip()
                     or str(data.get("razao_social") or "").strip())
            if legal:
                out["legal_name"] = legal.title()
            if any(k for k in out if k != "_name"):
                return out
    return {}


def _cnpj_official(html: str, logger: logging.Logger) -> dict[str, str]:
    """CNPJ encontrado NA PÁGINA -> dados oficiais da Receita."""
    cnpj = _find_cnpj(html) if html else ""
    result = _receita_lookup(cnpj) if cnpj else {}
    result.pop("_name", None)
    return result


# --- Nome de exibição da empresa ---------------------------------------------
# Separadores típicos de <title>: "Empresa Exemplo | Serviços e Soluções".
_TITLE_SPLIT = re.compile(r"\s+[|\u2013\u2014\-\u00b7:]\s+")
_TITLE_TAG_RE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
_OG_SITE_RE = re.compile(
    r"<meta[^>]+property=[\"']og:site_name[\"'][^>]+content=[\"']([^\"']+)[\"']", re.I)
# Ruído que costuma acompanhar o nome no <title> e não faz parte dele.
_NAME_NOISE = re.compile(
    r"(?i)\b(home|in[ií]cio|p[aá]gina inicial|bem[- ]vindos?|site oficial|oficial)\b")


# Títulos que descrevem o SERVIÇO, não a empresa — não servem como razão social.
# Genéricos aqui; os do nicho (busca.titulos_de_servico) entram em _e_titulo_de_servico().
_SERVICE_TITLE = re.compile(
    r"^(contrate|solicite|or\u00e7amento|orcamento|servicos? de|servi\u00e7os? de|"
    r"empresa de|agencia de|ag\u00eancia de|loja de|venda de|aluguel de|locacao de)\b")


def _e_titulo_de_servico(titulo_norm: str) -> bool:
    if _SERVICE_TITLE.match(titulo_norm):
        return True
    return any(titulo_norm.startswith(t) for t in _nicho.normalizados(_nicho.ativo().titulos_de_servico))


def _page_title(html: str) -> str:
    """Conteúdo da tag <title> da página (vazio se não houver)."""
    m = _TITLE_TAG_RE.search(html or "")
    return re.sub(r"\s+", " ", m.group(1)).strip() if m else ""


def _looks_squashed(name: str) -> bool:
    """True quando o nome veio do domínio e ficou colado ('Empresaexemplobrasil')."""
    n = (name or "").strip()
    return bool(n) and " " not in n and len(n) > 12


def _clean_company_name(candidate: str) -> str:
    """Normaliza um nome vindo do site: corta o slogan, o ruído e o excesso.

    Percorre os segmentos do título ("Home - Empresa Exemplo") e devolve o
    primeiro que sobrevive à limpeza — assim um "Home"/"Início" na frente não
    engole o nome real.
    """
    # O <title> vem com entidades HTML cruas ("Comércio &amp; Serviços").
    candidate = html_unescape(candidate or "")
    for seg in _TITLE_SPLIT.split(candidate.strip()):
        c = _NAME_NOISE.sub("", seg).strip(" -|\u2013\u2014\u00b7:,")
        c = re.sub(r"\s+", " ", c)
        if not (2 < len(c) <= 60):
            continue
        if not re.search(r"[A-Za-z\u00c0-\u00ff]", c):    # precisa ter letra
            continue
        if c.count(" ") > 7:                                # frase, não nome
            continue
        return c
    return ""


def _display_name(current: str, official: dict, html: str, title: str) -> str:
    """Melhor nome para exibir: Receita > og:site_name > <title> > derivado do domínio.

    Só substitui o nome atual quando ele veio esmagado do domínio — assim um nome
    bom vindo do resultado de busca nunca é piorado.
    """
    if not _looks_squashed(current):
        return current
    legal = (official or {}).get("legal_name", "")
    if legal:
        return _clean_company_name(legal) or current
    m = _OG_SITE_RE.search(html or "")
    if m:
        cand = _clean_company_name(m.group(1))
        if cand and _looks_squashed(cand) is False:
            return cand
    cand = _clean_company_name(title or "")
    # O <title> costuma ser DESCRITIVO ("Buffet para casamentos em Curitiba"). Isso é
    # serviço, não razão social — trocar o nome por ele piora a lista. Só aceitamos
    # títulos que não comecem por um termo de serviço.
    if cand and " " in cand and not _e_titulo_de_servico(strip_accents(cand.lower())):
        return cand
    return current


# Quando o site NÃO mostra o CNPJ: procura na web (diretórios públicos) e VALIDA por domínio/nome.
# 16 = o mesmo teto de leads em paralelo. Com 8, metade do lote ficava na fila
# esperando vaga para consultar CNPJ e o tempo por empresa dobrava.
_CNPJ_WEB_SEM = threading.Semaphore(16)


def _cnpjs_from_text(text: str, allow_bare: bool = False) -> list[str]:
    """CNPJs candidatos: formatado (com barra) e, opcionalmente, 14 dígitos (URLs de diretório)."""
    found: list[str] = []
    for match in _CNPJ_RE.finditer(text or ""):
        d = re.sub(r"\D", "", match.group(0))
        if len(d) == 14 and len(set(d)) > 1 and d not in found:
            found.append(d)
    if allow_bare:
        for match in re.finditer(r"\d{14}", text or ""):
            d = match.group(0)
            if len(set(d)) > 1 and d not in found:
                found.append(d)
    return found


def _web_search_backends(query: str, max_results: int = 8):
    """Gera os resultados de cada buscador gratuito (7 motores), um por vez.

    Tentar vários é essencial: os buscadores grátis oscilam — um devolve vazio/lixo e o
    outro acerta. O chamador para assim que extrair o dado válido.
    """
    try:
        from ddgs import DDGS
    except Exception:  # noqa: BLE001
        return

    def run(backend: str) -> list:
        try:
            with DDGS() as ddgs:
                return list(ddgs.text(query, backend=backend, max_results=max_results))
        except Exception:  # noqa: BLE001
            return []

    # Os motores EM PARALELO; entrega cada resultado não-vazio assim que chega
    # (o chamador para no primeiro que serve).
    _MOTORES = ("duckduckgo", "google", "brave", "mojeek", "startpage", "yahoo", "yandex")
    ex = ThreadPoolExecutor(max_workers=len(_MOTORES))
    try:
        futures = [ex.submit(run, b) for b in _MOTORES]
        for fut in as_completed(futures):
            results = fut.result()
            if results:
                yield results
    finally:
        # NÃO usar `with`: ao sair do bloco ele faz shutdown(wait=True) e espera os
        # motores restantes MESMO quando o chamador já achou o dado no primeiro —
        # o custo virava sempre o do motor mais lento (medido: LinkedIn a 6,8s).
        # Aqui o lead segue e os motores pendentes morrem sozinhos no timeout.
        ex.shutdown(wait=False, cancel_futures=True)


def _linkedin_web(company: str, domain: str, logger: logging.Logger) -> str:
    """Procura a PÁGINA DE EMPRESA da companhia no LinkedIn, via buscador.

    Só página institucional (``/company/``) — nunca perfil de pessoa (``/in/``).
    É dado público de empresa, do mesmo tipo que o site já publica; não coletamos
    nome, cargo ou contato de indivíduo por aqui (LGPD).

    Validação: o resultado precisa ter relação com o lead — o slug do LinkedIn
    e o domínio/nome precisam compartilhar raiz. Sem isso, um homônimo qualquer
    entraria como se fosse a empresa certa.
    """
    marca = (domain or "").split(".")[0]
    alvo = strip_accents((company or "").lower()).replace(" ", "")
    consultas = [f'"{company}" site:linkedin.com/company', f"{company} {marca} linkedin"]
    for consulta in consultas:
        for results in _web_search_backends(consulta, max_results=8):
            for item in results:
                url = (item.get("href") or "")
                achado = _LINKEDIN_RE.search(url)
                if not achado:
                    continue
                slug = achado.group(1).strip("/").lower()
                chave = slug.replace("-", "")
                if not (chave[:5] and (chave[:5] in alvo or chave[:5] in marca
                                       or marca[:5] in chave or alvo[:5] in chave)):
                    continue          # sem raiz em comum: provavelmente outra empresa
                logger.debug("LinkedIn achado na web para %s: %s", domain, slug)
                return f"https://www.linkedin.com/company/{slug}"
    return ""


def _cnpj_official_web(company: str, domain: str, logger: logging.Logger) -> dict[str, str]:
    """Acha o CNPJ na web (diretórios públicos) e busca o telefone oficial — validado por domínio/nome."""
    target = _norm_name(company)
    if not domain and len(target) < 5:
        return {}
    dom_label = domain.split(".")[0] if domain else ""
    with _CNPJ_WEB_SEM:
        for results in _web_search_backends(f"{company} {domain} CNPJ"):
            # 1) Resultado que cita o DOMÍNIO -> o CNPJ ali (inclusive na URL) é da empresa. Seguro.
            for r in results:
                blob = (r.get("title", "") + " " + r.get("body", "") + " " + r.get("href", "")).lower()
                if domain and (domain in blob or (len(dom_label) >= 5 and dom_label in blob)):
                    for cnpj in _cnpjs_from_text(blob, allow_bare=True):
                        data = _receita_lookup(cnpj)
                        if data:
                            data.pop("_name", None)
                            return data
            # 2) Fallback: CNPJ formatado cujo NOME confere com a empresa.
            snippets = " ".join((r.get("title", "") + " " + r.get("body", "")) for r in results)
            for cnpj in _cnpjs_from_text(snippets):
                data = _receita_lookup(cnpj)
                if data and len(target) >= 5 and target in (data.get("_name") or ""):
                    data.pop("_name", None)
                    return data
    return {}


_PHONE_WEB_SEM = threading.Semaphore(8)
_PHONE_DIRS = ("apontador", "guiamais", "telelistas", "econodata", "solutudo",
               "cnpj", "encontreinforma", "kompass", "cylex", "hotfrog", "boasinfo")


def _phone_official_web(company: str, domain: str, city: str, logger: logging.Logger) -> str:
    """Telefone PÚBLICO da empresa em listas/diretórios (GuiaMais, Apontador, Telelistas...).

    Só dado público; validado por DOMÍNIO (a lista cita o site da empresa) ou por NOME
    distinto + cidade — nunca devolve telefone de outra empresa.
    """
    target = _norm_name(company)
    if not domain and len(target) < 5:
        return ""
    dom_label = domain.split(".")[0] if domain else ""
    cnorm = _norm_name(city) if city else ""
    # Query funciona p/ BR ("telefone contato") e internacional ("phone contact").
    intl = not (domain.endswith(".br") or cnorm)
    term = "phone contact" if intl else "telefone contato"
    query = " ".join(x for x in (company, city, term) if x)
    with _PHONE_WEB_SEM:
        for results in _web_search_backends(query):   # tenta cada buscador até achar telefone válido
            for r in results:
                title, body, href = r.get("title", ""), r.get("body", ""), r.get("href", "")
                ref = _norm_name(title + " " + body + " " + href)
                dom_ok = bool(domain) and (len(dom_label) >= 5 and dom_label in ref)
                in_dir = any(d in _norm_name(href) for d in _PHONE_DIRS)   # página por empresa em lista pública
                name_ok = len(target) >= 6 and target in _norm_name(title) and (cnorm in ref if cnorm else in_dir)
                if not (dom_ok or name_ok):
                    continue
                phone = extract_phone(title + " . " + body)
                if phone:
                    return phone
    return ""


# --- Dados estruturados (JSON-LD / schema.org) — completa telefone/e-mail ---
_JSONLD_RE = re.compile(r'<script[^>]+ld\+json[^>]*>(.*?)</script>', re.I | re.S)
_LD_KEYS = {"telephone": "phone", "email": "email"}


def _ld_walk(obj, found):
    if isinstance(obj, dict):
        for key, value in obj.items():
            target = _LD_KEYS.get(key.lower())
            if target and isinstance(value, str) and value.strip() and target not in found:
                found[target] = value.replace("mailto:", "").replace("tel:", "").strip()
            else:
                _ld_walk(value, found)
    elif isinstance(obj, list):
        for item in obj:
            _ld_walk(item, found)


def _jsonld_contacts(html: str) -> dict:
    found: dict = {}
    for block in _JSONLD_RE.findall(html or ""):
        block = block.strip()
        if not block:
            continue
        try:
            _ld_walk(json.loads(block), found)
        except (ValueError, TypeError):
            continue
    return found


# Teto de tempo para buscas web de contato (telefone/CNPJ em diretórios): se um
# motor travar, seguimos SEM o dado em vez de segurar o lote inteiro. Best-effort
# dentro do orçamento — os dados da própria página/Receita já cobrem a maioria.
_WEB_LOOKUP_TIMEOUT = 8
# 64 vagas porque este pool é COMPARTILHADO por todos os leads do lote: 16 leads
# disparando 3 buscas cada = 48 tarefas simultâneas. Com 16 vagas elas entravam em
# FILA — e como o teto de espera conta desde a submissão, o lead estourava o tempo
# e perdia o dado sem que a busca sequer tivesse começado. São tarefas de REDE:
# ficam paradas esperando resposta, não competem por CPU.
_LOOKUP_EX = ThreadPoolExecutor(max_workers=64)


def _colher(futuro, default, teto: float):
    """Resultado de uma busca web já DISPARADA, com teto de espera.

    Existe para que CNPJ, telefone e LinkedIn possam correr juntos: submetidos de
    uma vez, o lead espera a mais lenta em vez da soma das três. ``None`` como
    futuro significa "esta busca não era necessária".
    """
    if futuro is None:
        return default
    try:
        return futuro.result(timeout=teto)
    except Exception:  # noqa: BLE001 - timeout/erro: segue sem o dado
        return default


def _call_timeout(fn, default, *args, _teto: float = _WEB_LOOKUP_TIMEOUT, **kwargs):
    """Roda ``fn`` com teto em segundos; estourou -> devolve ``default``.

    ``_teto`` sobe para a consulta de CNPJ: medida isolada ela leva 5 a 7s, então
    o teto padrão de 8s a matava justamente sob concorrência — e sem CNPJ não há
    porte, situação nem ano de abertura.
    """
    fut = _LOOKUP_EX.submit(fn, *args, **kwargs)
    try:
        return fut.result(timeout=_teto)
    except Exception:  # noqa: BLE001 - timeout/erro -> segue sem o dado
        return default


def _process_lead(lead: Lead, config: dict[str, Any], logger: logging.Logger, deep: bool = True) -> HotLead:
    """Monta o ``HotLead`` da empresa.

    ``deep=True`` (padrão): visita páginas internas (Contato/Sobre/Produtos) e faz as
    buscas web de contato — enriquecimento COMPLETO. ``deep=False``: só a homepage —
    RÁPIDO, usado na fase de filtro (país/score) antes de aprofundar só nos entregues.
    """
    fetch_cfg = config["fetch"]
    enrich_cfg = config["enrichment"]
    domain = normalize_domain(lead.website)
    # Buscas WEB de contato são caras: 'hot' = só nos HOT; 'all' = todos; 'off' = nunca.
    # Só rodam no enriquecimento PROFUNDO (deep).
    web_mode = str(enrich_cfg.get("web_contact_lookup", "all")).lower()
    do_web = deep and (web_mode == "all" or (web_mode == "hot" and (lead.classification or "") == "HOT"))

    def fetch(url: str):
        return fetch_page(
            url,
            timeout=fetch_cfg["timeout_seconds"],
            max_chars=fetch_cfg["max_text_chars"],
            user_agent=fetch_cfg["user_agent"],
            logger=logger,
        )

    home = fetch(lead.website)

    contact_url = about_url = locations_url = team_url = ""
    product_urls: list[str] = []
    pages_html: list[str] = []
    pages_text: list[str] = [lead.title, lead.description]
    html_lang = home.lang if home.ok else ""

    if home.ok:
        pages_html.append(home.html)
        pages_text.append(home.text)
        if deep:                                 # páginas internas só no enriquecimento PROFUNDO
            base = home.final_url or lead.website
            links = _internal_links(base, home.html, domain)

            contact_url = _pick(links, _PAGE_KEYWORDS["contact"])
            about_url = _pick(links, _PAGE_KEYWORDS["about"])
            locations_url = _pick(links, _PAGE_KEYWORDS["locations"])
            team_url = _pick(links, _PAGE_KEYWORDS["team"])     # onde mora o decisor
            product_urls = _pick_many(links, _paginas_operacao(), enrich_cfg["max_product_pages"])

            to_visit = [contact_url, about_url, locations_url, team_url, *product_urls]
            root = (base or lead.website).rstrip("/")
            # PALPITES só quando o link NÃO foi achado no HTML — cada palpite errado é
            # um 404 pago a preço de página. Eram até 12 fixos por lead; agora entram
            # no máximo 4, e apenas para o que faltou.
            if not contact_url:                     # tenta caminhos comuns de contato
                to_visit += [f"{root}/contato", f"{root}/contact", f"{root}/fale-conosco"]
            # Páginas de VENDA: é onde mora o e-mail comercial/nominal. Quando o site só
            # publica "contato@" na home, o endereço do comercial costuma estar aqui.
            if not team_url:
                to_visit += [f"{root}/equipe", f"{root}/quem-somos"]
            if not any("comercial" in (u or "") for u in to_visit):
                to_visit.append(f"{root}/comercial")
            if not about_url:   # a página de privacidade costuma trazer o CNPJ
                to_visit.append(f"{root}/politica-de-privacidade")
            # Visita as páginas internas EM PARALELO. O paralelismo aqui se MULTIPLICA
            # pelo número de leads do lote (16 leads x N threads), então 8 é o ponto de
            # equilíbrio: cobre as ~10 URLs em uma onda e meia sem estourar o total de
            # threads do processo, que era o que fazia o lote inteiro arrastar.
            urls = [u for u in dict.fromkeys(u for u in to_visit if u)]
            if urls:
                with ThreadPoolExecutor(max_workers=min(8, len(urls))) as page_ex:
                    for page in page_ex.map(fetch, urls):
                        if page.ok:
                            pages_html.append(page.html)
                            pages_text.append(page.text)

    combined_html = "\n".join(pages_html)
    full_text = " ".join(pages_text)
    combined_text = full_text.lower()

    country = detect_country(domain, full_text)         # país ANTES do telefone (usado como dica)
    # Lista RANQUEADA por temperatura (pessoa > diretoria > comercial > contato@ > sac@).
    # Guardamos a lista inteira: o decisor só aparece adiante e pode promover um endereço,
    # e o 2º canal serve de alternativa quando o 1º é uma caixa geral.
    emails_rank = extract_emails_ranked(combined_html, prefer_domain=domain)
    email = emails_rank[0][0] if emails_rank else ""
    phone = extract_phone(combined_html, country=country)
    if not (phone and email):                   # completa com dados estruturados (JSON-LD)
        ld = _jsonld_contacts(combined_html)
        if not phone and ld.get("phone"):
            phone = extract_phone(f'<a href="tel:{ld["phone"]}">x</a>', country=country) or phone
        if not email and ld.get("email"):
            email = extract_email(f'<a href="mailto:{ld["email"]}">x</a>', prefer_domain=domain) or email
    city = detect_city_consistent(full_text, country)   # cidade COERENTE com o país
    language = detect_language(html_lang, full_text, domain)
    # Necessidade: do conteúdo do site + a busca que achou a empresa + os termos
    # pontuados. Evidência real, casada com as pistas de cada solução do nicho.
    solutions = detect_solutions(full_text + " " + lead.search_keyword + " " + " ".join(lead.keywords_found))

    # Dados OFICIAIS da Receita quando há CNPJ — no site ou (se não houver) na web.
    official = _cnpj_official(combined_html, logger) if deep else {}
    # O decisor sai do HTML já baixado: é LOCAL e rápido, então vem antes das buscas
    # web — é ele que diz se ainda falta procurar o LinkedIn.
    decisor = find_decisor(combined_html, full_text, solutions)

    # ---- BUSCAS WEB EM PARALELO -------------------------------------------------
    # CNPJ, telefone e LinkedIn são independentes entre si e cada um custa segundos
    # (medido: LinkedIn 5,8s · CNPJ 5,0s). Em sequência, somavam; disparados juntos,
    # o custo do lead vira o da MAIS LENTA. As condições de "preciso disto?" já são
    # todas conhecidas aqui.
    # O CNPJ destrava PORTE, situação cadastral e ano de abertura na Receita — é o
    # que separa a empresa grande da pequena, e o cliente paga por isso no plano.
    _quer_porte = os.environ.get("PROSPECT_PORTE", "1") != ""
    _e_br = country == "Brazil" or domain.endswith(".br")
    _f_cnpj = _f_fone = _f_li = None
    if do_web and not official and _e_br and (_quer_porte or not phone):
        _f_cnpj = _LOOKUP_EX.submit(_cnpj_official_web, lead.company, domain, logger)
    # Telefone público em listas/diretórios — só BRASIL (Apontador/GuiaMais/Telelistas
    # são diretórios BR; p/ lead internacional não acham nada e ainda travam a busca).
    if do_web and not phone and _e_br:
        _f_fone = _LOOKUP_EX.submit(_phone_official_web, lead.company, domain, city, logger)
    # LinkedIn: rodapé do site primeiro (barato, já veio no HTML). Se não houver,
    # procura a página de EMPRESA na web — é o terceiro canal de contato, e para
    # muita empresa pequena é o único que existe além do telefone.
    if do_web and not decisor.linkedin and os.environ.get("PROSPECT_LINKEDIN", "1") != "":
        _f_li = _LOOKUP_EX.submit(_linkedin_web, lead.company, domain, logger)

    # Teto de 12s no CNPJ: medido, ele resolve em 1,5 a 5s. Os 18s antigos só
    # serviam para a cauda ruim — e, como o lead inteiro fica esperando, cada caso
    # desses atrasava o lote todo. Quem estoura 12s quase nunca responde mesmo.
    official = _colher(_f_cnpj, {}, 12) or official
    if official:
        city = official.get("city") or city
        if not phone and official.get("phone"):
            phone = extract_phone(f'<a href="tel:{official["phone"]}">x</a>') or phone
        if not email and official.get("email"):
            email = extract_email(f'<a href="mailto:{official["email"]}">x</a>', prefer_domain=domain) or email
    phone = phone or _colher(_f_fone, "", 8)
    decisor.linkedin = decisor.linkedin or _colher(_f_li, "", 8)

    # VALIDA o e-mail encontrado: o domínio precisa aceitar mensagens (ter MX). Senão, descarta
    # (evita entregar e-mail morto/typo e perder tempo testando endereço falso).
    # Cai para o PRÓXIMO da lista ranqueada em vez de entregar o lead sem e-mail:
    # muito site publica um endereço antigo ao lado do que funciona.
    while email and not _email_has_mx(email):
        emails_rank = [(e, r) for e, r in emails_rank if e != email]
        email = emails_rank[0][0] if emails_rank else ""
    # QUALIFICAÇÃO: por padrão NÃO inventamos "compras@dominio" — "tem e-mail" passa a
    # significar e-mail REAL, e o ranking por completude entrega contato real no topo.
    # Para voltar a inferir o endereço de função (compras@), ligue infer_role_email.
    if not email and enrich_cfg.get("infer_role_email", False) and _domain_has_mx(domain):
        email = f"contato@{domain}"

    # DECISOR + LINKEDIN: cargo real quando o site expõe (páginas Sobre/Equipe já
    # foram baixadas acima); senão o cargo-alvo derivado da necessidade detectada.
    # PORTE DA OPERAÇÃO: o número que a empresa publica manda; sem ele, o capital
    # social e o porte da Receita entram como substituto.
    if _quer_porte:
        porte_numero = _porte.detectar_numero(full_text)
        porte = _porte.classificar(porte_numero, float(official.get("capital_social") or 0),
                                   str(official.get("porte_receita") or ""))
    else:
        porte_numero, porte = 0, ""    # recurso fora do plano: nem calcula

    # Se o site publica o e-mail do decisor (ex.: decisor "Fulano de Tal" e
    # endereço "fulano@"), esse é o contato mais quente que existe — sobe para o
    # topo. Nada é inventado: o endereço já estava na página.
    if decisor.name and emails_rank:
        emails_rank = promover_decisor(emails_rank, decisor.name)
        if emails_rank[0][0] != email and _email_has_mx(emails_rank[0][0]):
            email = emails_rank[0][0]
    # Temperatura do e-mail entregue — o vendedor sabe se vai cair numa pessoa,
    # no comercial ou numa caixa geral antes de escrever. Calculada sobre o
    # endereço final, que pode ter vindo da Receita ou do JSON-LD.
    email_tipo = rotulo_email(temperatura_email(email, decisor.name, domain)) if email else ""
    # NOME EXIBIDO: troca o derivado do domínio ("Empresaexemplobrasil") pelo nome
    # comercial da Receita / og:site_name / <title> quando houver algo melhor.
    company = _display_name(lead.company, official, combined_html,
                            _page_title(home.html) if home.ok else lead.title)

    return HotLead(
        company=company,
        website=lead.website,
        score=lead.score,
        classification=lead.classification or "HOT",
        keywords_found=lead.keywords_found,
        solutions=solutions,
        country=country,
        city=city,
        phone=phone,
        email=email,
        email_tipo=email_tipo,
        contact_page=contact_url,
        about_page=about_url,
        porte_numero=porte_numero,
        porte=porte,
        porte_texto=_porte.rotulo(porte_numero, porte),
        situacao=str(official.get("situacao") or ""),
        desde=str(official.get("desde") or ""),
        cnae=str(official.get("sector") or ""),
        contact_name=decisor.name,
        contact_role=decisor.role,
        role_source=decisor.role_source,
        linkedin=decisor.linkedin,
        buyer_likelihood=_buyer_likelihood(combined_text),
        export_potential=_export_potential(combined_text, " ".join(pages_text)),
        recommended_language=language,
    )


def _internal_links(base_url: str, html: str, domain: str) -> list[tuple[str, str]]:
    """Devolve (texto, url_absoluta) dos links internos ao mesmo domínio."""
    soup = BeautifulSoup(html or "", "lxml")
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        try:
            absolute = urljoin(base_url, href)
            if normalize_domain(absolute) != domain:
                continue
        except ValueError:   # href malformado (ex.: host entre colchetes inválido) -> ignora
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        links.append((anchor.get_text(" ", strip=True).lower(), absolute))
    return links


def _matches(text: str, url: str, keywords: list[str]) -> bool:
    haystack = text + " " + url.lower()
    return any(keyword in haystack for keyword in keywords)


def _pick(links: list[tuple[str, str]], keywords: list[str]) -> str:
    for text, url in links:
        if _matches(text, url, keywords):
            return url
    return ""


def _pick_many(links: list[tuple[str, str]], keywords: list[str], limit: int) -> list[str]:
    picked: list[str] = []
    for text, url in links:
        if _matches(text, url, keywords) and url not in picked:
            picked.append(url)
        if len(picked) >= limit:
            break
    return picked


def _buyer_likelihood(text: str) -> str:
    """HIGH: muitos sinais de necessidade; MEDIUM: setor certo com poucos; LOW: insuficiente.

    Os sinais são os do próprio nicho (pontuacao.necessidades e segmentos).
    """
    n = _nicho.ativo()
    normalized = _nicho.norm(text)
    solutions = sum(1 for kw in n.necessidades if _nicho.norm(kw) in normalized)
    industries = sum(1 for kw in n.segmentos if _nicho.norm(kw) in normalized)
    total = solutions + industries
    if total >= 4 or solutions >= 2:
        return "HIGH"
    if total >= 1:
        return "MEDIUM"
    return "LOW"


def _export_potential(text_lower: str, text_raw: str) -> str:
    """HIGH: presença internacional; MEDIUM: nacional relevante; LOW: local."""
    normalized = strip_accents(text_lower)
    countries = count_countries(text_raw)
    signals = sum(1 for kw in _EXPORT_SIGNALS if kw in normalized)
    if countries >= 3 or signals >= 2:
        return "HIGH"
    if countries >= 1 or signals >= 1:
        return "MEDIUM"
    return "LOW"
