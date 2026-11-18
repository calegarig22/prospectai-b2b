"""Sessão, CSRF, bloqueio por tentativas e anti-enumeração."""

from __future__ import annotations

from fastapi.testclient import TestClient

from conftest import DONO, H, SENHA, client, login, sql, user_id


def test_bootstrap_so_uma_vez(app, dono):
    assert client(app).get("/auth/status").json() == {"needs_bootstrap": False,
                                                      "bootstrap_enabled": True}
    r = client(app).post("/auth/bootstrap", json={"app_password": "senha-do-time-teste",
                                                  "name": "X", "email": "x@x.example.com",
                                                  "password": "123456"})
    assert r.status_code == 409
    me = dono.get("/auth/me").json()
    assert me["user"]["role"] == "superadmin" and me["org"]["id"] == "plataforma"
    assert me["plan"] is None


def test_bootstrap_com_senha_errada(app, dono):
    r = client(app).post("/auth/bootstrap", json={"app_password": "errada", "name": "X",
                                                  "email": "y@x.example.com", "password": "123456"})
    assert r.status_code == 403


def test_csrf_sem_cabecalho_e_recusado(app, dono):
    r = TestClient(app).post("/auth/login", json={"email": DONO["email"],
                                                  "password": DONO["password"]})
    assert r.status_code == 403


def test_cookie_httponly_e_samesite(app, dono):
    r = client(app).post("/auth/login", json={"email": DONO["email"], "password": DONO["password"]})
    cookie = r.headers["set-cookie"].lower()
    assert r.status_code == 200 and "httponly" in cookie and "samesite=lax" in cookie


def test_sem_sessao_e_cookie_forjado(app, dono):
    assert client(app).get("/auth/me").status_code == 401
    forjado = TestClient(app, headers=H, cookies={"tp_session": "eyJhbGciOiJub25lIn0.e30."})
    assert forjado.get("/auth/me").status_code == 401


def test_me_traz_plano_e_marca_da_empresa(app, empresas):
    me = login(app, "vend@a.example.com").get("/auth/me").json()
    assert me["org"]["id"] == empresas["A"] and me["org"]["marca"]["nome"] == "Empresa A"
    assert me["plan"]["efetivo"] == "empresarial"


def test_login_mensagem_unica_e_bloqueio(app, empresas):
    inex = client(app).post("/auth/login", json={"email": "ninguem@a.example.com", "password": "x"})
    exis = client(app).post("/auth/login", json={"email": "vend2@a.example.com", "password": "x"})
    assert inex.status_code == exis.status_code == 401 and inex.json() == exis.json()
    for _ in range(4):
        r = client(app).post("/auth/login", json={"email": "vend2@a.example.com", "password": "x"})
    assert r.status_code == 429
    r = client(app).post("/auth/login", json={"email": "vend2@a.example.com", "password": SENHA})
    assert r.status_code == 429
    sql("DELETE FROM login_attempts")


def test_trocar_senha_derruba_outras_sessoes(app, empresas):
    a = login(app, "admin@a.example.com")
    a.post("/admin/users", json={"email": "troca@a.example.com", "name": "t",
                                 "role": "vendedor", "password": SENHA})
    s1, s2 = login(app, "troca@a.example.com"), login(app, "troca@a.example.com")
    assert s1.post("/auth/password", json={"current": SENHA, "new": "nova-654321"}).status_code == 200
    assert s1.get("/auth/me").status_code == 200
    assert s2.get("/auth/me").status_code == 401


def test_desativar_derruba_sessao_na_hora(app, empresas):
    a = login(app, "admin@a.example.com")
    a.post("/admin/users", json={"email": "sai@a.example.com", "name": "s",
                                 "role": "vendedor", "password": SENHA})
    v = login(app, "sai@a.example.com")
    assert a.patch(f"/admin/users/{user_id('sai@a.example.com')}",
                   json={"active": False}).status_code == 200
    assert v.get("/auth/me").status_code == 401


def test_reset_responde_igual_exista_ou_nao(app, empresas):
    x = client(app).post("/auth/reset/start", json={"email": "admin@a.example.com"})
    y = client(app).post("/auth/reset/start", json={"email": "fantasma@a.example.com"})
    assert x.status_code == y.status_code == 200 and x.json() == y.json()


def test_reset_com_codigo(app, empresas):
    from app import db, users
    a = login(app, "admin@a.example.com")
    a.post("/admin/users", json={"email": "esq@a.example.com", "name": "e",
                                 "role": "vendedor", "password": SENHA})
    with db.conn() as c:
        code, _ = users.start_reset(c, "esq@a.example.com")
    errado = "000000" if code != "000000" else "111111"
    c2 = client(app)
    assert c2.post("/auth/reset/verify", json={"email": "esq@a.example.com",
                                               "code": errado}).status_code == 400
    assert c2.post("/auth/reset/confirm", json={"email": "esq@a.example.com", "code": code,
                                                "password": "outra-123456"}).status_code == 200
    login(app, "esq@a.example.com", "outra-123456")
