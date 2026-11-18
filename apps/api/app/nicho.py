"""Nicho do cliente: o que buscar, como pontuar, o que oferecer e com quem falar.

É o que torna o ProspectAI configurável. O MOTOR (busca, leitura de site,
contatos, Receita) é o mesmo para todo mundo; o NICHO muda tudo o que é do
negócio do cliente:

- ``busca``: palavras-chave, buscas "premium", variações, regiões e ruído a cortar.
- ``pontuacao``: sinais de necessidade, segmentos, tipos de empresa, concorrentes
  e os cortes de HOT/WARM.
- ``solucoes``: o catálogo do cliente e as pistas no site que indicam cada item.
- ``decisores``: cargos que decidem a compra e o cargo-alvo de cada solução.
- ``porte``: como medir o tamanho do lead pelo que ele publica (opcional).

Cada empresa (tenant) guarda o seu nicho no banco (``orgs.nicho``, JSON). O motor
roda num processo por lote e lê o nicho DAQUELE lote de um arquivo indicado em
``PROSPECT_NICHO_FILE`` — assim um lote nunca enxerga o nicho de outra empresa.
Sem a variável (testes, uso local), vale ``config/nicho.exemplo.yaml``.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .utils import strip_accents

EXEMPLO_PATH = Path(__file__).resolve().parent.parent / "config" / "nicho.exemplo.yaml"
ENV_FILE = "PROSPECT_NICHO_FILE"

# Tetos de tamanho: o nicho é editado por tela e vai inteiro para cada lote.
_MAX_LISTA = 400
_MAX_TEXTO = 160


class NichoInvalido(ValueError):
    """Configuração de nicho com erro. A mensagem vai para a tela, em português."""


@dataclass(frozen=True)
class Solucao:
    nome: str
    curto: str
    sinais: tuple[str, ...]
    decisor: str = ""
    # Se alguma destas soluções já foi detectada, esta some (ex.: um item que já
    # inclui o outro). Evita oferecer duas vezes a mesma coisa.
    oculta_se: tuple[str, ...] = ()


@dataclass(frozen=True)
class Porte:
    ativo: bool = False
    rotulo: str = "unidades"                 # "120 unidades" na planilha
    unidades: tuple[str, ...] = ()           # palavras DEPOIS do número
    contexto: tuple[str, ...] = ()           # palavras ANTES do número ("rede de")
    media_a_partir_de: int = 25
    grande_a_partir_de: int = 100
    qualifica_a_partir_de: int = 0           # 0 = o porte não força a entrega


@dataclass(frozen=True)
class Nicho:
    nome: str
    descricao: str
    palavras_chave: tuple[str, ...]
    buscas_premium: tuple[str, ...] = ()
    modificadores: tuple[str, ...] = ()
    formas: tuple[str, ...] = ()
    regioes_busca: tuple[str, ...] = ()
    ruido: tuple[str, ...] = ()
    fornecedores: tuple[str, ...] = ()
    paginas_operacao: tuple[str, ...] = ()
    titulos_de_servico: tuple[str, ...] = ()
    base_curada: tuple[str, ...] = ()
    hot: int = 60
    warm: int = 50
    max_score: int = 100
    exige_sinal_de_necessidade: bool = True
    necessidades: dict[str, int] = field(default_factory=dict)
    segmentos: dict[str, int] = field(default_factory=dict)
    tipos_empresa: dict[str, int] = field(default_factory=dict)
    concorrentes: dict[str, int] = field(default_factory=dict)
    solucoes: tuple[Solucao, ...] = ()
    cargos: tuple[tuple[str, str, int], ...] = ()
    decisor_padrao: str = "Diretor Comercial"
    porte: Porte = Porte()
    email_operacao: tuple[str, ...] = ()
    email_nao_pessoa: tuple[str, ...] = ()

    # ------------------------------------------------------------ derivados
    def scoring(self) -> dict[str, Any]:
        """Formato que app/scorer.py consome."""
        return {"hot_threshold": self.hot, "warm_threshold": self.warm,
                "max_score": self.max_score,
                "require_need_signal": self.exige_sinal_de_necessidade,
                "needs": dict(self.necessidades), "segments": dict(self.segmentos),
                "company_types": dict(self.tipos_empresa),
                "competitors": dict(self.concorrentes)}

    def nomes_solucoes(self) -> list[str]:
        return [s.nome for s in self.solucoes]

    def curtos(self) -> dict[str, str]:
        return {s.nome: s.curto for s in self.solucoes}

    def para_dict(self) -> dict[str, Any]:
        return _para_dict(self)


# ------------------------------------------------------------------ leitura
def _texto(v: Any, campo: str, obrigatorio: bool = False) -> str:
    s = "" if v is None else str(v).strip()
    if obrigatorio and not s:
        raise NichoInvalido(f"Preencha '{campo}'.")
    if len(s) > _MAX_TEXTO * 4:
        raise NichoInvalido(f"'{campo}' está longo demais.")
    return s


def _lista(v: Any, campo: str) -> tuple[str, ...]:
    if v is None:
        return ()
    if not isinstance(v, list):
        raise NichoInvalido(f"'{campo}' precisa ser uma lista.")
    if len(v) > _MAX_LISTA:
        raise NichoInvalido(f"'{campo}' tem itens demais (máximo {_MAX_LISTA}).")
    out = []
    for item in v:
        s = str(item).strip() if item is not None else ""
        if len(s) > _MAX_TEXTO:
            raise NichoInvalido(f"Item longo demais em '{campo}': {s[:40]}…")
        if s:
            out.append(s)
    return tuple(out)


def _pesos(v: Any, campo: str) -> dict[str, int]:
    if v is None:
        return {}
    if not isinstance(v, dict):
        raise NichoInvalido(f"'{campo}' precisa ser uma lista de 'termo: peso'.")
    if len(v) > _MAX_LISTA:
        raise NichoInvalido(f"'{campo}' tem itens demais (máximo {_MAX_LISTA}).")
    out = {}
    for termo, peso in v.items():
        t = str(termo).strip()
        try:
            p = int(peso)
        except (TypeError, ValueError):
            raise NichoInvalido(f"O peso de '{t}' em '{campo}' precisa ser um número.")
        if not -100 <= p <= 100:
            raise NichoInvalido(f"O peso de '{t}' em '{campo}' precisa ficar entre -100 e 100.")
        if t:
            out[t] = p
    return out


def _inteiro(v: Any, campo: str, padrao: int, minimo: int = 0, maximo: int = 100_000) -> int:
    if v is None or v == "":
        return padrao
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise NichoInvalido(f"'{campo}' precisa ser um número.")
    if not minimo <= n <= maximo:
        raise NichoInvalido(f"'{campo}' precisa ficar entre {minimo} e {maximo}.")
    return n


def de_dict(d: Any) -> Nicho:
    """Valida e monta o nicho. Levanta NichoInvalido com mensagem para a tela."""
    if not isinstance(d, dict):
        raise NichoInvalido("A configuração do nicho precisa ser um mapeamento (chave: valor).")
    busca = d.get("busca") or {}
    pont = d.get("pontuacao") or {}
    dec = d.get("decisores") or {}
    por = d.get("porte") or {}
    em = d.get("email") or {}
    for nome, bloco in (("busca", busca), ("pontuacao", pont), ("decisores", dec),
                        ("porte", por), ("email", em)):
        if not isinstance(bloco, dict):
            raise NichoInvalido(f"'{nome}' precisa ser um bloco de chaves.")

    palavras = _lista(busca.get("palavras_chave"), "busca.palavras_chave")
    if not palavras:
        raise NichoInvalido("Informe ao menos uma palavra-chave em 'busca.palavras_chave'.")

    hot = _inteiro(pont.get("hot"), "pontuacao.hot", 60, 1, 100)
    warm = _inteiro(pont.get("warm"), "pontuacao.warm", 50, 0, 100)
    if warm > hot:
        raise NichoInvalido("'pontuacao.warm' não pode ser maior que 'pontuacao.hot'.")

    solucoes = []
    nomes = set()
    raw_sols = d.get("solucoes") or []
    if not isinstance(raw_sols, list):
        raise NichoInvalido("'solucoes' precisa ser uma lista.")
    for i, s in enumerate(raw_sols, start=1):
        if not isinstance(s, dict):
            raise NichoInvalido(f"A solução nº {i} precisa ter 'nome' e 'sinais'.")
        nome = _texto(s.get("nome"), f"solucoes[{i}].nome", obrigatorio=True)
        if nome in nomes:
            raise NichoInvalido(f"Solução repetida: {nome}.")
        nomes.add(nome)
        sinais = _lista(s.get("sinais"), f"solucoes[{i}].sinais")
        if not sinais:
            raise NichoInvalido(f"A solução '{nome}' precisa de ao menos um sinal.")
        solucoes.append(Solucao(nome=nome, curto=_texto(s.get("curto"), "curto") or nome,
                                sinais=sinais, decisor=_texto(s.get("decisor"), "decisor"),
                                oculta_se=_lista(s.get("oculta_se"), f"solucoes[{i}].oculta_se")))
    for s in solucoes:
        for outra in s.oculta_se:
            if outra not in nomes:
                raise NichoInvalido(f"'{s.nome}' cita em 'oculta_se' uma solução que não existe: {outra}.")

    cargos = []
    raw_cargos = dec.get("cargos") or []
    if not isinstance(raw_cargos, list):
        raise NichoInvalido("'decisores.cargos' precisa ser uma lista.")
    for c in raw_cargos:
        if not isinstance(c, dict) or not c.get("termo"):
            raise NichoInvalido("Cada cargo precisa de 'termo', 'rotulo' e 'prioridade'.")
        termo = _texto(c.get("termo"), "termo")
        cargos.append((termo, _texto(c.get("rotulo"), "rotulo") or termo,
                       _inteiro(c.get("prioridade"), "prioridade", 80, 1, 99)))

    porte = Porte(
        ativo=bool(por.get("ativo", False)),
        rotulo=_texto(por.get("rotulo"), "porte.rotulo") or "unidades",
        unidades=_lista(por.get("unidades"), "porte.unidades"),
        contexto=_lista(por.get("contexto"), "porte.contexto"),
        media_a_partir_de=_inteiro(por.get("media_a_partir_de"), "porte.media_a_partir_de", 25, 1),
        grande_a_partir_de=_inteiro(por.get("grande_a_partir_de"), "porte.grande_a_partir_de", 100, 1),
        qualifica_a_partir_de=_inteiro(por.get("qualifica_a_partir_de"),
                                       "porte.qualifica_a_partir_de", 0, 0),
    )
    if porte.ativo and not (porte.unidades or porte.contexto):
        raise NichoInvalido("Com 'porte.ativo', informe 'porte.unidades' ou 'porte.contexto'.")

    return Nicho(
        nome=_texto(d.get("nome"), "nome", obrigatorio=True),
        descricao=_texto(d.get("descricao"), "descricao"),
        palavras_chave=palavras,
        buscas_premium=_lista(busca.get("buscas_premium"), "busca.buscas_premium"),
        modificadores=_lista(busca.get("modificadores"), "busca.modificadores"),
        formas=_lista(busca.get("formas"), "busca.formas"),
        regioes_busca=_lista(busca.get("regioes"), "busca.regioes"),
        ruido=_lista(busca.get("ruido"), "busca.ruido"),
        fornecedores=_lista(busca.get("fornecedores"), "busca.fornecedores"),
        paginas_operacao=_lista(busca.get("paginas_operacao"), "busca.paginas_operacao"),
        titulos_de_servico=_lista(busca.get("titulos_de_servico"), "busca.titulos_de_servico"),
        base_curada=_lista(busca.get("base_curada"), "busca.base_curada"),
        hot=hot, warm=warm,
        max_score=_inteiro(pont.get("max_score"), "pontuacao.max_score", 100, 1, 1000),
        exige_sinal_de_necessidade=bool(pont.get("exige_sinal_de_necessidade", True)),
        necessidades=_pesos(pont.get("necessidades"), "pontuacao.necessidades"),
        segmentos=_pesos(pont.get("segmentos"), "pontuacao.segmentos"),
        tipos_empresa=_pesos(pont.get("tipos_empresa"), "pontuacao.tipos_empresa"),
        concorrentes=_pesos(pont.get("concorrentes"), "pontuacao.concorrentes"),
        solucoes=tuple(solucoes),
        cargos=tuple(cargos),
        decisor_padrao=_texto(dec.get("padrao"), "decisores.padrao") or "Diretor Comercial",
        porte=porte,
        email_operacao=_lista(em.get("palavras_operacao"), "email.palavras_operacao"),
        email_nao_pessoa=_lista(em.get("nao_e_pessoa"), "email.nao_e_pessoa"),
    )


def _para_dict(n: Nicho) -> dict[str, Any]:
    """Volta ao formato do YAML/JSON (o que a tela de edição mostra)."""
    return {
        "nome": n.nome, "descricao": n.descricao,
        "busca": {"palavras_chave": list(n.palavras_chave),
                  "buscas_premium": list(n.buscas_premium),
                  "modificadores": list(n.modificadores), "formas": list(n.formas),
                  "regioes": list(n.regioes_busca), "ruido": list(n.ruido),
                  "fornecedores": list(n.fornecedores),
                  "paginas_operacao": list(n.paginas_operacao),
                  "titulos_de_servico": list(n.titulos_de_servico),
                  "base_curada": list(n.base_curada)},
        "pontuacao": {"hot": n.hot, "warm": n.warm, "max_score": n.max_score,
                      "exige_sinal_de_necessidade": n.exige_sinal_de_necessidade,
                      "necessidades": n.necessidades, "segmentos": n.segmentos,
                      "tipos_empresa": n.tipos_empresa, "concorrentes": n.concorrentes},
        "solucoes": [{"nome": s.nome, "curto": s.curto, "sinais": list(s.sinais),
                      "decisor": s.decisor, "oculta_se": list(s.oculta_se)}
                     for s in n.solucoes],
        "decisores": {"padrao": n.decisor_padrao,
                      "cargos": [{"termo": t, "rotulo": r, "prioridade": p}
                                 for t, r, p in n.cargos]},
        "porte": {"ativo": n.porte.ativo, "rotulo": n.porte.rotulo,
                  "unidades": list(n.porte.unidades), "contexto": list(n.porte.contexto),
                  "media_a_partir_de": n.porte.media_a_partir_de,
                  "grande_a_partir_de": n.porte.grande_a_partir_de,
                  "qualifica_a_partir_de": n.porte.qualifica_a_partir_de},
        "email": {"palavras_operacao": list(n.email_operacao),
                  "nao_e_pessoa": list(n.email_nao_pessoa)},
    }


def de_yaml(texto: str) -> Nicho:
    try:
        dados = yaml.safe_load(texto or "")
    except yaml.YAMLError as erro:
        linha = getattr(getattr(erro, "problem_mark", None), "line", None)
        onde = f" (linha {linha + 1})" if linha is not None else ""
        raise NichoInvalido(f"O texto não é um YAML válido{onde}. Confira a indentação.")
    return de_dict(dados)


def para_yaml(n: Nicho) -> str:
    return yaml.safe_dump(n.para_dict(), allow_unicode=True, sort_keys=False, width=100)


def exemplo() -> Nicho:
    return de_yaml(EXEMPLO_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def ativo() -> Nicho:
    """Nicho do lote em execução (um processo = um lote = uma empresa)."""
    caminho = (os.environ.get(ENV_FILE) or "").strip()
    if caminho:
        return de_dict(json.loads(Path(caminho).read_text(encoding="utf-8")))
    return exemplo()


def norm(texto: str) -> str:
    """Minúsculo e sem acento: a base de todo casamento de termo."""
    return strip_accents((texto or "").lower())


def normalizados(itens) -> tuple[str, ...]:
    return tuple(norm(x) for x in itens if x)


def casa(termo: str, blob: str) -> bool:
    """Casamento de termo já sem acento e minúsculo (use ``norm`` nos dois lados).

    - Frase (espaço/hífen): substring.
    - Termo terminado em ``*``: prefixo ("restaurant*" casa restaurante/restaurantes).
    - Palavra única: limite de palavra ("usb" não casa "usbank").
    """
    if termo.endswith("*"):
        return re.search(r"\b" + re.escape(termo[:-1]), blob) is not None
    if " " in termo or "-" in termo:
        return termo in blob
    return re.search(r"\b" + re.escape(termo) + r"\b", blob) is not None
