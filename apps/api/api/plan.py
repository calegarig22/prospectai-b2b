"""Contexto do plano da empresa — toda regra de limite passa por aqui.

As regras em si continuam em app/planos.py (fonte única). Este módulo junta o
plano da empresa com o consumo do mês, para a API e para a tela.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException, status

from app import db, leads, orgs, planos


@dataclass(frozen=True)
class PlanCtx:
    org_id: str
    org_name: str
    contratado: str
    trial_ate: str

    @property
    def efetivo(self) -> str:
        return planos.plano_efetivo(self.contratado, self.trial_ate)

    @property
    def em_teste(self) -> bool:
        return planos.em_teste(self.trial_ate)

    def limite(self, chave: str) -> int:
        return planos.limite(self.contratado, chave, self.trial_ate)

    def tem(self, recurso: str) -> bool:
        return planos.tem(self.contratado, recurso, self.trial_ate)


def load(org_id: str) -> PlanCtx:
    with db.conn() as c:
        org = orgs.get(c, org_id)
    if not org:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Empresa não encontrada.")
    return PlanCtx(org_id=org_id, org_name=org["name"],
                   contratado=planos.normaliza(org["plano"]), trial_ate=org["trial_ate"])


def inicio_do_mes() -> str:
    return datetime.now().strftime("%Y-%m-01")


def renova_em() -> str:
    """Dia 1º do mês seguinte (a cota zera aí)."""
    hoje = datetime.now()
    return hoje.replace(day=1, month=hoje.month % 12 + 1,
                        year=hoje.year + (1 if hoje.month == 12 else 0)).strftime("%Y-%m-%d")


def leads_no_mes(org_id: str) -> int:
    with db.conn() as c:
        return leads.leads_desde(c, org_id, inicio_do_mes())


def matriz() -> dict:
    """Tabela completa dos planos, para a tela de comparação."""
    return {
        "ordem": list(planos.ORDEM),
        "planos": {p: {"nome": d["nome"], "preco": d["preco"],
                       "limites": d["limites"], "recursos": d["recursos"]}
                   for p, d in planos.PLANOS.items()},
        "ilimitado": planos.ILIMITADO,
    }
