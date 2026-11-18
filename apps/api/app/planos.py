"""Planos de assinatura — fonte única de verdade dos limites e recursos.

Regra de projeto: nada de `if plano == "comercial"` espalhado pelo código. Todo
lugar que precisa saber algo consulta ``limite()`` ou ``tem()``. Trocar a régua
comercial vira edição de UMA tabela, não caça a condicionais.

Duas categorias, porque o cliente sente cada uma de um jeito:
  - ``limites``  : números. Sentidos como atrito ("só posso trazer 40 por vez").
  - ``recursos`` : capacidades. Sentidas como falta ("não sei o porte do lead").

O que está bloqueado aparece na tela MARCADO, nunca escondido — recurso oculto
não gera upgrade, porque o cliente nunca descobre que existe.
"""

from __future__ import annotations

from datetime import date, datetime

# Ordem importa: define o que é "superior" na hora de sugerir o upgrade.
ORDEM = ("essencial", "profissional", "empresarial")

ILIMITADO = 10 ** 9   # sentinela; comparações continuam funcionando sem caso especial

# Valores de EXEMPLO. A régua comercial é decisão do dono da plataforma: ajuste
# preços e limites aqui (é a única fonte) antes de vender.
PLANOS: dict[str, dict] = {
    "essencial": {
        "nome": "Essencial",
        "preco": "a definir",
        "limites": {
            "usuarios": 5,
            "leads_mes": 1000,
            "leads_clique": 40,
            "historico_dias": 60,
            "emails_dia": 20,
        },
        "recursos": {
            "porte": False,           # porte publicado + dados cadastrais da Receita
            "linkedin": False,        # busca do LinkedIn da empresa na web
            "filtro_regiao": False,   # focar uma macro-região do Brasil
        },
    },
    "profissional": {
        "nome": "Profissional",
        "preco": "a definir",
        "limites": {
            "usuarios": 12,
            "leads_mes": 3000,
            "leads_clique": 100,
            "historico_dias": 365,
            "emails_dia": 50,
        },
        "recursos": {"porte": True, "linkedin": True, "filtro_regiao": True},
    },
    "empresarial": {
        "nome": "Empresarial",
        "preco": "a definir",
        "limites": {
            "usuarios": ILIMITADO,
            "leads_mes": ILIMITADO,
            "leads_clique": 200,
            "historico_dias": ILIMITADO,
            "emails_dia": 100,
        },
        "recursos": {"porte": True, "linkedin": True, "filtro_regiao": True},
    },
}

PLANO_PADRAO = "essencial"
# Durante o teste, a conta roda como o plano mais alto: é o período em que o
# cliente precisa VER o produto inteiro para escolher onde quer ficar.
PLANO_TESTE = "empresarial"


def normaliza(plano: str | None) -> str:
    p = (plano or "").strip().lower()
    return p if p in PLANOS else PLANO_PADRAO


def em_teste(trial_ate: str | None) -> bool:
    """True enquanto a data de fim do teste (YYYY-MM-DD) não passou."""
    if not trial_ate:
        return False
    try:
        return date.today() <= datetime.strptime(str(trial_ate)[:10], "%Y-%m-%d").date()
    except ValueError:
        return False


def plano_efetivo(plano: str | None, trial_ate: str | None = None) -> str:
    """O plano que VALE agora: o do teste enquanto ele durar, senão o contratado."""
    return PLANO_TESTE if em_teste(trial_ate) else normaliza(plano)


def limite(plano: str | None, chave: str, trial_ate: str | None = None) -> int:
    return PLANOS[plano_efetivo(plano, trial_ate)]["limites"].get(chave, 0)


def tem(plano: str | None, recurso: str, trial_ate: str | None = None) -> bool:
    return bool(PLANOS[plano_efetivo(plano, trial_ate)]["recursos"].get(recurso, False))


def nome(plano: str | None, trial_ate: str | None = None) -> str:
    return PLANOS[plano_efetivo(plano, trial_ate)]["nome"]


def ilimitado(valor: int) -> bool:
    return valor >= ILIMITADO


def formata(valor: int) -> str:
    """Número para a tela: 'ilimitado' em vez de 1000000000."""
    return "ilimitado" if ilimitado(valor) else f"{valor:,}".replace(",", ".")


def plano_minimo_com(recurso: str) -> str:
    """Nome do plano mais barato que inclui o recurso — usado no selo de upgrade."""
    for p in ORDEM:
        if PLANOS[p]["recursos"].get(recurso):
            return PLANOS[p]["nome"]
    return PLANOS[ORDEM[-1]]["nome"]


def selo_upgrade(recurso: str) -> str:
    """Texto curto do bloqueio. Diz o QUE falta e ONDE está, sem rodeio."""
    return f"Disponível no plano {plano_minimo_com(recurso)}"
