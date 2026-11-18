"""Estruturas de dados do domínio.

Mantém os modelos isolados do restante do código para facilitar a expansão
futura (ex.: adicionar setor, score ou contatos em versões posteriores).
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Colunas do Excel bruto (V1), do Excel pontuado (V1.2) e do Excel de leads HOT
# enriquecidos (V1.3). Centralizadas aqui para manter escritor e modelos em sincronia.
EXCEL_COLUMNS = ["Company", "Website", "SearchKeyword", "Title", "Description"]
EXCEL_COLUMNS_SCORED = EXCEL_COLUMNS + ["Score", "Classification", "KeywordsFound"]
# Colunas do arquivo final de oportunidades (hot_leads.xlsx) — conjunto enxuto e
# acionável, na ordem do fluxo: quem é, o que precisa, por quem se fala, como falar.
# "Soluções" = itens do catálogo do cliente que a empresa demonstra precisar (nicho).
# "Porte" = o tamanho que ela publica ou a classe da Receita (ver app/porte.py).
EXCEL_COLUMNS_HOT = [
    "Company", "Porte", "Soluções", "Email", "TipoEmail", "Phone", "LinkedIn",
    "City", "Situação", "Desde", "Score", "Classification", "Website",
]


@dataclass
class Lead:
    """Representa uma empresa candidata encontrada em uma busca.

    Os campos de enriquecimento (``score``, ``classification``,
    ``keywords_found``) começam vazios e são preenchidos na etapa V1.2.
    """

    company: str
    website: str
    search_keyword: str
    title: str
    description: str
    score: int = 0
    classification: str = ""
    keywords_found: list[str] = field(default_factory=list)

    def to_row(self) -> dict[str, object]:
        """Converte o lead em um dicionário com todas as colunas possíveis.

        O escritor de Excel seleciona apenas as colunas que precisa, de modo
        que o mesmo modelo serve tanto para a planilha bruta quanto a pontuada.
        """
        return {
            "Company": self.company,
            "Website": self.website,
            "SearchKeyword": self.search_keyword,
            "Title": self.title,
            "Description": self.description,
            "Score": self.score,
            "Classification": self.classification,
            "KeywordsFound": ", ".join(self.keywords_found),
        }


@dataclass
class HotLead:
    """Lead HOT enriquecido (V1.3): contatos, geografia e potencial comercial."""

    company: str
    website: str
    score: int = 0
    classification: str = "HOT"
    keywords_found: list[str] = field(default_factory=list)
    solutions: list[str] = field(default_factory=list)
    country: str = ""
    city: str = ""
    phone: str = ""
    email: str = ""
    # Temperatura do e-mail: quem lê a caixa entregue ("Pessoa", "Comercial",
    # "Caixa geral"...). Ver rotulo_email em app/contacts.py.
    email_tipo: str = ""
    contact_page: str = ""
    about_page: str = ""
    # Decisor (ver app/decisor.py): nome só quando o site expõe; cargo é o real do
    # site OU o alvo recomendado — role_source diz qual dos dois.
    contact_name: str = ""
    contact_role: str = ""
    role_source: str = ""
    linkedin: str = ""
    # Porte: porte_numero = quantidade que a empresa publica (0 = não publica),
    # porte = Grande/Média/Pequena, porte_texto = o que vai para a tela ("40 lojas").
    porte_numero: int = 0
    porte: str = ""
    porte_texto: str = ""
    situacao: str = ""      # situação cadastral na Receita (evita empresa baixada)
    desde: str = ""         # ano de abertura
    cnae: str = ""          # atividade principal declarada
    buyer_likelihood: str = "LOW"
    export_potential: str = "LOW"
    recommended_language: str = "Português"

    def to_row(self) -> dict[str, object]:
        """Dicionário com todas as colunas do Excel de leads HOT."""
        return {
            "Company": self.company,
            "Website": self.website,
            "Soluções": ", ".join(self.solutions),
            "Porte": self.porte_texto or self.porte,
            "PorteClasse": self.porte,
            "Situação": self.situacao,
            "Desde": self.desde,
            "Atividade": self.cnae,
            "Decisor": self.contact_name,
            "Cargo": self.contact_role,
            "CargoOrigem": self.role_source,
            "LinkedIn": self.linkedin,
            "Country": self.country,
            "City": self.city,
            "Phone": self.phone,
            "Email": self.email,
            "TipoEmail": self.email_tipo,
            "ContactPage": self.contact_page,
            "AboutPage": self.about_page,
            "Score": self.score,
            "Classification": self.classification,
            "BuyerLikelihood": self.buyer_likelihood,
            "ExportPotential": self.export_potential,
            "RecommendedLanguage": self.recommended_language,
            "KeywordsFound": ", ".join(self.keywords_found),
        }
