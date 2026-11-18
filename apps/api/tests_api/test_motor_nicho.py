"""O motor obedece ao nicho: soluções, decisor, porte e pontuação mudam com ele."""

from __future__ import annotations

import pytest

from app import nicho

NICHO_TESTE = """
nome: Nicho de teste — clínicas
busca:
  palavras_chave: [clínica odontológica, rede de clínicas]
pontuacao:
  hot: 30
  warm: 10
  necessidades: {consultórios: 20, cadeira odontológica: 15}
  segmentos: {clínica: 10}
  concorrentes: {fabricante de cadeiras: -40}
solucoes:
  - {nome: Cadeiras, curto: Cad, sinais: [cadeira odontológica, consultório*], decisor: Diretor clínico}
  - {nome: Software, curto: Soft, sinais: [agendamento online], oculta_se: [Cadeiras]}
decisores:
  padrao: Sócio
  cargos: [{termo: diretor clínico, rotulo: Diretor clínico, prioridade: 92}]
porte:
  ativo: true
  rotulo: consultórios
  unidades: [consultórios, unidades]
  contexto: [rede de]
  media_a_partir_de: 3
  grande_a_partir_de: 10
"""


@pytest.fixture
def nicho_teste(monkeypatch, tmp_path):
    n = nicho.de_yaml(NICHO_TESTE)
    arq = tmp_path / "n.json"
    import json
    arq.write_text(json.dumps(n.para_dict()), encoding="utf-8")
    monkeypatch.setenv(nicho.ENV_FILE, str(arq))
    nicho.ativo.cache_clear()
    yield n
    nicho.ativo.cache_clear()


def test_exemplo_e_valido_e_volta_igual():
    n = nicho.exemplo()
    assert nicho.de_yaml(nicho.para_yaml(n)) == n
    assert n.solucoes and n.palavras_chave


def test_erros_de_nicho_viram_mensagem_clara():
    with pytest.raises(nicho.NichoInvalido, match="palavra-chave"):
        nicho.de_yaml("nome: x\nbusca: {palavras_chave: []}")
    with pytest.raises(nicho.NichoInvalido, match="warm"):
        nicho.de_yaml("nome: x\nbusca: {palavras_chave: [a]}\npontuacao: {hot: 20, warm: 40}")
    with pytest.raises(nicho.NichoInvalido, match="não existe"):
        nicho.de_yaml("nome: x\nbusca: {palavras_chave: [a]}\n"
                      "solucoes: [{nome: A, sinais: [a], oculta_se: [Fantasma]}]")
    with pytest.raises(nicho.NichoInvalido, match="entre -100 e 100"):
        nicho.de_yaml("nome: x\nbusca: {palavras_chave: [a]}\npontuacao: {necessidades: {a: 500}}")


def test_solucoes_e_oculta_se(nicho_teste):
    from app.solutions import detect_solutions
    texto = "Temos 4 consultórios com cadeira odontológica e agendamento online."
    assert detect_solutions(texto) == ["Cadeiras"]           # Software some por oculta_se
    assert detect_solutions("Faça seu agendamento online") == ["Software"]
    assert detect_solutions("Nada a ver") == []


def test_decisor_do_nicho(nicho_teste):
    from app.decisor import find_decisor, target_role
    assert target_role(["Cadeiras"]) == "Diretor clínico"
    assert target_role([]) == "Sócio"
    d = find_decisor("", "Nossa equipe: Diretor clínico: Carlos Menezes cuida de tudo.", [])
    assert d.role == "Diretor clínico" and d.name == "Carlos Menezes" and d.is_real


def test_porte_do_nicho(nicho_teste):
    from app import porte
    assert porte.detectar_numero("Somos uma rede de 12 clínicas") == 12
    assert porte.detectar_numero("Atendemos em 7 consultórios") == 7
    assert porte.detectar_numero("Fundada em 12 de agosto de 2019, com 2019 unidades") == 0
    assert porte.classificar(12) == "Grande" and porte.classificar(4) == "Média"
    assert porte.rotulo(7, "Média") == "7 consultórios"


def test_pontuacao_usa_os_pesos_do_nicho(nicho_teste):
    from app.scorer import score_text
    r = score_text("Clínica com 3 consultórios", nicho_teste.scoring())
    assert r.score == 30 and r.classification == "HOT"
    concorrente = score_text("Clínica, fabricante de cadeiras, consultórios", nicho_teste.scoring())
    assert concorrente.classification == "COLD"
    so_setor = score_text("Uma clínica qualquer", nicho_teste.scoring())
    assert so_setor.classification == "COLD"            # sem sinal de necessidade


def test_buscas_saem_do_nicho(nicho_teste):
    import importlib
    import discover
    importlib.reload(discover)
    qs = discover._rotating_queries(6)
    assert qs and all(("clínica" in q or "clinicas" in q or "clínicas" in q) for q in qs)
