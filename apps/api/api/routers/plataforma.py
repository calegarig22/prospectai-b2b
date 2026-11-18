"""Área do DONO DA PLATAFORMA (superadmin): criar e configurar empresas clientes.

O que ele faz: cria empresa (com o primeiro admin dela), define plano e teste,
suspende/reativa, edita o NICHO (o que a empresa busca e oferece) e a MARCA.
O que ele NÃO faz: ler leads, e-mails ou remetentes de empresa nenhuma — não há
rota para isso. Configurar o produto não exige ver os dados do cliente.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app import audit, db, nicho as _nicho, orgs, users

from ..schemas import Marca, Msg, NichoIn, NichoOut, TenantCreateIn, TenantOut, TenantPatchIn
from ..security import Ctx, require_superadmin

router = APIRouter(prefix="/plataforma", tags=["plataforma"])


def _audit(c, ctx: Ctx, action: str, detail: str = "") -> None:
    audit.registrar(c, orgs.PLATAFORMA_ID, ctx.as_user(), action, detail)


def _empresa(c, org_id: str) -> dict:
    org = orgs.get(c, org_id) if org_id != orgs.PLATAFORMA_ID else None
    if not org:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Empresa não encontrada.")
    return org


def _nome_nicho(org: dict) -> str:
    try:
        import json
        return (json.loads(org["nicho"]) or {}).get("nome", "") if org["nicho"] else ""
    except ValueError:
        return ""


@router.get("/empresas", response_model=list[TenantOut])
def empresas(ctx: Ctx = Depends(require_superadmin)):
    with db.conn() as c:
        lista = orgs.listar(c)
        return [{"id": o["id"], "name": o["name"], "active": o["active"], "plano": o["plano"],
                 "trial_ate": o["trial_ate"], "created_at": o["created_at"],
                 "usuarios": users.usuarios_da_org(c, o["id"]), "nicho_nome": _nome_nicho(o)}
                for o in lista]


@router.post("/empresas", response_model=TenantOut, status_code=201)
def criar_empresa(body: TenantCreateIn, ctx: Ctx = Depends(require_superadmin)):
    """Empresa nova já nasce com o primeiro admin e o nicho de EXEMPLO (a ajustar)."""
    # TUDO OU NADA: valida o admin ANTES de criar a empresa e, se a criação dele
    # falhar mesmo assim, desfaz a empresa. Antes, um e-mail recusado deixava uma
    # empresa órfã, sem ninguém capaz de entrar nela.
    ok, motivo = users._valida_email(body.admin_email.strip().lower())
    if not ok:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"E-mail do admin inválido: {motivo}.")
    with db.conn() as c:
        if users.get_by_email(c, body.admin_email):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Já existe um usuário com esse e-mail.")
        try:
            org = orgs.criar(c, body.name, body.plano, body.trial_ate)
        except ValueError as erro:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))
        try:
            users.create_user(c, org["id"], body.admin_email, body.admin_password,
                              name=body.admin_name, role="admin")
        except Exception as erro:
            orgs.excluir_vazia(c, org["id"])
            if isinstance(erro, ValueError):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))
            raise
        _audit(c, ctx, "Criou empresa", f"{org['name']} ({org['id']}) · admin {body.admin_email}")
        return {"id": org["id"], "name": org["name"], "active": True, "plano": org["plano"],
                "trial_ate": org["trial_ate"], "created_at": org["created_at"], "usuarios": 1,
                "nicho_nome": _nome_nicho(org)}


@router.patch("/empresas/{org_id}", response_model=Msg)
def editar_empresa(org_id: str, body: TenantPatchIn, ctx: Ctx = Depends(require_superadmin)):
    with db.conn() as c:
        org = _empresa(c, org_id)
        mudou = []
        try:
            if body.name is not None and body.name != org["name"]:
                orgs.renomear(c, org_id, body.name); mudou.append("nome")
            if body.plano is not None or body.trial_ate is not None:
                orgs.definir_plano(c, org_id, body.plano or org["plano"],
                                   org["trial_ate"] if body.trial_ate is None else body.trial_ate)
                mudou.append("plano")
            if body.active is not None and body.active != org["active"]:
                orgs.definir_ativa(c, org_id, body.active)
                mudou.append("reativada" if body.active else "suspensa")
        except ValueError as erro:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))
        if mudou:
            _audit(c, ctx, "Editou empresa", f"{org['name']}: {', '.join(mudou)}")
    return {"detail": "Alterações salvas." if mudou else "Nenhuma alteração."}


@router.get("/empresas/{org_id}/nicho", response_model=NichoOut)
def ver_nicho(org_id: str, ctx: Ctx = Depends(require_superadmin)):
    with db.conn() as c:
        _empresa(c, org_id)
        n = orgs.nicho_de(c, org_id)
        texto = orgs.texto_do_nicho(c, org_id)
    return {"yaml": texto, "nome": n.nome, "solucoes": len(n.solucoes),
            "palavras_chave": len(n.palavras_chave)}


@router.post("/nicho/validar", response_model=NichoOut)
def validar_nicho(body: NichoIn, ctx: Ctx = Depends(require_superadmin)):
    """Confere o texto sem salvar — a tela usa antes de gravar."""
    try:
        n = _nicho.de_yaml(body.yaml)
    except _nicho.NichoInvalido as erro:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))
    return {"yaml": body.yaml, "nome": n.nome, "solucoes": len(n.solucoes),
            "palavras_chave": len(n.palavras_chave)}


@router.put("/empresas/{org_id}/nicho", response_model=Msg)
def salvar_nicho(org_id: str, body: NichoIn, ctx: Ctx = Depends(require_superadmin)):
    try:
        n = _nicho.de_yaml(body.yaml)
    except _nicho.NichoInvalido as erro:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))
    with db.conn() as c:
        org = _empresa(c, org_id)
        orgs.salvar_nicho(c, org_id, n, body.yaml)
        _audit(c, ctx, "Alterou nicho", f"{org['name']}: {n.nome}")
    return {"detail": "Nicho salvo. Vale a partir do próximo lote."}


@router.get("/empresas/{org_id}/marca", response_model=Marca)
def ver_marca(org_id: str, ctx: Ctx = Depends(require_superadmin)):
    with db.conn() as c:
        return _empresa(c, org_id)["marca"]


@router.put("/empresas/{org_id}/marca", response_model=Msg)
def salvar_marca(org_id: str, body: Marca, ctx: Ctx = Depends(require_superadmin)):
    try:
        marca = orgs.valida_marca(body.nome, body.cor, body.logo)
    except ValueError as erro:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(erro))
    with db.conn() as c:
        org = _empresa(c, org_id)
        orgs.salvar_marca(c, org_id, marca)
        _audit(c, ctx, "Alterou marca", org["name"])
    return {"detail": "Marca salva."}


@router.get("/nicho/exemplo", response_model=NichoOut)
def nicho_exemplo(ctx: Ctx = Depends(require_superadmin)):
    n = _nicho.exemplo()
    return {"yaml": _nicho.EXEMPLO_PATH.read_text(encoding="utf-8"), "nome": n.nome,
            "solucoes": len(n.solucoes), "palavras_chave": len(n.palavras_chave)}
