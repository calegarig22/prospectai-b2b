"""Área do dono da plataforma: empresas, plano, nicho e marca."""

from __future__ import annotations

from conftest import login


def test_lista_e_cria_empresa_com_nicho_de_exemplo(app, dono, empresas):
    lista = {e["id"]: e for e in dono.get("/plataforma/empresas").json()}
    assert empresas["A"] in lista and "plataforma" not in lista
    assert lista[empresas["A"]]["nicho_nome"].startswith("Exemplo")
    assert lista[empresas["A"]]["usuarios"] >= 3


def test_email_repetido_nao_cria_empresa(app, dono, empresas):
    antes = len(dono.get("/plataforma/empresas").json())
    r = dono.post("/plataforma/empresas", json={"name": "Dup", "admin_email": "admin@a.example.com",
                                                "admin_password": "senha-123456"})
    assert r.status_code == 400
    assert len(dono.get("/plataforma/empresas").json()) == antes


def test_falha_no_admin_nao_deixa_empresa_orfa(app, dono, empresas, monkeypatch):
    import app.users as u
    antes = len(dono.get("/plataforma/empresas").json())
    monkeypatch.setattr(u, "_valida_email", lambda e: (False, "domínio sem e-mail"))
    r = dono.post("/plataforma/empresas", json={"name": "Órfã", "admin_email": "x@semmx.example.com",
                                                "admin_password": "senha-123456"})
    assert r.status_code == 400
    monkeypatch.undo()
    # Falha DEPOIS de criar a empresa (ex.: senha curta passou no schema mas não no repositório).
    def quebra(*a, **k):
        raise ValueError("falha simulada")
    monkeypatch.setattr(u, "create_user", quebra)
    r = dono.post("/plataforma/empresas", json={"name": "Órfã 2", "admin_email": "y@ok.example.com",
                                                "admin_password": "senha-123456"})
    assert r.status_code == 400
    assert len(dono.get("/plataforma/empresas").json()) == antes


def test_teto_de_usuarios_do_plano(app, dono, empresas):
    dono.patch(f"/plataforma/empresas/{empresas['B']}", json={"plano": "essencial"})
    try:
        b = login(app, "admin@b.example.com")
        criados, ultimo = 0, None
        while criados < 10:
            ultimo = b.post("/admin/users", json={"email": f"vaga{criados}@b.example.com",
                                                  "name": "v", "role": "vendedor",
                                                  "password": "senha-123456"})
            if ultimo.status_code != 201:
                break
            criados += 1
        assert ultimo.status_code == 400 and "plano" in ultimo.json()["detail"].lower()
        assert b.get("/admin/users").json()["total"] == 5
    finally:
        dono.patch(f"/plataforma/empresas/{empresas['B']}", json={"plano": "empresarial"})


def test_nicho_valida_salva_e_chega_na_empresa(app, dono, empresas):
    y = dono.get(f"/plataforma/empresas/{empresas['B']}/nicho").json()["yaml"]
    assert dono.post("/plataforma/nicho/validar", json={"yaml": "nome: x\n  ruim: [\n"}).status_code == 400
    sem_palavras = "nome: Teste\nbusca:\n  palavras_chave: []\n"
    r = dono.post("/plataforma/nicho/validar", json={"yaml": sem_palavras})
    assert r.status_code == 400 and "palavra-chave" in r.json()["detail"]
    novo = y.replace("Exemplo — equipamentos para cozinha profissional", "Nicho da B") \
            .replace("curto: Fornos", "curto: FornosB")
    assert dono.put(f"/plataforma/empresas/{empresas['B']}/nicho", json={"yaml": novo}).status_code == 200
    meta_b = login(app, "admin@b.example.com").get("/meta").json()
    assert meta_b["nicho_nome"] == "Nicho da B"
    assert "FornosB" in [s["curto"] for s in meta_b["solucoes"]]
    # O texto volta COMO FOI ESCRITO (os comentários que explicam cada campo ficam).
    salvo = dono.get(f"/plataforma/empresas/{empresas['B']}/nicho").json()["yaml"]
    assert "# Como o casamento de termos funciona" in salvo and "Nicho da B" in salvo
    meta_a = login(app, "admin@a.example.com").get("/meta").json()
    assert meta_a["nicho_nome"] != "Nicho da B"           # o nicho de B não vaza para A


def test_marca_valida(app, dono, empresas):
    url = f"/plataforma/empresas/{empresas['A']}/marca"
    assert dono.put(url, json={"nome": "A", "cor": "azul"}).status_code == 400
    svg = "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4="
    assert dono.put(url, json={"nome": "A", "cor": "#123456", "logo": svg}).status_code == 400
    assert dono.put(url, json={"nome": "Marca A", "cor": "#123456"}).status_code == 200
    assert login(app, "vend@a.example.com").get("/auth/me").json()["org"]["marca"]["cor"] == "#123456"


def test_plataforma_nao_pode_ser_editada_como_empresa(app, dono):
    assert dono.patch("/plataforma/empresas/plataforma", json={"active": False}).status_code == 404
