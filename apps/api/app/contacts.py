"""Extração de contatos corporativos públicos (e-mail e telefone).

Prioriza TELEFONES REAIS (com estrutura: parênteses, hífen, +código ou 0800) —
evitando números soltos de analytics/JS — e E-MAILS direcionados a RH e Vendas
(rebaixando imprensa/jurídico/LGPD). Usa apenas dados publicamente disponíveis.
"""

from __future__ import annotations

import re
import unicodedata

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_MAILTO_RE = re.compile(r"mailto:([^\"'?>\s]+)", re.IGNORECASE)
_TEL_RE = re.compile(r"tel:([+0-9().\-\s]{7,})", re.IGNORECASE)
# WhatsApp (wa.me / api.whatsapp.com / web.whatsapp.com) — fonte comum em sites BR.
_WHATSAPP_RE = re.compile(
    r"(?:wa\.me/|whatsapp\.com/send/?\?phone=|api\.whatsapp\.com/send/?\?phone=)\+?(\d{10,15})",
    re.IGNORECASE,
)
# E-mails ofuscados: "contato [at] empresa [dot] com" / "(arroba)" / "(ponto)".
_OBF_AT = re.compile(r"\s*[\[\(\{]\s*(?:at|arroba)\s*[\]\)\}]\s*", re.IGNORECASE)
_OBF_DOT = re.compile(r"\s*[\[\(\{]\s*(?:dot|ponto)\s*[\]\)\}]\s*", re.IGNORECASE)
# Remove blocos de script/estilo (fonte dos números de analytics) antes de varrer telefone.
_SCRIPT_RE = re.compile(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>")
_DATE_LIKE = re.compile(r"^\s*\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}\s*$")
# Intervalo de anos (ex.: 2025-2026, 2020/2021) que parece telefone — rejeitar.
_YEAR_RANGE = re.compile(r"^\s*(19|20)\d{2}\s*[-/]\s*(19|20)\d{2}\s*$")

# Telefones REAIS exigem ESTRUTURA — assim números soltos de JS não passam.
_PHONE_PATTERNS = [
    re.compile(r"0800[\s.\-]?\d{3}[\s.\-]?\d{3,4}"),                            # 0800 707 4700
    re.compile(r"\+\d{1,3}[\s.\-]?\(?\d{2,4}\)?[\s.\-]?\d{3,5}[\s.\-]?\d{4}"),  # +55 (11) 1234-5678
    re.compile(r"\(\d{2,4}\)\s?\d{3,5}[\s.\-]?\d{4}"),                          # (11) 91234-5678
    re.compile(r"\b\d{2,3}[\s.\-]\d{3,5}[\s.\-]\d{4}\b"),                       # 11 91234 5678 / 713-555-1234
    re.compile(r"\b\d{4,5}\-\d{4}\b"),                                          # 3239-2000 (exige hífen)
]

_ASSET_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js", ".ico")
_EMAIL_BAD_DOMAINS = {
    "example.com", "example.org", "sentry.io", "wix.com", "wixpress.com",
    "godaddy.com", "squarespace.com", "domain.com", "email.com", "yourcompany.com",
    "company.com", "empresa.com", "seudominio.com.br", "dominio.com", "dominio.com.br",
    # Diretórios/marketplaces B2B — e-mail deles não é da empresa
    "tradeindia.com", "indiamart.com", "made-in-china.com", "alibaba.com",
    "europages.com", "kompass.com", "thomasnet.com",
    # Plataformas de reserva/marketplace: o e-mail é da plataforma, não do lead.
    "booking.com", "tripadvisor.com", "expedia.com",
    # Bases de CNPJ e diretórios BR — dado agregado, não contato do prospecto.
    "econodata.com.br", "casadosdados.com.br", "cnpj.biz", "empresascnpj.com",
    "solutudo.com.br", "telelistas.net", "apontador.com.br", "escavador.com",
    # Órgãos e reguladores: sites linkam a ouvidoria de órgãos no rodapé. É e-mail
    # do órgão, não da empresa — entregá-lo seria um lead falso.
    "gov.br", "procon.sp.gov.br",
    # Domínios-modelo que ficam esquecidos em template de site.
    "site.com.br", "seusite.com.br", "meusite.com.br", "empresa.com.br",
    "exemplo.com.br", "teste.com.br", "dominio.com.br",
}
_EMAIL_BAD_LOCAL = {"email", "your", "name", "user", "username", "seuemail", "john", "jane",
                    "seu.nome", "seunome", "nome.sobrenome", "exemplo", "teste"}
_EMAIL_FREE_DOMAINS = {
    "gmail.com", "googlemail.com", "hotmail.com", "hotmail.co.uk", "outlook.com",
    "live.com", "msn.com", "yahoo.com", "yahoo.co.uk", "ymail.com", "aol.com",
    "icloud.com", "me.com", "gmx.com", "gmx.net", "protonmail.com", "proton.me",
    "mail.com", "yandex.com", "yandex.ru", "mail.ru", "qq.com", "163.com",
    "126.com", "sina.com", "foxmail.com", "zoho.com",
}

# Locais (parte antes do @) por TEMPERATURA — quem tem mais chance de RESPONDER
# um e-mail frio de fornecedor. A ordem vem da prática de prospecção B2B:
# uma pessoa com nome responde; uma caixa de decisão responde; o SAC nunca.
# Nada aqui inventa endereço: só ordena o que o site publicou.
_LOCAL_DECIDE = ("diretoria", "diretor", "presidencia", "presidente", "gerencia",
                 "gerente", "socio", "ceo", "owner", "proprietario")
_LOCAL_BUY = ("compras", "suprimentos", "purchasing", "procurement", "supply")
_LOCAL_SALES = ("comercial", "vendas", "venda", "sales", "negocios", "cotacao",
                "orcamento", "propostas", "proposta")
# Genéricos. As palavras de operação próprias do nicho entram em _ops().
_LOCAL_OPS = ("operacional", "operacoes", "operacao", "manutencao", "producao", "logistica")
_LOCAL_TECH = ("ti", "tecnologia", "engenharia", "projetos", "qualidade", "seguranca",
               "planejamento", "rh", "financeiro", "administrativo", "administracao",
               "adm", "documentacao", "documentos", "fiscal", "cobranca", "faturamento",
               "contabilidade", "contabil", "expedicao", "almoxarifado", "pessoal",
               "marketing", "mkt")
# Caixas GERAIS — chegam a alguém, mas sem dono definido.
_LOCAL_GENERIC = ("contato", "faleconosco", "fale", "relacionamento", "contact",
                  "info", "hello", "mail", "email", "geral", "empresa")
# Atendimento ao CONSUMIDOR: quem lê atende passageiro, não fornecedor. Pior aposta
# entre as caixas válidas — mas ainda é um canal, então não é descartado.
_LOCAL_SAC = ("sac", "atendimento", "ouvidoria", "suporte", "support", "reservas",
              "reserva", "passagens", "vendasonline", "posvenda", "pos-venda",
              "posvendas", "pos-vendas")
_LOCAL_BAD = ("imprensa", "press", "midia", "media", "juridico", "legal", "lgpd",
              "privacidade", "compliance", "noreply", "no-reply", "investidor",
              "investor", "webmaster", "abuse", "postmaster", "dpo", "comunicacao",
              "curriculo", "curriculos", "vagas", "recrutamento", "trabalheconosco",
              # redação/pauta: quem responde é jornal, e jornal não é comprador.
              # 'redacao@' também denuncia que o lead é portal de notícia.
              "redacao", "jornalismo", "editorial", "pauta", "anuncie", "publicidade")
# Palavras que provam que um token ÚNICO não é nome de pessoa (ex.: "matriz@",
# "filial@"). Sem esta lista, qualquer palavra viraria "pessoa". As do nicho
# entram em _nao_pessoa().
_LOCAL_NOT_PERSON = ("matriz", "filial", "unidade", "loja", "site",
                     "web", "adm", "administracao", "administrativo", "escritorio",
                     "agencia", "central", "grupo", "locacao", "aluguel", "servicos",
                     "servico", "vendas", "loja",
                     # lugares e siglas que aparecem como sufixo de caixa por praça
                     "brasil", "brazil", "sao", "paulo", "rio", "janeiro", "minas",
                     "norte", "sul", "leste", "oeste", "centro", "nacional", "regional",
                     "online", "oficial", "novo", "nova", "casa", "home", "portal")


def _ops() -> tuple[str, ...]:
    """Palavras de operação: genéricas + as do nicho (ex.: "cozinha@")."""
    from . import nicho as _nicho
    return _LOCAL_OPS + _nicho.normalizados(_nicho.ativo().email_operacao)


def _nao_pessoa() -> tuple[str, ...]:
    from . import nicho as _nicho
    return _LOCAL_NOT_PERSON + _nicho.normalizados(_nicho.ativo().email_nao_pessoa)


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def _valid_email(email: str) -> bool:
    email = email.lower().strip().strip(".")
    if email.endswith(_ASSET_EXT) or "@" not in email:
        return False
    local, _, domain = email.partition("@")
    if local in _EMAIL_BAD_LOCAL:
        return False
    if any(domain == b or domain.endswith("." + b) for b in _EMAIL_BAD_DOMAINS):
        return False  # rejeita também subdomínios (ex.: sentry-next.wixpress.com)
    if len(local) > 25 and all(ch in "0123456789abcdef" for ch in local):
        return False  # hash de rastreamento (Sentry/Wix), não é e-mail real
    # domínios grátis (gmail etc.) são ACEITOS, mas rebaixados no ranking
    return len(local) <= 64 and "." in domain


def _tokens(local: str) -> list[str]:
    """Quebra o local em palavras: 'joao.silva', 'joao_silva' e 'joao-silva'."""
    return [t for t in re.split(r"[._\-]+", local) if t]


def _e_a_propria_empresa(token: str, domain: str) -> bool:
    """O token é o nome da EMPRESA (acme@acmets.exemplo.com)?

    Esse endereço é a caixa da casa, não a de uma pessoa. Sem esta checagem,
    'casaexemplo@casaexemplo.com.br' seria anunciado ao vendedor como um contato
    nominal — e ele escreveria "Olá, Casaexemplo" para uma caixa geral.
    """
    raiz = (domain or "").split(".")[0]
    if not raiz or len(token) < 4:
        return False
    # Substring em QUALQUER posição: além de 'motrix@motrixts', pega o sobrenome
    # de família que virou razão social ('silva@transportessilva'). Custa algum
    # falso negativo — uma pessoa rotulada como caixa geral —, e esse é o erro
    # certo: o vendedor pode ser surpreendido por um humano, nunca o contrário.
    if token in raiz or raiz in token:
        return True
    comuns = 0
    for a, b in zip(token, raiz):
        if a != b:
            break
        comuns += 1
    return comuns >= 5


def _parece_pessoa(local: str, domain: str = "") -> bool:
    """O local é o nome de uma PESSOA (joao, joao.silva, moisesmarques.ti)?

    Regra: pelo menos um token com 4+ letras que não é palavra de função, de
    lugar, nem o nome da própria empresa — esse token é o nome. Os outros podem
    ser área ("joao.comercial" é o João do comercial, uma pessoa). Caixas de
    porta nunca passam, mesmo com sufixo ('contato.sp' segue caixa geral).

    É um palpite pelo que sobrou, então erra para o lado conservador: o rótulo
    pode sair mais frio que a realidade. Nenhum endereço é inventado.
    """
    parts = _tokens(local)
    if not parts or len(parts) > 3:
        return False
    if any(not p.isalpha() or len(p) > 16 for p in parts):
        return False
    # Substring, não igualdade: "falecom" carrega "fale" e é caixa geral.
    frias = _LOCAL_GENERIC + _LOCAL_SAC + _LOCAL_BAD + _nao_pessoa()
    if any(k in p for p in parts for k in frias):
        return False
    funcoes = _LOCAL_DECIDE + _LOCAL_BUY + _LOCAL_SALES + _ops() + _LOCAL_TECH
    return any(len(p) >= 4 and not any(f in p for f in funcoes)
               and not _e_a_propria_empresa(p, domain) for p in parts)


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto or "")
                   if unicodedata.category(c) != "Mn")


def _bate_com_decisor(local: str, person_hint: str) -> bool:
    """O e-mail é da pessoa que o site apontou como decisor?

    Duas formas contam: um token inteiro em comum ('fulano@' com 'Fulano
    Prado') ou dois pedaços do nome grudados no local ('vitorcorreia@' com
    'Vitor Correia'). Um pedaço só, grudado, não basta — 'ana' vive dentro de
    'anacleto', e um falso positivo aqui promete ao vendedor um decisor que não
    está do outro lado.
    """
    if not person_hint:
        return False
    nome = {t for t in re.split(r"[^a-z]+", _sem_acento(person_hint).lower()) if len(t) >= 3}
    if not nome:
        return False
    partes = [t for t in _tokens(_sem_acento(local).lower()) if len(t) >= 3]
    if nome & set(partes):
        return True
    grudado = "".join(partes)
    return sum(1 for t in nome if t in grudado) >= 2


# Escala de TEMPERATURA do e-mail (maior = mais chance de resposta útil).
RANK_DECISOR_NOMINAL = 10  # pessoa que o próprio site aponta como decisora
RANK_PESSOA = 9            # e-mail de gente (joao.silva@) — alguém lê e responde
RANK_DECIDE = 8            # diretoria@, gerencia@
RANK_COMPRAS = 7
RANK_COMERCIAL = 6
RANK_OPERACAO = 5
RANK_TECNICO = 4           # ti@, financeiro@, marketing@ — função conhecida
RANK_INDEFINIDO = 3        # 'rva2147@' — não dá para dizer quem lê
RANK_GERAL = 2             # contato@, info@
RANK_SAC = 1               # atende passageiro, não fornecedor
RANK_DESCARTE = 0


def _email_rank(local: str, person_hint: str = "", domain: str = "") -> int:
    """Temperatura do e-mail: pessoa (9/8) > decisão (7) > comercial (5) > geral (2) > SAC (1).

    A ordem responde a "quem lê isso e responde": uma caixa com nome de pessoa
    tem dono; ``contato@`` cai numa triagem; ``sac@`` existe para o passageiro
    reclamar. Antes o topo era compras/operação — bom para quem sente a dor,
    ruim para taxa de resposta em e-mail frio.
    """
    if any(k in local for k in _LOCAL_BAD):
        return RANK_DESCARTE
    if _parece_pessoa(local, domain):
        return RANK_DECISOR_NOMINAL if _bate_com_decisor(local, person_hint) else RANK_PESSOA
    if any(k in local for k in _LOCAL_DECIDE):
        return RANK_DECIDE
    if any(k in local for k in _LOCAL_BUY):
        return RANK_COMPRAS
    # SAC vem ANTES de vendas de propósito: "pos-venda@" e "vendasonline@" carregam
    # a palavra venda, mas quem abre essas caixas cuida de quem JÁ é cliente.
    if any(k in local for k in _LOCAL_SAC):
        return RANK_SAC
    if any(k in local for k in _LOCAL_SALES):
        return RANK_COMERCIAL
    if any(k in local for k in _ops()):
        return RANK_OPERACAO
    if any(k in local for k in _LOCAL_TECH):
        return RANK_TECNICO
    if any(k in local for k in _LOCAL_GENERIC):
        return RANK_GERAL
    # A caixa com o nome da casa (casaexemplo@casaexemplo.com.br) é uma caixa geral,
    # não uma área — quem abre é quem cuida do e-mail da empresa.
    if _e_a_propria_empresa(local, domain):
        return RANK_GERAL
    # Sobrou o ilegível ('rva2147@'): fica no meio, e o rótulo NÃO finge saber
    # quem abre a caixa — anunciar "Área técnica" aqui seria inventar.
    return RANK_INDEFINIDO


def _unescape(html: str) -> str:
    """Resolve escapes JSON (\\u003e) e entidades HTML (&gt;) ANTES de varrer e-mails.

    Sem isso, um '>' escapado vaza para o endereço (ex.: '\\u003eadm@x.com' virava
    'u003eadm@x.com'). Após resolver, '<'/'>'/'&' viram limites do e-mail.
    """
    h = html or ""
    h = (h.replace("\\u003e", ">").replace("\\u003c", "<").replace("\\u0026", "&")
           .replace("\\u0022", '"').replace("\\u0027", "'"))
    h = (h.replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&")
           .replace("&#62;", ">").replace("&#60;", "<"))
    return h


def _deobfuscate(html: str) -> str:
    """Converte 'nome [at] dominio [dot] com' em e-mail real (só formas com colchete/parêntese)."""
    return _OBF_DOT.sub(".", _OBF_AT.sub("@", html or ""))


def _same_business(domain: str, prefer_domain: str) -> bool:
    """O domínio do e-mail pertence à MESMA empresa que o site do lead?

    Muitos operadores usam um domínio comercial diferente do site
    (``grupoexemplo.com.br`` -> ``grupoexemploeventos.com.br``): é a mesma
    casa e o e-mail vale. Mas um site que apenas LINKA um parceiro
    (``transexemplo`` -> ``parceiroexemplo.com``) não pode emprestar o contato dele —
    entregar isso é atribuir o e-mail de uma empresa a outra.

    Critério: um rótulo contém o outro, ou os dois partilham 5+ letras iniciais.
    """
    a = (domain or "").split(".")[0]
    b = (prefer_domain or "").split(".")[0]
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    common = 0
    for ca, cb in zip(a, b):
        if ca != cb:
            break
        common += 1
    return common >= 5


def extract_emails_ranked(html: str, prefer_domain: str = "",
                          person_hint: str = "") -> list[tuple[str, int]]:
    """Todos os e-mails públicos válidos, do mais QUENTE para o mais frio.

    Devolve pares ``(email, rank)``. Serve para escolher o melhor e, quando o
    melhor é uma caixa geral, oferecer o segundo canal ao vendedor.
    """
    html = _unescape(html or "")
    candidates: list[str] = []
    for raw in _MAILTO_RE.findall(html):
        candidates.append(raw.split("?")[0])
    candidates.extend(_EMAIL_RE.findall(_deobfuscate(html)))

    achados: list[tuple[tuple[int, int, int], str]] = []
    seen: set[str] = set()
    for email in candidates:
        email = email.lower().strip().strip(".")
        if email in seen:
            continue
        seen.add(email)
        if not _valid_email(email):
            continue
        local, _, domain = email.partition("@")
        # Compara com o domínio do SITE: no gmail o domínio do e-mail nada diz sobre
        # a empresa, e 'vansexemplo@hotmail.com' também é a caixa da própria casa.
        rank = _email_rank(local, person_hint, prefer_domain or domain)
        if rank == RANK_DESCARTE:   # noreply, lgpd, juridico, imprensa, vagas -> ignora
            continue
        match = 1 if (prefer_domain and (domain == prefer_domain or domain.endswith("." + prefer_domain))) else 0
        free = domain in _EMAIL_FREE_DOMAINS
        # Domínio corporativo de OUTRA empresa -> descarta. É o caso do site que linka
        # um parceiro: melhor entregar o lead sem e-mail do que com o e-mail errado.
        # Provedor grátis passa (o pequeno operador usa gmail mesmo).
        if not match and not free and prefer_domain and not _same_business(domain, prefer_domain):
            continue
        # Domínio próprio > corporativo > grátis; só então a temperatura decide.
        achados.append(((match, 0 if free else 1, rank), email))
    achados.sort(key=lambda x: x[0], reverse=True)
    return [(email, chave[2]) for chave, email in achados]


def promover_decisor(ranked: list[tuple[str, int]], person_hint: str) -> list[tuple[str, int]]:
    """Reordena a lista já extraída quando o decisor do site tem e-mail próprio.

    O decisor só é identificado DEPOIS da extração (ele precisa das soluções
    detectadas), e varrer o HTML inteiro de novo custa caro. Como a lista já vem
    ordenada por qualidade de domínio, basta promover o endereço que carrega o
    nome dele — sem inventar nada: o e-mail já estava publicado no site.
    """
    if not person_hint or not ranked:
        return ranked
    for i, (email, _rank) in enumerate(ranked):
        if _bate_com_decisor(email.partition("@")[0], person_hint):
            promovido = (email, RANK_DECISOR_NOMINAL)
            return [promovido] + ranked[:i] + ranked[i + 1:]
    return ranked


def temperatura_email(email: str, person_hint: str = "", site_domain: str = "") -> int:
    """Rank de um e-mail já escolhido — inclusive o que veio da Receita/JSON-LD,
    que nunca passou pela lista ranqueada do site."""
    local, _, domain = (email or "").lower().partition("@")
    if not local:
        return RANK_DESCARTE
    return _email_rank(local, person_hint, site_domain or domain)


def rotulo_email(rank: int) -> str:
    """Como o vendedor lê a temperatura na planilha. Descreve, não promete."""
    if rank <= RANK_DESCARTE:   # e-mail que nem chega a ser entregue
        return ""
    if rank >= RANK_DECISOR_NOMINAL:
        return "Decisor (nominal)"
    if rank >= RANK_PESSOA:
        return "Pessoa"
    if rank >= RANK_DECIDE:
        return "Diretoria"
    if rank >= RANK_COMPRAS:
        return "Compras"
    if rank >= RANK_COMERCIAL:
        return "Comercial"
    if rank >= RANK_OPERACAO:
        return "Operação"
    if rank >= RANK_TECNICO:
        return "Área técnica"
    if rank >= RANK_INDEFINIDO:
        return "Não identificado"
    if rank >= RANK_GERAL:
        return "Caixa geral"
    return "Atendimento"


def extract_email(html: str, prefer_domain: str = "", person_hint: str = "") -> str:
    """Retorna o e-mail público mais quente: pessoa > decisão > comercial > geral."""
    ranked = extract_emails_ranked(html, prefer_domain, person_hint)
    return ranked[0][0] if ranked else ""


def _plausible_phone(candidate: str) -> bool:
    digits = _digits(candidate)
    if not (8 <= len(digits) <= 13):
        return False
    if len(set(digits)) <= 1:           # 00000000 (placeholder)
        return False
    cand = candidate.strip()
    if _DATE_LIKE.match(cand) or _YEAR_RANGE.match(cand):
        return False
    return True


# DDDs válidos do Brasil — rejeita "telefones" com código de área inexistente.
_DDDS = {
    11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 24, 27, 28,
    31, 32, 33, 34, 35, 37, 38, 41, 42, 43, 44, 45, 46, 47, 48, 49,
    51, 53, 54, 55, 61, 62, 63, 64, 65, 66, 67, 68, 69,
    71, 73, 74, 75, 77, 79, 81, 82, 83, 84, 85, 86, 87, 88, 89,
    91, 92, 93, 94, 95, 96, 97, 98, 99,
}
# Contexto que confirma "isto é um telefone" (para números curtos sem DDD).
_PHONE_CONTEXT = re.compile(r"(?i)(tel|fone|telefone|whats|contato|ligue|call|phone|0800|atendimento|fale)")


def _valid_br_phone(d: str) -> bool:
    """Valida a estrutura real de um telefone brasileiro (DDD + fixo/celular).

    0800 é REJEITADO de propósito: queremos número direto (com DDD) para a conversão.
    """
    if d.startswith("0800"):
        return False
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    if len(d) == 11:                      # celular: DDD + 9XXXXXXXX
        return int(d[:2]) in _DDDS and d[2] == "9"
    if len(d) == 10:                      # fixo: DDD + assinante (começa em 2-5)
        return int(d[:2]) in _DDDS and d[2] in "2345"
    return False


def _format_phone(digits: str) -> str:
    """Formata dígitos como telefone BR legível."""
    if digits.startswith("0800") and len(digits) in (10, 11):
        rest = digits[4:]
        return f"0800 {rest[:3]} {rest[3:]}"
    cc = ""
    if digits.startswith("55") and len(digits) in (12, 13):
        digits, cc = digits[2:], "+55 "
    if len(digits) == 11:
        return f"{cc}({digits[:2]}) {digits[2:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"{cc}({digits[:2]}) {digits[2:6]}-{digits[6:]}"
    return (cc + digits).strip()


def _format_intl(digits: str, raw: str = "", force_intl: bool = False) -> str:
    """BR vira formato BR; internacional mantém a formatação do site (ou +dígitos).

    ``force_intl`` (lead de fora do Brasil) NUNCA formata como BR — evita mostrar um
    número estrangeiro como '(71) ...' por colidir com um DDD brasileiro.
    """
    if not force_intl and _valid_br_phone(digits):
        return _format_phone(digits)
    r = (raw or "").strip()
    if r and (any(c in r for c in "()+") or re.search(r"\d[\s.\-]\d", r)):
        return re.sub(r"\s+", " ", r)              # preserva a formatação do site
    return ("+" + digits) if len(digits) >= 11 else digits


def extract_phone(html: str, country: str = "") -> str:
    """Telefone público — BR validado (DDD/fixo/celular) + internacional (tel:/WhatsApp/texto).

    ``country`` = país detectado do lead. Se for FORA do Brasil, nunca formata como BR e
    aceita números estrangeiros com estrutura/contexto — cobre leads internacionais.
    """
    html = html or ""
    intl = bool(country) and country not in ("Brazil", "")

    # 1) Fontes EXPLÍCITAS (tel: e WhatsApp) — confiáveis; aceitam BR e internacional.
    explicit: list[tuple[str, str]] = []          # (dígitos, texto original)
    for raw in _TEL_RE.findall(html):
        d = _digits(raw)
        if d.startswith("0800"):          # 0800 não interessa — queremos número direto
            continue
        if 8 <= len(d) <= 15 and len(set(d)) > 2 and not (_DATE_LIKE.match(raw.strip()) or _YEAR_RANGE.match(raw.strip())):
            explicit.append((d, raw.strip()))
    for raw in _WHATSAPP_RE.findall(html):
        d = _digits(raw)
        if 10 <= len(d) <= 15 and len(set(d)) > 2:
            explicit.append((d, "+" + d))
    if not intl:
        for d, _raw in explicit:                   # BR primeiro (formato bonito)
            if _valid_br_phone(d):
                return _format_phone(d)
    for d, raw in explicit:                        # senão, o primeiro (internacional)
        return _format_intl(d, raw, force_intl=intl)

    # 2) Texto visível: BR válido (parênteses/contexto) OU internacional (com +código ou estrutura+contexto).
    clean = _SCRIPT_RE.sub(" ", html)
    for pattern in _PHONE_PATTERNS:
        for m in pattern.finditer(clean):
            match = m.group(0)
            d = _digits(match)
            if not (8 <= len(d) <= 15) or len(set(d)) <= 1:
                continue
            if _DATE_LIKE.match(match.strip()) or _YEAR_RANGE.match(match.strip()):
                continue
            if d.startswith("0800"):          # 0800 não interessa — queremos número direto
                continue
            strong = ("(" in match) or match.lstrip().startswith("+")
            has_ctx = bool(_PHONE_CONTEXT.search(clean[max(0, m.start() - 30):m.start()]))
            if not intl:                          # lead BR/indef: valida estrutura BR primeiro
                cell = len(d) == 11 or (d.startswith("55") and len(d) == 13)
                if _valid_br_phone(d):
                    if strong or has_ctx or cell:
                        return _format_phone(d)
                    continue
            if match.lstrip().startswith("+") and 9 <= len(d) <= 15:   # internacional explícito (+código)
                return _format_intl(d, match, force_intl=intl)
            # Internacional SEM '+' (ex.: sites alemães/sauditas): exige ESTRUTURA + contexto de telefone.
            if 9 <= len(d) <= 15 and has_ctx and (strong or "-" in match or "." in match or " " in match):
                return _format_intl(d, match, force_intl=intl)
            if len(d) in (8, 9) and "-" in match and has_ctx:          # curto sem DDD
                return re.sub(r"\s+", " ", match).strip()
    return ""
