"""Contratos de entrada e saída da API.

Estes modelos viram o ``/openapi.json``, do qual o front gera os tipos
TypeScript (``apps/web/src/lib/api-types.ts``). Mudou aqui, regenere lá.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Role = Literal["admin", "vendedor"]
AnyRole = Literal["superadmin", "admin", "vendedor"]
Plano = Literal["essencial", "profissional", "empresarial"]
Classe = Literal["HOT", "WARM", "COLD"]


class Msg(BaseModel):
    detail: str


# --------------------------------------------------------------------- auth
class AuthStatus(BaseModel):
    needs_bootstrap: bool
    bootstrap_enabled: bool


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class BootstrapIn(BaseModel):
    app_password: str = Field(max_length=200)
    name: str = Field(max_length=120)
    email: str = Field(max_length=254)
    password: str = Field(min_length=6, max_length=200)


class ResetStartIn(BaseModel):
    email: str = Field(max_length=254)


class ResetVerifyIn(BaseModel):
    email: str = Field(max_length=254)
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class ResetConfirmIn(ResetVerifyIn):
    password: str = Field(min_length=6, max_length=200)


class ChangePasswordIn(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(min_length=6, max_length=200)


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    role: AnyRole


class Marca(BaseModel):
    nome: str = Field(default="", max_length=60)
    cor: str = Field(default="", max_length=7)
    logo: str = Field(default="", max_length=210_000)


class OrgOut(BaseModel):
    id: str
    name: str
    marca: Marca


class PlanOut(BaseModel):
    contratado: str
    efetivo: str
    nome: str
    em_teste: bool
    trial_ate: str
    limites: dict[str, int]
    recursos: dict[str, bool]
    uso_leads_mes: int
    renova_em: str
    ilimitado: int


class MeOut(BaseModel):
    user: UserOut
    org: OrgOut
    plan: PlanOut | None        # None para o dono da plataforma


# --------------------------------------------------------------------- meta
class PlanInfo(BaseModel):
    nome: str
    preco: str
    limites: dict[str, int]
    recursos: dict[str, bool]


class PlanMatrix(BaseModel):
    ordem: list[str]
    planos: dict[str, PlanInfo]
    ilimitado: int


class SolucaoInfo(BaseModel):
    nome: str
    curto: str


class MetaOut(BaseModel):
    regions: list[str]
    world: str
    plans: PlanMatrix
    nicho_nome: str
    solucoes: list[SolucaoInfo]
    porte_rotulo: str


# -------------------------------------------------------------------- lotes
class LoteOut(BaseModel):
    id: str
    count: int
    created_at: str
    gen_seconds: float
    device: str
    region: str


class LotesOut(BaseModel):
    lotes: list[LoteOut]
    ocultos_por_plano: int
    historico_dias: int


class Bloqueio(BaseModel):
    recurso: str
    nome: str
    selo: str


class LoteDetail(BaseModel):
    lote: LoteOut
    columns: list[str]
    rows: list[dict[str, Any]]
    bloqueios: list[Bloqueio]


# --------------------------------------------------------------------- jobs
class DiscoverIn(BaseModel):
    quantidade: int = Field(ge=10, le=500)
    regiao: str | None = Field(default=None, max_length=60)
    so_com_contato: bool = True


class EmailJobIn(BaseModel):
    lote: str | None = Field(default=None, max_length=40)
    classes: list[Classe] = Field(default_factory=lambda: ["HOT"])
    confirmar: bool


class JobOut(BaseModel):
    id: str
    kind: Literal["discover", "email"]
    status: Literal["queued", "running", "done", "error"]
    progress: str
    params: dict[str, Any]
    result: dict[str, Any] | None
    error: str
    created_at: str
    started_at: str
    finished_at: str


# -------------------------------------------------------------------- email
class SelectionIn(BaseModel):
    lote: str | None = Field(default=None, max_length=40)
    classes: list[Classe] = Field(default_factory=lambda: ["HOT"])


class SenderInfo(BaseModel):
    from_name: str
    from_email: str
    origem: Literal["sua caixa", "conta corporativa"]


class SelectionOut(BaseModel):
    selecionadas: int
    pendentes: int
    cota_restante: int
    teto_hoje: int
    warmup: bool
    envia_agora: int
    delay_min: int
    delay_max: int
    eta_min: int
    remetente: SenderInfo | None
    pode_enviar: bool
    motivo: str


class TemplateOut(BaseModel):
    origem: Literal["upload", "padrao", "nenhum"]
    preview_html: str
    campos: list[str]


class TemplateIn(BaseModel):
    html: str = Field(min_length=20, max_length=500_000)


# -------------------------------------------------------------------- admin
class PlanAdminOut(BaseModel):
    matriz: PlanMatrix
    contratado: str
    efetivo: str
    trial_ate: str
    em_teste: bool


class PlanUpdateIn(BaseModel):
    plano: Plano
    trial_ate: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")


class AdminUser(BaseModel):
    id: str
    email: str
    name: str
    role: Role
    active: bool
    created_at: str
    has_sender: bool


class UsersOut(BaseModel):
    users: list[AdminUser]
    limite: int
    ilimitado: bool
    total: int
    ativos: int
    admins: int


class UserCreateIn(BaseModel):
    email: str = Field(max_length=254)
    name: str = Field(default="", max_length=120)
    role: Role = "vendedor"
    password: str = Field(min_length=6, max_length=200)


class UserPatchIn(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    role: Role | None = None
    password: str | None = Field(default=None, min_length=6, max_length=200)
    active: bool | None = None


class AdminLote(BaseModel):
    id: str
    count: int
    created_at: str
    device: str
    generated_by_name: str
    owner_id: str
    owner_name: str


class AssignIn(BaseModel):
    user_id: str = Field(max_length=64)


class SenderOut(BaseModel):
    user_id: str
    user_name: str
    user_email: str
    configured: bool
    from_email: str
    from_name: str
    smtp_host: str
    smtp_port: int
    has_password: bool


class SendersOut(BaseModel):
    encryption_available: bool
    senders: list[SenderOut]


class SenderIn(BaseModel):
    from_email: str = Field(max_length=254)
    from_name: str = Field(default="", max_length=120)
    smtp_host: str = Field(default="smtp.gmail.com", max_length=120)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_password: str | None = Field(default=None, max_length=200)


class AuditEntry(BaseModel):
    ts: str
    user: str
    action: str
    detail: str


# --------------------------------------------------------------- plataforma
class TenantOut(BaseModel):
    id: str
    name: str
    active: bool
    plano: str
    trial_ate: str
    created_at: str
    usuarios: int
    nicho_nome: str


class TenantCreateIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    plano: Plano = "essencial"
    trial_ate: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    admin_name: str = Field(default="", max_length=120)
    admin_email: str = Field(max_length=254)
    admin_password: str = Field(min_length=6, max_length=200)


class TenantPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    active: bool | None = None
    plano: Plano | None = None
    trial_ate: str | None = Field(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")


class NichoOut(BaseModel):
    yaml: str
    nome: str
    solucoes: int
    palavras_chave: int


class NichoIn(BaseModel):
    yaml: str = Field(min_length=10, max_length=200_000)
