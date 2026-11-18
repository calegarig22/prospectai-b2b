"""Etapa "Cargo decisor" e "LinkedIn" do fluxo.

Dois problemas diferentes, resolvidos aqui:

1. **LinkedIn** — puramente extração: o link da empresa quase sempre está no
   rodapé do site. Devolvemos a URL da PÁGINA DA EMPRESA (``/company/...``),
   nunca um perfil pessoal encontrado por acaso.

2. **Cargo decisor** — duas camadas, nesta ordem:
   a. Se o site expõe um nome com cargo ("João Silva — Gerente de Operações",
      página Sobre/Equipe/Diretoria), devolvemos o cargo REAL e o nome.
   b. Senão, devolvemos o cargo-ALVO recomendado, derivado da necessidade
      identificada: cada solução do nicho diz quem costuma comprá-la
      (``solucoes[].decisor``); sem nenhuma, vale ``decisores.padrao``.
   A camada (b) é uma RECOMENDAÇÃO de abordagem, não um dado do lead — por isso
   ``role_source`` diz de onde veio, e o painel/planilha mostram isso.

Só dados publicamente disponíveis no próprio site da empresa (LGPD).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import nicho as _nicho
from .utils import strip_accents

# LinkedIn da EMPRESA (aceita /company/ e /school/; ignora /in/ = perfil pessoal).
_LINKEDIN_RE = re.compile(
    r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/(?:company|school)/([A-Za-z0-9_%.\-]+)",
    re.IGNORECASE,
)

# Cargos GENÉRICOS que decidem compra B2B, do mais decisor para o menos.
# Os cargos próprios do nicho entram somados a estes (``decisores.cargos``).
# (termo normalizado sem acento, rótulo exibido, prioridade)
_ROLE_TERMS: list[tuple[str, str, int]] = [
    ("diretor de operacoes", "Diretor de Operações", 95),
    ("diretora de operacoes", "Diretora de Operações", 95),
    ("diretor operacional", "Diretor Operacional", 94),
    ("gerente de operacoes", "Gerente de Operações", 90),
    ("coordenador de operacoes", "Coordenador de Operações", 84),
    ("diretor de manutencao", "Diretor de Manutenção", 86),
    ("gerente de manutencao", "Gerente de Manutenção", 83),
    ("gerente de seguranca", "Gerente de Segurança", 82),
    ("gestor de seguranca", "Gestor de Segurança", 81),
    ("diretor comercial", "Diretor Comercial", 89),
    ("diretora comercial", "Diretora Comercial", 89),
    ("gerente comercial", "Gerente Comercial", 80),
    ("diretor de tecnologia", "Diretor de Tecnologia", 87),
    ("gerente de ti", "Gerente de TI", 78),
    ("coordenador de ti", "Coordenador de TI", 74),
    ("gerente de compras", "Gerente de Compras", 79),
    ("comprador", "Comprador", 70),
    ("gerente de suprimentos", "Gerente de Suprimentos", 77),
    ("gerente de produto", "Gerente de Produto", 72),
    ("diretor de marketing", "Diretor de Marketing", 71),
    ("diretor presidente", "Diretor-Presidente", 98),
    ("presidente", "Presidente", 96),
    ("diretor geral", "Diretor-Geral", 97),
    ("diretor executivo", "Diretor Executivo", 96),
    ("socio proprietario", "Sócio-Proprietário", 94),
    ("proprietario", "Proprietário", 90),
    ("fundador", "Fundador", 90),
    ("ceo", "CEO", 97),
    ("coo", "COO", 93),
    ("cto", "CTO", 86),
    ("diretor", "Diretor", 75),
    ("gerente", "Gerente", 60),
]

# Nome próprio brasileiro: 2 a 4 palavras capitalizadas, conectores minúsculos aceitos.
_NAME_RE = re.compile(
    r"\b([A-ZÁÂÃÀÉÊÍÓÔÕÚÇ][a-záâãàéêíóôõúç]{2,}"
    r"(?:\s+(?:d[aeo]s?|e)\s+|\s+)"
    r"[A-ZÁÂÃÀÉÊÍÓÔÕÚÇ][a-záâãàéêíóôõúç]{2,}"
    r"(?:\s+(?:d[aeo]s?|e)?\s*[A-ZÁÂÃÀÉÊÍÓÔÕÚÇ][a-záâãàéêíóôõúç]{2,}){0,2})\b"
)
# Palavras que denunciam que o "nome" é na verdade um trecho institucional.
_NOT_A_NAME = {
    "nossa historia", "fale conosco", "quem somos", "nossos servicos", "politica de",
    "termos de", "central de", "trabalhe conosco", "sao paulo", "rio de janeiro",
    "minas gerais", "belo horizonte", "porto alegre", "santa catarina", "mato grosso",
    "espirito santo", "rio grande", "brasil ltda", "empresa de",
}


@dataclass
class Decisor:
    """Contato decisor de um lead. Campos vazios quando não há evidência."""

    name: str = ""              # nome da pessoa, só se achado no site
    role: str = ""              # cargo (real do site, ou o alvo recomendado)
    role_source: str = ""       # "site" (achado) | "recomendado" (derivado da necessidade)
    linkedin: str = ""          # URL do LinkedIn da EMPRESA

    @property
    def is_real(self) -> bool:
        """True quando o cargo veio de fato do site do lead."""
        return self.role_source == "site"


def extract_linkedin(html: str) -> str:
    """URL do LinkedIn da empresa encontrada no HTML, ou string vazia.

    Devolve a forma canônica ``https://www.linkedin.com/company/<slug>``. Ignora
    perfis pessoais (``/in/``) e os links institucionais do próprio LinkedIn.
    """
    for slug in _LINKEDIN_RE.findall(html or ""):
        s = slug.strip("/").lower()
        if not s or s in {"linkedin", "unknown", "setup", "showcase"}:
            continue
        return f"https://www.linkedin.com/company/{s}"
    return ""


def _looks_like_name(candidate: str) -> bool:
    norm = strip_accents(candidate.lower())
    return not any(bad in norm for bad in _NOT_A_NAME)


# Separador aceito entre nome e cargo: só pontuação/espaço, no máximo 3 chars.
# É isso que distingue "Marcos Lima — Gerente de Operações" (par real) de
# "...do presidente. Conheça a equipe: Marcos Lima" (proximidade acidental).
_SEP_AFTER = re.compile(r"^[\s—–\-,:|(]{0,3}")
_SEP_BEFORE = re.compile(r"[\s—–\-,:|)]{0,3}$")
_NAME_AT_START = re.compile(r"^" + _NAME_RE.pattern.strip())
_NAME_AT_END = re.compile(_NAME_RE.pattern.strip() + r"$")


def _find_role_in_site(text: str) -> tuple[str, str]:
    """Melhor par (nome, cargo) exposto no site. Vazio quando não há evidência.

    Só aceita nome e cargo ENCOSTADOS, separados no máximo por pontuação — os dois
    lados são testados, então "Carlos Menezes — Diretor de Operações" e "Diretor de
    Operações: Carlos Menezes" caem no mesmo caminho. Sem essa exigência de
    adjacência, qualquer nome citado perto de um cargo virava um par falso.
    """
    raw = re.sub(r"\s+", " ", text or "")
    norm = strip_accents(raw).lower()
    if len(norm) != len(raw):              # normalização mexeu no tamanho: sem índices
        raw = norm                          # confiáveis, trabalha sobre o normalizado
    best_role, best_name, best_key = "", "", (-1, -1)
    extras = [(_nicho.norm(t), r, p) for t, r, p in _nicho.ativo().cargos]
    for term, label, prio in [*extras, *_ROLE_TERMS]:
        if (1, prio) <= best_key:          # nem o melhor caso deste cargo supera
            continue
        for m in re.finditer(r"\b" + re.escape(term) + r"\b", norm):
            name = ""
            after = raw[m.end():m.end() + 60]
            sep = _SEP_AFTER.match(after).group(0)
            cand = _NAME_AT_START.match(after[len(sep):])
            if cand and _looks_like_name(cand.group(1)):
                name = cand.group(1)
            else:
                before = raw[max(0, m.start() - 60):m.start()]
                trimmed = before[:len(before) - len(_SEP_BEFORE.search(before).group(0))]
                cand = _NAME_AT_END.search(trimmed)
                if cand and _looks_like_name(cand.group(1)):
                    name = cand.group(1)
            # Um cargo COM nome sempre ganha de um cargo sem nome, mesmo que o
            # sem-nome seja hierarquicamente maior ("Presidente" solto na página).
            key = (1 if name else 0, prio)
            if key > best_key:
                best_key, best_role, best_name = key, label, name
            if name:
                break                      # já achamos o par deste cargo
    return best_name, best_role


def target_role(solutions: list[str]) -> str:
    """Cargo-alvo recomendado para abordar o lead, dado o que ele precisa.

    Vale a primeira solução detectada (o catálogo já vem em ordem de prioridade)
    que tenha um decisor definido no nicho.
    """
    n = _nicho.ativo()
    por_nome = {s.nome: s.decisor for s in n.solucoes if s.decisor}
    for sol in solutions:
        if sol in por_nome:
            return por_nome[sol]
    return n.decisor_padrao


def find_decisor(html: str, text: str, solutions: list[str]) -> Decisor:
    """Monta o decisor do lead: pessoa real do site quando existe, senão o alvo.

    ``html`` é usado para o LinkedIn (precisa dos ``href``); ``text`` é o texto
    visível das páginas (home + Sobre/Equipe/Contato) para nome e cargo.

    Exigimos o NOME junto do cargo para chamar de "site". Um "Diretor" solto no
    meio da página é quase sempre uma menção genérica ("fale com nosso diretor")
    — devolvê-lo como decisor daria a impressão falsa de um contato apurado. Sem
    nome, entregamos o cargo-alvo, que é uma recomendação honesta de abordagem.
    """
    name, role = _find_role_in_site(text)
    if name and role:
        return Decisor(name=name, role=role, role_source="site",
                       linkedin=extract_linkedin(html))
    return Decisor(name="", role=target_role(solutions), role_source="recomendado",
                   linkedin=extract_linkedin(html))
