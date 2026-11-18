"""Casos de e-mail com a forma dos que quebraram a heurística em produção.

Roda sem pytest, para não trazer dependência nova ao projeto:

    python tests/test_contatos.py

Cada caso é ``(e-mail, domínio do site, rótulo esperado)``. Ao mexer nas listas
de ``app/contacts.py``, rode isto: o classificador é de heurística, e uma palavra
nova na lista errada troca silenciosamente a temperatura de um lote inteiro.

REGRA QUE NÃO PODE QUEBRAR: na dúvida o rótulo sai MAIS FRIO. Anunciar "Pessoa"
onde há uma caixa geral faz o vendedor escrever "Olá, Fulano" para o nada.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.contacts import (extract_email, extract_emails_ranked, promover_decisor,  # noqa: E402
                          rotulo_email, temperatura_email)

# (e-mail, domínio do site, rótulo esperado)
# Domínios FICTÍCIOS, mas com a mesma forma dos casos reais que quebraram a
# heurística (nenhum dado de cliente na base).
CASOS_REAIS = [
    # Caixa da própria empresa — o local é o nome da casa, não de gente.
    ("silva@transportessilva.exemplo.com", "transportessilva.exemplo.com", "Caixa geral"),
    ("zetatec@zetatecsolucoes.exemplo.com", "zetatecsolucoes.exemplo.com", "Caixa geral"),
    ("casaexemplo@casaexemplo.com.br", "casaexemplo.com.br", "Caixa geral"),
    ("vilaexemplo@vilaexemplo.exemplo.com", "vilaexemplo.exemplo.com", "Caixa geral"),
    ("docesexemplo@hotmail.com", "docesexemplo.exemplo.com", "Caixa geral"),
    # "falecom" carrega "fale": é porta de entrada, não pessoa.
    ("falecom@empresaexemplo.com.br", "empresaexemplo.com.br", "Caixa geral"),
    ("contato@grupoexemplo.com.br", "grupoexemplo.com.br", "Caixa geral"),
    ("contato@abc.com.br", "abc.com.br", "Caixa geral"),
    # Gente de verdade.
    ("renatolima@empresaexemplo.com.br", "empresaexemplo.com.br", "Pessoa"),
    ("leonardo@exemplologistica.com.br", "exemplologistica.com.br", "Pessoa"),
    ("fulanoexemplo.ti@hotmail.com", "exemplosul.com.br", "Pessoa"),
    # Funções.
    ("comercial@empresaexemplo.com.br", "empresaexemplo.com.br", "Comercial"),
    ("cotacao@exemplo10.com.br", "exemplo10.com.br", "Comercial"),
    ("diretoria@empresax.com.br", "empresax.com.br", "Diretoria"),
    ("compras@empresax.com.br", "empresax.com.br", "Compras"),
    ("operacional@empresax.com.br", "empresax.com.br", "Operação"),
    ("documentacao@empresax.com.br", "empresax.com.br", "Área técnica"),
    ("adm@empresax.com.br", "empresax.com.br", "Área técnica"),
    ("marketing@empresax.com.br", "empresax.com.br", "Área técnica"),
    # Atendimento ao consumidor: o pior lugar para um e-mail de fornecedor.
    # "pos-venda" cuida de quem JÁ comprou — e o singular "venda" não pode
    # escapar da lista de vendas e virar nome de gente.
    ("pos-venda@empresax.com.br", "empresax.com.br", "Atendimento"),
    ("sac@empresax.com.br", "empresax.com.br", "Atendimento"),
    ("suporte@empresax.com.br", "empresax.com.br", "Atendimento"),
    ("atendimento@empresax.com.br", "empresax.com.br", "Atendimento"),
    ("reservas@empresax.com.br", "empresax.com.br", "Atendimento"),
    # Ilegível: o rótulo admite que não sabe, em vez de inventar uma área.
    ("qzx0000@gmail.com", "empresax.com.br", "Não identificado"),
    # Redação de jornal: descartado (rótulo vazio). Além de não comprar, o
    # endereço denuncia que o "lead" é um portal de notícia.
    ("redacao@portalexemplo.com.br", "portalexemplo.com.br", ""),
    # Palavra de operação vinda do NICHO de exemplo (email.palavras_operacao).
    ("cozinha@empresax.com.br", "empresax.com.br", "Operação"),
]

# (e-mail, nome do decisor, domínio, rótulo esperado)
CASOS_DECISOR = [
    ("renatolima@empresaexemplo.com.br", "Renato Lima", "empresaexemplo.com.br", "Decisor (nominal)"),
    ("joao.silva@x.com.br", "João Silva", "x.com.br", "Decisor (nominal)"),
    ("jose@x.com.br", "José Antônio Ribeiro", "x.com.br", "Decisor (nominal)"),
    ("anacleto@x.com.br", "Ana Souza", "x.com.br", "Pessoa"),      # 1 pedaço não basta
    ("mariana@x.com.br", "Carlos Prado", "x.com.br", "Pessoa"),    # outra pessoa
    ("contato@x.com.br", "Renato Lima", "x.com.br", "Caixa geral"),
]

HTML_MULTIPLO = (
    '<a href="mailto:sac@empresax.com.br">s</a>'
    '<a href="mailto:contato@empresax.com.br">c</a>'
    '<a href="mailto:comercial@empresax.com.br">x</a>'
    '<a href="mailto:leonardo@empresax.com.br">l</a>'
    '<a href="mailto:noreply@empresax.com.br">n</a>'
)


def main() -> int:
    falhas = []

    for email, dominio, esperado in CASOS_REAIS:
        veio = rotulo_email(temperatura_email(email, "", dominio))
        if veio != esperado:
            falhas.append(f"{email}: esperado {esperado!r}, veio {veio!r}")

    for email, decisor, dominio, esperado in CASOS_DECISOR:
        veio = rotulo_email(temperatura_email(email, decisor, dominio))
        if veio != esperado:
            falhas.append(f"{email} (decisor {decisor}): esperado {esperado!r}, veio {veio!r}")

    # Entre vários e-mails do mesmo site, o mais quente ganha e o noreply some.
    melhor = extract_email(HTML_MULTIPLO, "empresax.com.br")
    if melhor != "leonardo@empresax.com.br":
        falhas.append(f"escolha entre vários: veio {melhor!r}")
    if any(e.startswith("noreply") for e, _ in extract_emails_ranked(HTML_MULTIPLO, "empresax.com.br")):
        falhas.append("noreply@ não pode entrar na lista")

    # O decisor promove o endereço dele ao topo.
    html = '<a href="mailto:contato@x.com.br">c</a><a href="mailto:mariana@x.com.br">m</a>'
    base = extract_emails_ranked(html, "x.com.br")
    if promover_decisor(base, "Mariana Prado")[0][0] != "mariana@x.com.br":
        falhas.append("promoção pelo decisor não funcionou")

    # E-mail corporativo de OUTRA empresa nunca é emprestado ao lead.
    alheio = extract_email('<a href="mailto:contato@parceiro.com.br">p</a>', "minhaempresa.com.br")
    if alheio:
        falhas.append(f"e-mail de outra empresa vazou: {alheio!r}")

    total = len(CASOS_REAIS) + len(CASOS_DECISOR) + 4
    if falhas:
        print(f"FALHOU — {len(falhas)} de {total} verificações:")
        for f in falhas:
            print("  -", f)
        return 1
    print(f"OK — {total} verificações de contato passaram.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
