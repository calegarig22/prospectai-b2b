"""Detecção heurística de país, cidade e idioma principal do site.

Sem serviços externos: usa o ccTLD do domínio, varredura de nomes no texto e o
atributo ``lang`` do HTML, com fallback por palavras-comuns. São aproximações
(ver limitações no relatório), suficientes para priorização comercial.
"""

from __future__ import annotations

import re

# --- Idiomas ---------------------------------------------------------------
LANG_MAP = {
    "en": "English", "pt": "Portuguese", "es": "Spanish",
    "de": "German", "fr": "French", "it": "Italian",
}

_STOPWORDS = {
    "English": ["the", "and", "for", "with", "our", "we", "products", "services", "about", "contact"],
    "Portuguese": ["de", "para", "com", "nossos", "nós", "produtos", "serviços", "sobre", "contato", "empresa"],
    "Spanish": ["de", "para", "con", "nuestros", "nosotros", "productos", "servicios", "contacto", "empresa", "acerca"],
    "German": ["und", "der", "die", "das", "für", "mit", "unsere", "produkte", "über", "kontakt"],
    "French": ["et", "pour", "avec", "nos", "nous", "produits", "services", "propos", "contact", "entreprise"],
    "Italian": ["di", "per", "con", "nostri", "prodotti", "servizi", "contatto", "azienda", "chi", "siamo"],
}

# --- Geografia -------------------------------------------------------------
CCTLD_COUNTRY = {
    "br": "Brazil", "us": "United States", "uk": "United Kingdom", "de": "Germany",
    "fr": "France", "it": "Italy", "es": "Spain", "pt": "Portugal", "nl": "Netherlands",
    "be": "Belgium", "ch": "Switzerland", "at": "Austria", "se": "Sweden", "no": "Norway",
    "dk": "Denmark", "fi": "Finland", "cn": "China", "in": "India", "jp": "Japan",
    "kr": "South Korea", "ru": "Russia", "ae": "United Arab Emirates", "sa": "Saudi Arabia",
    "au": "Australia", "ca": "Canada", "mx": "Mexico", "ar": "Argentina", "cl": "Chile",
    "za": "South Africa", "tr": "Turkey", "pl": "Poland", "cz": "Czech Republic",
    "tw": "Taiwan", "vn": "Vietnam", "th": "Thailand", "id": "Indonesia", "my": "Malaysia",
    "sg": "Singapore", "qa": "Qatar", "kw": "Kuwait", "om": "Oman", "eg": "Egypt",
    "co": "Colombia", "nz": "New Zealand",
    "pe": "Peru", "uy": "Uruguay", "bo": "Bolivia", "ec": "Ecuador", "py": "Paraguay", "ve": "Venezuela",
}

CCTLD_LANG = {
    "br": "Portuguese", "pt": "Portuguese", "de": "German", "at": "German", "ch": "German",
    "fr": "French", "it": "Italian", "es": "Spanish", "mx": "Spanish",
    "ar": "Spanish", "cl": "Spanish",
}

COUNTRY_NAMES = [
    "United States", "United Kingdom", "Brazil", "Brasil", "Germany", "France", "Italy", "Spain",
    "Portugal", "Netherlands", "Belgium", "Switzerland", "Austria", "Sweden", "Norway",
    "Denmark", "Finland", "China", "India", "Japan", "South Korea", "Russia",
    "United Arab Emirates", "Saudi Arabia", "Qatar", "Kuwait", "Oman", "Australia",
    "Canada", "Mexico", "Argentina", "Chile", "Colombia", "South Africa", "Nigeria",
    "Turkey", "Poland", "Czech Republic", "Singapore", "Malaysia", "Indonesia",
    "Thailand", "Vietnam", "Egypt", "Ireland", "Scotland", "USA", "UK",
    "Taiwan", "New Zealand", "Peru", "Uruguay", "Bolivia", "Ecuador", "Paraguay", "Venezuela",
]

# Lista enxuta de cidades industriais/comerciais relevantes (heurística).
CITY_NAMES = [
    "Houston", "Dallas", "Chicago", "New York", "Los Angeles", "Pittsburgh", "Cleveland",
    "London", "Manchester", "Sheffield", "Birmingham", "Aberdeen", "Rotterdam", "Hamburg",
    "Düsseldorf", "Frankfurt", "Munich", "Milan", "Turin", "Madrid", "Barcelona", "Bilbao",
    "Paris", "Lyon", "Mumbai", "Delhi", "Chennai",
    "Shanghai", "Beijing", "Dubai", "Abu Dhabi", "Doha", "Singapore", "Tokyo", "Seoul",
    "Toronto", "Calgary", "Edmonton", "Monterrey", "Buenos Aires", "Santiago",
    # Brasil — principais polos industriais/comerciais
    "São Paulo", "Sao Paulo", "Rio de Janeiro", "Belo Horizonte", "Curitiba",
    "Porto Alegre", "Campinas", "Joinville", "Caxias do Sul", "Sorocaba",
    "Guarulhos", "Osasco", "Santo André", "Diadema", "São Bernardo do Campo",
    "Contagem", "Betim", "Jundiaí", "Limeira", "Piracicaba",
]

# Cidades internacionais -> país, para manter a cidade COERENTE com o país detectado
# (evita inconsistências como "Brazil / Mumbai").
CITY_COUNTRY = {
    "Houston": "United States", "Dallas": "United States", "Chicago": "United States",
    "New York": "United States", "Los Angeles": "United States", "Pittsburgh": "United States",
    "Cleveland": "United States", "London": "United Kingdom", "Manchester": "United Kingdom",
    "Sheffield": "United Kingdom", "Birmingham": "United Kingdom", "Aberdeen": "United Kingdom",
    "Rotterdam": "Netherlands", "Hamburg": "Germany", "Düsseldorf": "Germany",
    "Frankfurt": "Germany", "Munich": "Germany", "Milan": "Italy", "Turin": "Italy",
    "Madrid": "Spain", "Barcelona": "Spain", "Bilbao": "Spain", "Paris": "France", "Lyon": "France",
    "Mumbai": "India", "Delhi": "India", "Chennai": "India", "Shanghai": "China", "Beijing": "China",
    "Dubai": "United Arab Emirates", "Abu Dhabi": "United Arab Emirates", "Doha": "Qatar",
    "Singapore": "Singapore", "Tokyo": "Japan", "Seoul": "South Korea", "Toronto": "Canada",
    "Calgary": "Canada", "Edmonton": "Canada", "Monterrey": "Mexico",
    "Buenos Aires": "Argentina", "Santiago": "Chile",
}
# Cidades brasileiras (subconjunto) — usadas quando o país é o Brasil.
_BR_CITIES = [
    "São Paulo", "Sao Paulo", "Rio de Janeiro", "Belo Horizonte", "Curitiba",
    "Porto Alegre", "Campinas", "Joinville", "Caxias do Sul", "Sorocaba",
    "Guarulhos", "Osasco", "Santo André", "Diadema", "São Bernardo do Campo",
    "Contagem", "Betim", "Jundiaí", "Limeira", "Piracicaba",
]


def _count_words(text: str, words: list[str]) -> int:
    total = 0
    for word in words:
        total += len(re.findall(r"\b" + re.escape(word) + r"\b", text))
    return total


def detect_language(html_lang: str, text: str, domain: str) -> str:
    """Detecta o idioma principal: atributo lang -> palavras-comuns -> ccTLD."""
    code = (html_lang or "").strip().lower()[:2]
    if code in LANG_MAP:
        return LANG_MAP[code]

    low = (text or "").lower()
    if low:
        scores = {lang: _count_words(low, words) for lang, words in _STOPWORDS.items()}
        best = max(scores, key=scores.get)
        if scores[best] >= 3:
            return best

    tld = domain.rsplit(".", 1)[-1] if domain else ""
    if tld in CCTLD_LANG:
        return CCTLD_LANG[tld]
    return "English" if tld in {"com", "net", "org"} else "Other"


def detect_country(domain: str, text: str) -> str:
    """Detecta o país via ccTLD e, em fallback, por nomes citados no texto."""
    tld = domain.rsplit(".", 1)[-1] if domain else ""
    if tld in CCTLD_COUNTRY:
        return CCTLD_COUNTRY[tld]

    best, best_count = "", 0
    for name in COUNTRY_NAMES:
        count = len(re.findall(r"\b" + re.escape(name) + r"\b", text or ""))
        if count > best_count:
            best, best_count = name, count
    # Normaliza apelidos / variações de idioma.
    return {"USA": "United States", "UK": "United Kingdom", "Brasil": "Brazil"}.get(best, best)


def _detect_city_curated(text: str) -> str:
    # Só cidades brasileiras — detect_city_state é do Brasil (evita 'Brazil/Mumbai').
    best, best_count = "", 0
    for name in _BR_CITIES:
        count = len(re.findall(r"\b" + re.escape(name) + r"\b", text))
        if count > best_count:
            best, best_count = name, count
    return best


def detect_city(text: str) -> str:
    """Cidade (compatibilidade). Use detect_city_state para o par cidade+UF consistente."""
    return detect_city_state(text)[0]


def detect_city_consistent(text: str, country: str = "") -> str:
    """Cidade COERENTE com o país detectado — nunca casa cidade de outro país.

    Brasil -> endereço BR + cidades BR. Outro país -> só cidade daquele país.
    Vazio quando não há cidade coerente (preferível a mostrar errado).
    """
    raw = text or ""
    if country == "Brazil":
        return detect_city_state(raw)[0]
    best, best_count = "", 0
    for name, ccountry in CITY_COUNTRY.items():
        if country and ccountry != country:   # cidade tem que ser do país detectado
            continue
        count = len(re.findall(r"\b" + re.escape(name) + r"\b", raw))
        if count > best_count:
            best, best_count = name, count
    return best


def count_countries(text: str) -> int:
    """Conta quantos países distintos são citados no texto (sinal de exportação)."""
    found = set()
    for name in COUNTRY_NAMES:
        if re.search(r"\b" + re.escape(name) + r"\b", text or ""):
            found.add({"USA": "United States", "UK": "United Kingdom", "Brasil": "Brazil"}.get(name, name))
    return len(found)


# --- Estados brasileiros ---------------------------------------------------
BR_STATES = {
    "AC": "Acre", "AL": "Alagoas", "AP": "Amapá", "AM": "Amazonas", "BA": "Bahia",
    "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás",
    "MA": "Maranhão", "MT": "Mato Grosso", "MS": "Mato Grosso do Sul", "MG": "Minas Gerais",
    "PA": "Pará", "PB": "Paraíba", "PR": "Paraná", "PE": "Pernambuco", "PI": "Piauí",
    "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RS": "Rio Grande do Sul",
    "RO": "Rondônia", "RR": "Roraima", "SC": "Santa Catarina", "SP": "São Paulo",
    "SE": "Sergipe", "TO": "Tocantins",
}

# Cidade -> estado (apenas as cidades brasileiras de CITY_NAMES).
_CITY_STATE = {
    "São Paulo": "São Paulo", "Sao Paulo": "São Paulo", "Campinas": "São Paulo",
    "Sorocaba": "São Paulo", "Guarulhos": "São Paulo", "Osasco": "São Paulo",
    "Santo André": "São Paulo", "Diadema": "São Paulo", "São Bernardo do Campo": "São Paulo",
    "Jundiaí": "São Paulo", "Limeira": "São Paulo", "Piracicaba": "São Paulo",
    "Rio de Janeiro": "Rio de Janeiro", "Belo Horizonte": "Minas Gerais",
    "Contagem": "Minas Gerais", "Betim": "Minas Gerais", "Curitiba": "Paraná",
    "Joinville": "Santa Catarina", "Porto Alegre": "Rio Grande do Sul",
    "Caxias do Sul": "Rio Grande do Sul",
}

# Nomes de estado mais longos primeiro, para casar antes de substrings.
_STATE_NAMES = sorted(set(BR_STATES.values()), key=len, reverse=True)
# UF só é aceita quando precedida por separador de endereço (ex.: "- SP", ", RJ").
_UF_RE = re.compile(r"[-/,(]\s*([A-Z]{2})\b")


def detect_state(text: str, city: str = "") -> str:
    """Detecta o estado (Brasil): nome completo -> UF em endereço -> cidade.

    Retorna o nome do estado por extenso, ou string vazia se indefinido.
    """
    raw = text or ""
    for name in _STATE_NAMES:
        if re.search(r"\b" + re.escape(name) + r"\b", raw):
            return name

    for uf in _UF_RE.findall(raw):
        if uf in BR_STATES:
            return BR_STATES[uf]

    return _CITY_STATE.get(city, "")


def normalize_state(value: str) -> str:
    """Normaliza um estado vindo de dados estruturados (UF ou nome) -> nome por extenso."""
    v = (value or "").strip()
    if v in BR_STATES:                 # já é UF ("SP")
        return BR_STATES[v]
    if v in BR_STATES.values():        # já é o nome por extenso
        return v
    return BR_STATES.get(v.upper(), "")


# Endereço "Cidade - UF" / "Cidade/UF" / "Cidade, UF": captura a cidade de QUALQUER
# município brasileiro (não só os da lista curada). Palavras só com inicial maiúscula,
# permitindo conectores (de/do/da). A frequência decide a cidade real (repete no rodapé).
_ADDR_CITY_RE = re.compile(
    r"([A-ZÀ-Ý][a-zà-ÿ']+(?:\s+(?:de|do|da|dos|das|e|[A-ZÀ-Ý][a-zà-ÿ']+)){0,3})"
    r"\s*[-/,]\s*(" + "|".join(BR_STATES.keys()) + r")\b"
)
# Palavras de logradouro/ruído/esporte que NÃO são cidade (filtra falsos positivos).
_NOT_CITY = {
    "rua", "avenida", "av", "alameda", "rodovia", "estrada", "travessa", "praca", "praça",
    "bairro", "endereco", "endereço", "cep", "matriz", "filial", "unidade", "loja", "sala",
    "andar", "bloco", "centro", "brasil", "brazil", "telefone", "fone", "email", "contato",
    "times", "bola", "clube", "futebol", "atletico", "athletico", "esporte", "esportes",
    "campeonato", "jogos", "jogo", "copa", "liga",
}
_CONNECTORS = {"de", "do", "da", "dos", "das", "e"}


def _city_state_from_address(text: str) -> tuple[str, str]:
    """Cidade + UF capturadas do MESMO endereço 'Cidade - UF' — garante consistência."""
    counts: dict[tuple[str, str], int] = {}
    for match in _ADDR_CITY_RE.finditer(text or ""):
        city = match.group(1).strip(" .,-'")
        uf = match.group(2)
        words = city.split()
        lower = {w.lower() for w in words}
        if not words or words[0].lower() in _NOT_CITY or lower & _NOT_CITY:
            continue
        if len(city) < 3:
            continue
        # 3+ palavras só valem com conector (ex.: "Rio de Janeiro", "São José dos Campos");
        # corta capturas longas sem conector (ruído tipo "Bola Times Athletico").
        if len(words) >= 3 and not (lower & _CONNECTORS):
            continue
        counts[(city, uf)] = counts.get((city, uf), 0) + 1
    if not counts:
        return "", ""
    city, uf = max(counts, key=counts.get)
    return city, uf


def detect_city_state(text: str) -> tuple[str, str]:
    """Devolve (cidade, estado) CONSISTENTES: do mesmo endereço, ou pela cidade curada.

    Nunca pega a UF de um trecho do texto diferente da cidade — evita 'Curitiba/RJ'.
    """
    raw = text or ""
    city, uf = _city_state_from_address(raw)      # par do mesmo endereço
    if city:
        return city, BR_STATES.get(uf, "")
    city = _detect_city_curated(raw)              # cidade conhecida -> seu estado
    if city:
        return city, _CITY_STATE.get(city, "")
    return "", ""
