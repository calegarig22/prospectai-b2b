"""Empresas clientes (tenants).

Cada empresa tem plano, período de teste, NICHO (o que buscar e oferecer) e
MARCA (como a tela aparece para ela). A empresa ``plataforma`` é a do dono do
sistema: o superadmin vive nela e administra as outras.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime

from . import nicho as _nicho
from .db import Conn

PLATAFORMA_ID = "plataforma"
_COR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_LOGO_RE = re.compile(r"^data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$")
_LOGO_MAX = 200_000          # data URI: cabe no JSON da marca sem pesar no login
_COLS = "id, name, active, created_at, plano, trial_ate, nicho, marca, nicho_yaml"


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _row(r) -> dict:
    return {"id": r[0], "name": r[1], "active": bool(r[2]), "created_at": r[3] or "",
            "plano": r[4] or "essencial", "trial_ate": r[5] or "",
            "nicho": r[6] or "", "marca": _marca(r[7]), "nicho_yaml": r[8] or ""}


def _marca(raw) -> dict:
    try:
        m = json.loads(raw) if raw else {}
    except ValueError:
        m = {}
    return {"nome": m.get("nome", ""), "cor": m.get("cor", ""), "logo": m.get("logo", "")}


def valida_marca(nome: str, cor: str, logo: str) -> dict:
    nome = (nome or "").strip()
    if len(nome) > 60:
        raise ValueError("O nome de exibição pode ter até 60 caracteres.")
    cor = (cor or "").strip()
    if cor and not _COR_RE.match(cor):
        raise ValueError("A cor precisa estar no formato #RRGGBB.")
    logo = (logo or "").strip()
    if logo and (len(logo) > _LOGO_MAX or not _LOGO_RE.match(logo)):
        # SVG fica de fora de propósito: ele pode carregar script.
        raise ValueError("O logo precisa ser PNG, JPEG ou WEBP de até ~150 KB.")
    return {"nome": nome, "cor": cor, "logo": logo}


def get(c: Conn, org_id: str) -> dict | None:
    r = c.one(f"SELECT {_COLS} FROM orgs WHERE id = {c.ph}", (org_id,))
    return _row(r) if r else None


def listar(c: Conn) -> list[dict]:
    """Todas as empresas clientes (sem a da plataforma). Só o superadmin chama."""
    rows = c.all(f"SELECT {_COLS} FROM orgs WHERE id <> {c.ph} ORDER BY name", (PLATAFORMA_ID,))
    return [_row(r) for r in rows]


def garantir_plataforma(c: Conn) -> None:
    c.run(f"INSERT INTO orgs (id, name, active, created_at, plano) "
          f"VALUES ({c.ph}, {c.ph}, 1, {c.ph}, {c.ph}) ON CONFLICT (id) DO NOTHING",
          (PLATAFORMA_ID, "Plataforma", _agora(), "empresarial"))


def criar(c: Conn, nome: str, plano: str, trial_ate: str = "") -> dict:
    nome = (nome or "").strip()
    if not nome or len(nome) > 120:
        raise ValueError("Informe o nome da empresa (até 120 caracteres).")
    oid = f"org-{uuid.uuid4().hex[:12]}"
    texto = _nicho.EXEMPLO_PATH.read_text(encoding="utf-8")
    nicho_json = json.dumps(_nicho.de_yaml(texto).para_dict(), ensure_ascii=False)
    marca_json = json.dumps({"nome": nome, "cor": "", "logo": ""}, ensure_ascii=False)
    c.run(f"INSERT INTO orgs (id, name, active, created_at, plano, trial_ate, nicho, marca, "
          f"nicho_yaml) VALUES ({', '.join([c.ph] * 9)})",
          (oid, nome, 1, _agora(), plano, trial_ate or None, nicho_json, marca_json, texto))
    return get(c, oid)


def nicho_de(c: Conn, org_id: str) -> _nicho.Nicho:
    """Nicho da empresa já validado. Empresa sem nicho salvo usa o exemplo."""
    org = get(c, org_id)
    if not org:
        raise ValueError("Empresa não encontrada.")
    if not org["nicho"]:
        return _nicho.exemplo()
    return _nicho.de_dict(json.loads(org["nicho"]))


def salvar_nicho(c: Conn, org_id: str, n: _nicho.Nicho, texto: str = "") -> None:
    """Grava a versão validada (o motor usa) e o texto original (a tela mostra)."""
    c.run(f"UPDATE orgs SET nicho = {c.ph}, nicho_yaml = {c.ph} WHERE id = {c.ph}",
          (json.dumps(n.para_dict(), ensure_ascii=False), texto or _nicho.para_yaml(n), org_id))


def texto_do_nicho(c: Conn, org_id: str) -> str:
    """O texto como foi escrito; se faltar (empresa antiga), gera a partir do JSON."""
    org = get(c, org_id)
    if org and org["nicho_yaml"]:
        return org["nicho_yaml"]
    return _nicho.para_yaml(nicho_de(c, org_id))


def salvar_marca(c: Conn, org_id: str, marca: dict) -> None:
    c.run(f"UPDATE orgs SET marca = {c.ph} WHERE id = {c.ph}",
          (json.dumps(marca, ensure_ascii=False), org_id))


def definir_plano(c: Conn, org_id: str, plano: str, trial_ate: str) -> None:
    c.run(f"UPDATE orgs SET plano = {c.ph}, trial_ate = {c.ph} WHERE id = {c.ph}",
          (plano, trial_ate or None, org_id))


def excluir_vazia(c: Conn, org_id: str) -> None:
    """Desfaz uma empresa recém-criada que ficou sem nenhum usuário."""
    if org_id == PLATAFORMA_ID:
        return
    r = c.one(f"SELECT COUNT(*) FROM users WHERE org_id = {c.ph}", (org_id,))
    if r and int(r[0]) == 0:
        c.run(f"DELETE FROM orgs WHERE id = {c.ph}", (org_id,))


def definir_ativa(c: Conn, org_id: str, ativa: bool) -> None:
    if org_id == PLATAFORMA_ID:
        raise ValueError("A empresa da plataforma não pode ser desativada.")
    c.run(f"UPDATE orgs SET active = {c.ph} WHERE id = {c.ph}", (1 if ativa else 0, org_id))


def renomear(c: Conn, org_id: str, nome: str) -> None:
    nome = (nome or "").strip()
    if not nome or len(nome) > 120:
        raise ValueError("Informe o nome da empresa (até 120 caracteres).")
    c.run(f"UPDATE orgs SET name = {c.ph} WHERE id = {c.ph}", (nome, org_id))
