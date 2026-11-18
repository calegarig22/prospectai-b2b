"""Filtro de prospecção por REGIÃO DO BRASIL.

O ProspectAI prospecta no mercado brasileiro — o escopo é sempre o Brasil. O usuário pode, opcionalmente, focar uma macro-região. Cada
entrada define:
  - ``countries``: países aceitos no PORTÃO de entrega. Aqui é sempre ``Brazil``,
    em TODAS as regiões (inclusive "Brasil inteiro") — é o que mantém o funil
    exclusivamente brasileiro e descarta lead de país comprovadamente diferente.
  - ``query``: estados/cidades usados para DECORAR as buscas (skewa os resultados
    para aquela região sem precisar de detecção de UF no lead).
  - ``lang``: viés de idioma das buscas — sempre ``pt``.

Nota de projeto: NÃO existe filtro por Estado/UF no painel. Ele foi testado e
descartado em uso real (jun/2026); aqui a granularidade para no
nível de macro-região, que já concentra a busca sem poluir a interface.
"""

from __future__ import annotations

# Opção padrão do painel: Brasil inteiro. É uma REGIÃO de verdade (está em
# CONTINENTS), então o portão de país vale mesmo sem o usuário escolher nada.
WORLD = "Brasil inteiro"

CONTINENTS: dict[str, dict] = {
    WORLD: {
        "countries": {"Brazil"},
        "query": ["Brasil", "São Paulo", "Minas Gerais", "Rio de Janeiro", "Paraná",
                  "Santa Catarina", "Rio Grande do Sul", "Bahia", "Goiás", "Pernambuco",
                  "Ceará", "Espírito Santo", "Mato Grosso", "Pará"],
        "lang": "pt",
    },
    "Sudeste": {
        "countries": {"Brazil"},
        "query": ["São Paulo", "Minas Gerais", "Rio de Janeiro", "Espírito Santo",
                  "Campinas", "Belo Horizonte", "Ribeirão Preto", "ABC paulista",
                  "Vitória ES", "interior de São Paulo", "Sorocaba", "São José dos Campos",
                  "Uberlândia", "Juiz de Fora"],
        "lang": "pt",
    },
    "Sul": {
        "countries": {"Brazil"},
        "query": ["Paraná", "Santa Catarina", "Rio Grande do Sul", "Curitiba",
                  "Porto Alegre", "Florianópolis", "Joinville", "Caxias do Sul",
                  "Londrina", "Blumenau", "Maringá", "Pelotas", "Chapecó"],
        "lang": "pt",
    },
    "Nordeste": {
        "countries": {"Brazil"},
        "query": ["Bahia", "Pernambuco", "Ceará", "Maranhão", "Rio Grande do Norte",
                  "Paraíba", "Alagoas", "Sergipe", "Piauí", "Salvador", "Recife",
                  "Fortaleza", "Natal", "São Luís", "Maceió", "Feira de Santana"],
        "lang": "pt",
    },
    "Centro-Oeste": {
        "countries": {"Brazil"},
        "query": ["Goiás", "Mato Grosso", "Mato Grosso do Sul", "Distrito Federal",
                  "Goiânia", "Brasília", "Cuiabá", "Campo Grande", "Anápolis",
                  "Rondonópolis", "Dourados"],
        "lang": "pt",
    },
    "Norte": {
        "countries": {"Brazil"},
        "query": ["Pará", "Amazonas", "Rondônia", "Tocantins", "Acre", "Amapá",
                  "Roraima", "Belém", "Manaus", "Porto Velho", "Palmas", "Rio Branco",
                  "Santarém", "Marabá"],
        "lang": "pt",
    },
}

# Rótulos para o painel (Brasil inteiro primeiro = padrão).
REGION_LABELS = list(CONTINENTS.keys())


def continent_of(country: str | None) -> str | None:
    """Uma região que contém o país (a primeira que casar), ou ``None`` se desconhecido."""
    c = (country or "").strip()
    for label, d in CONTINENTS.items():
        if c in d["countries"]:
            return label
    return None


def is_region(label: str | None) -> bool:
    """True se ``label`` é uma região válida (i.e., um filtro ativo)."""
    return bool(label) and label in CONTINENTS


def keep_for_region(country: str | None, region: str | None) -> bool:
    """Portão de entrega: mantém o lead para a região escolhida?

    - Lead com país BRASIL -> mantém.
    - Qualquer OUTRO país identificado -> descarta (o escopo é o Brasil).
    - País indeterminado (o site não revela) -> MANTÉM. A maioria dos sites de
      empresas brasileiras não declara o país; descartá-los esvaziaria
      a lista. O ranking já prioriza os leads com Brasil confirmado.
    """
    if not is_region(region):
        return True
    c = (country or "").strip()
    if not c:
        return True                       # indeterminado -> mantém
    return c in CONTINENTS[region]["countries"]


def in_region_confirmed(country: str | None, region: str | None) -> bool:
    """True só quando o país PERTENCE de fato à região-alvo (usado p/ priorizar no ranking)."""
    return is_region(region) and (country or "").strip() in CONTINENTS[region]["countries"]
