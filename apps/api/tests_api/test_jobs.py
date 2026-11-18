"""Fila de lotes: o processo do motor recebe SÓ a empresa e o nicho certos."""

from __future__ import annotations

import json
import sys
import textwrap
import time

from conftest import login


def _espera(cli, jid):
    for _ in range(200):
        job = cli.get(f"/jobs/{jid}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.05)
    raise AssertionError("job não terminou")


def test_lote_roda_com_a_empresa_e_o_nicho_certos(app, empresas, tmp_path, monkeypatch):
    from api import jobs
    relatorio = tmp_path / "env.json"
    falso = tmp_path / "discover_falso.py"
    falso.write_text(textwrap.dedent(f"""
        import json, os, sys
        nicho = json.load(open(os.environ["PROSPECT_NICHO_FILE"], encoding="utf-8"))
        json.dump({{"org": os.environ.get("ORG_ID"), "owner": os.environ.get("OWNER_ID"),
                   "nicho": nicho["nome"], "jwt": "JWT_SECRET" in os.environ,
                   "enc": "EMAIL_ENC_KEY" in os.environ, "qtd": sys.argv[1]}},
                  open({str(relatorio)!r}, "w"))
        print("2026-10-08 10:00:00 | INFO    | Buscando em /Users/servidor/segredo", flush=True)
        print("2026-10-08 10:00:01 | INFO    | LOTE_ID: 2026-10-08_100001", flush=True)
    """))
    monkeypatch.setattr(jobs, "DISCOVER_CMD", [sys.executable, str(falso)])
    v = login(app, "vend@a.example.com")
    r = v.post("/jobs/discover", json={"quantidade": 20, "so_com_contato": True})
    assert r.status_code == 202, r.text
    job = _espera(v, r.json()["id"])
    assert job["status"] == "done" and job["result"]["lote"] == "2026-10-08_100001"
    assert all("/Users/" not in linha for linha in job["result"]["log"])
    env = json.loads(relatorio.read_text())
    assert env["org"] == empresas["A"] and env["qtd"] == "20"
    assert env["nicho"].startswith("Exemplo")
    assert env["jwt"] is False and env["enc"] is False      # segredos não vão para o motor
    # Ninguém de outra empresa (nem colega) acompanha o job.
    assert login(app, "admin@b.example.com").get(f"/jobs/{job['id']}").status_code == 404
    assert login(app, "vend2@a.example.com").get(f"/jobs/{job['id']}").status_code == 404
    assert login(app, "admin@a.example.com").get(f"/jobs/{job['id']}").status_code == 200


def test_motor_que_falha_nao_fica_rodando(app, empresas, tmp_path, monkeypatch):
    from api import jobs
    falso = tmp_path / "quebra.py"
    falso.write_text("import sys; print('erro em /srv/segredo/x.py'); sys.exit(3)")
    monkeypatch.setattr(jobs, "DISCOVER_CMD", [sys.executable, str(falso)])
    v = login(app, "vend@a.example.com")
    job = _espera(v, v.post("/jobs/discover", json={"quantidade": 10}).json()["id"])
    assert job["status"] == "error" and "segredo" not in json.dumps(job)


def test_plano_limita_quantidade_e_regiao(app, dono, empresas):
    dono.patch(f"/plataforma/empresas/{empresas['A']}", json={"plano": "essencial"})
    try:
        v = login(app, "vend@a.example.com")
        assert v.post("/jobs/discover", json={"quantidade": 100}).status_code == 400
        assert v.post("/jobs/discover", json={"quantidade": 20, "regiao": "Sul"}).status_code == 403
    finally:
        dono.patch(f"/plataforma/empresas/{empresas['A']}", json={"plano": "empresarial"})


def test_email_sem_remetente_nao_dispara(app, empresas):
    v = login(app, "vend@a.example.com")
    sel = v.post("/email/selection", json={"lote": None, "classes": ["HOT"]}).json()
    assert sel["pode_enviar"] is False and "remetente" in sel["motivo"]
    r = v.post("/jobs/email", json={"lote": None, "classes": ["HOT"], "confirmar": True})
    assert r.status_code == 409


def test_template_por_usuario(app, empresas):
    v = login(app, "vend@a.example.com")
    assert v.get("/email/template").json()["origem"] == "padrao"
    html = "<html><body><p>Oi {company}</p></body></html>"
    assert v.put("/email/template", json={"html": html}).status_code == 200
    t = v.get("/email/template").json()
    assert t["origem"] == "upload" and "Empresa Exemplo" in t["preview_html"]
    # O colega continua com o padrão.
    assert login(app, "vend2@a.example.com").get("/email/template").json()["origem"] == "padrao"
    v.delete("/email/template")


def test_remetente_cifrado_e_senha_nunca_sai(app, empresas, monkeypatch):
    from cryptography.fernet import Fernet
    from conftest import sql, user_id
    a = login(app, "admin@a.example.com")
    uid = user_id("vend@a.example.com")
    body = {"from_email": "vend@a.example.com", "smtp_password": "abcd efgh ijkl mnop"}
    assert a.put(f"/admin/senders/{uid}", json=body).status_code == 503       # sem chave
    monkeypatch.setenv("EMAIL_ENC_KEY", Fernet.generate_key().decode())
    assert a.put(f"/admin/senders/{uid}", json=body).status_code == 200
    assert "abcd efgh" not in a.get("/admin/senders").text
    guardado = sql("SELECT smtp_password_enc FROM email_senders WHERE user_id = ?", (uid,))[0][0]
    assert "abcd" not in guardado
