"""Ambiente dos testes da API: SQLite temporário, nunca um banco real.

Roda a partir de apps/api:
    .venv/bin/python -m pytest tests_api -q

Cenário montado uma vez por sessão:
  - dono da plataforma (superadmin)
  - empresa A (admin + vendedor) e empresa B (admin), criadas pela API
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="prospect-api-test-"))
(_TMP / "data").mkdir()
os.environ.pop("DATABASE_URL", None)            # garantia: nada de Neon nos testes
os.environ["PROSPECT_SQLITE_PATH"] = str(_TMP / "data" / "prospect.db")
os.environ["APP_ENV"] = "development"
os.environ["APP_PASSWORD"] = "senha-do-time-teste"
os.environ["JWT_SECRET"] = "x" * 48
os.environ.pop("EMAIL_ENC_KEY", None)

API_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(API_DIR))
os.chdir(_TMP)

from fastapi.testclient import TestClient       # noqa: E402

import app.users as _users                       # noqa: E402
from api import ratelimit                        # noqa: E402
from api.main import create_app                  # noqa: E402

# Os testes não dependem de rede: a checagem de MX do e-mail de cadastro tem
# teste próprio (tests/test_email_cadastro.py).
_users._valida_email = lambda email: ("@" in email, "formato")

H = {"X-Requested-With": "prospectai"}
DONO = {"email": "dono@plataforma.example.com", "password": "dono-123456", "name": "Dono"}
SENHA = "senha-123456"


@pytest.fixture(scope="session")
def app():
    return create_app()


@pytest.fixture(autouse=True)
def _sem_limite_de_ip():
    ratelimit.reset_all()
    yield


def client(app) -> TestClient:
    return TestClient(app, headers=H)


def login(app, email: str, password: str = SENHA) -> TestClient:
    c = client(app)
    r = c.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture(scope="session")
def dono(app):
    c = client(app)
    c.__enter__()                                # roda o lifespan (migrations)
    r = c.post("/auth/bootstrap", json={"app_password": "senha-do-time-teste", **DONO})
    assert r.status_code == 200, r.text
    return c


def _criar_empresa(dono, nome: str, admin_email: str, plano: str = "empresarial") -> str:
    r = dono.post("/plataforma/empresas", json={
        "name": nome, "plano": plano, "admin_name": "Admin " + nome,
        "admin_email": admin_email, "admin_password": SENHA})
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture(scope="session")
def empresas(app, dono):
    """{'A': org_id, 'B': org_id} + usuários: adminA, vendA, vend2A, adminB."""
    a = _criar_empresa(dono, "Empresa A", "admin@a.example.com")
    b = _criar_empresa(dono, "Empresa B", "admin@b.example.com")
    adm_a = login(app, "admin@a.example.com")
    for email in ("vend@a.example.com", "vend2@a.example.com"):
        r = adm_a.post("/admin/users", json={"email": email, "name": email.split("@")[0],
                                             "role": "vendedor", "password": SENHA})
        assert r.status_code == 201, r.text
    return {"A": a, "B": b}


def user_id(email: str) -> str:
    return sql("SELECT id FROM users WHERE email = ?", (email,))[0][0]


def inserir_lead(org_id: str, owner_id: str, lote: str, website: str, **extra) -> None:
    """Grava um lead direto no SQLite de teste (o motor real busca na web)."""
    payload = {"Company": extra.get("Company", website), "Website": f"https://{website}",
               "Soluções": "Fornos e cocção", "Email": extra.get("Email", f"contato@{website}"),
               "Classification": extra.get("Classification", "HOT"), "Score": 80,
               "Porte": "12 unidades", "LinkedIn": "https://linkedin.com/company/x",
               "Cargo": "Gerente de operações", "City": "São Paulo",
               "Phone": "+55 11 9999-0000", "TipoEmail": "Caixa geral", "Situação": "Ativa",
               "Desde": "1999"}
    payload.update(extra)
    sql("INSERT INTO leads (org_id, website, company, first_seen, last_seen, score, lote, "
        "payload, gen_seconds, device, region, owner_id, generated_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (org_id, website, payload["Company"], lote[:10] + " 10:00:00", lote[:10] + " 10:00:00",
         80, lote, json.dumps(payload, ensure_ascii=False), 30.0, "Mac", "Brasil inteiro",
         owner_id, owner_id))


def sql(query: str, params: tuple = ()):
    con = sqlite3.connect(os.environ["PROSPECT_SQLITE_PATH"])
    try:
        rows = con.execute(query, params).fetchall()
        con.commit()
        return rows
    finally:
        con.close()
