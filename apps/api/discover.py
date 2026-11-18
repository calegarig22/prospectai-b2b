"""Descoberta de leads de UMA empresa cliente (um processo = um lote = uma empresa).

A cada execução: dispara buscas rotativas montadas com o NICHO da empresa
(palavras-chave, buscas premium, variações e regiões), filtra ruído, descarta o
que a MEMÓRIA DAQUELA EMPRESA já viu, completa com a base curada do nicho se a
web render pouco, pontua, enriquece (contatos, decisor, porte, cidade e as
SOLUÇÕES do catálogo do cliente) e grava o lote no banco.

Quem chama (a API) passa no ambiente:
    ORG_ID               empresa dona do lote (OBRIGATÓRIO — sem ele não roda)
    OWNER_ID             usuário que pediu
    PROSPECT_NICHO_FILE  JSON com o nicho da empresa
    PROSPECT_REGION / PROSPECT_REQUIRE_CONTACT / PROSPECT_PORTE / PROSPECT_LINKEDIN
    PROSPECT_DEVICE

Uso local:  ORG_ID=org-... python discover.py 40
"""

from __future__ import annotations

import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from app import db, leads as leads_repo, nicho as _nicho, orgs as orgs_repo

from app.blacklist import parece_portal_de_noticia, filter_blacklist
from app.config_loader import load_config
from app.deduplicator import deduplicate
from app.enrichment import _process_lead
from app.fetcher import fetch_homepage
from app.geo_lang import detect_country
from app.logger import enable_utf8_console, setup_logger
from app.models import Lead
from app.planos import ilimitado as plano_ilimitado, limite as limite_plano, nome as nome_plano
from app.regions import CONTINENTS, WORLD, in_region_confirmed, is_region, keep_for_region
from app.scorer import score_text
from app.search_engine import SearchEngine
from app.utils import company_name_from_domain, normalize_domain, strip_accents

TARGET_DEFAULT = 60
QUERIES_PER_RUN = 10

# Ruído GENÉRICO (não são empresas-alvo em nenhum nicho): diretórios, listas,
# notícias, marketplaces, enciclopédias e redes sociais. O ruído próprio do nicho
# (portais do setor, concorrentes) vem de ``busca.ruido`` — ver _ruido().
_NOISE = (
    # dicionários / enciclopédia / referência
    "wikipedia", "wikiwand", "wiktionary", "dicio", "dicionario", "significados",
    "priberam", "michaelis", "infopedia", "investopedia", "thefreedictionary", "britannica",
    # marketplaces / classificados / e-commerce
    "amazon.", "alibaba", "made-in-china", "indiamart", "tradeindia", "ebay", "aliexpress",
    "mercadolivre", "mercadolibre", "olx", "shopee", "americanas", "magazineluiza",
    "exportersindia", "go4worldbusiness", "solostocks", "tradekey", "globalsources",
    # diretórios / agregadores / bases de empresas (NÃO são prospects)
    "quiminet", "thomasnet", "kompass", "europages", "yellowpages", "yelp", "guiamais",
    "telelistas", "apontador", "encontreempresas", "listaempresas", "directory", "directorio",
    "diretorio", "econodata", "escavador", "jusbrasil", "consultacnpj", "cnpj.", "empresascnpj",
    "razaosocial", "f6s", "crunchbase", "startupbase",
    # vagas / RH portais / redes sociais
    "indeed", "glassdoor", "catho", "infojobs", "empregos", "vagas", "gupy", "linkedin",
    "facebook", "instagram", "youtube", "twitter", "x.com", "tiktok", "pinterest", "reddit",
    # notícias / mídia / imprensa em geral
    "noticia", "news", "jornal", "globo.", "uol.", "estadao", "folha.", "exame.", "revista",
    "magazine", "blog.", "wordpress.com", "medium.com", "slideshare", "scribd", "researchgate",
    "gazeta", "noticias", "redacao", "tribuna", "diariodo", "portalde", "folhade",
    # governo / educação / ferramentas / reviews
    "gov.", "edu.", "sebrae", "calculator", "symbolab", "conversor", "reclameaqui",
    "trustpilot", "ranking", "top10",
    # sites de conteúdo educativo (não são empresas)
    "infoescola", "brasilescola", "mundoeducacao", "todamateria", "conhecimentosgerais",
    "escolakids", "stoodi", "coladaweb",
    # entretenimento / streaming / cripto / jogos
    "imdb", "rottentomatoes", "fandango", "metacritic", "letterboxd",
    "netflix", "spotify", "twitch", "steampowered", "epicgames", "gamespot", "ign.com",
    "nicehash", "coinmarketcap", "coingecko", "binance",
    # OTAs / plataformas de reserva (revendem, não são o lead)
    "tripadvisor", "expedia", "booking.",
    # órgãos, sindicatos e associações (não compram direto)
    "prefeitura", "sindicato", "federacao das empresas", "associacao das empresas",
)


def _ruido() -> tuple[str, ...]:
    return _NOISE + _nicho.normalizados(_nicho.ativo().ruido)


def _target() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PROSPECT_BATCH")
    if arg:
        try:
            n = int(arg)
            if n > 0:
                return n
        except ValueError:
            pass
    return TARGET_DEFAULT


def _read_seeds() -> list[str]:
    """Base curada do NICHO (domínios que o dono da plataforma já sabe que servem)."""
    out, seen = [], set()
    for line in _nicho.ativo().base_curada:
        d = normalize_domain(line.strip()) or line.strip()
        if d and d not in seen:
            seen.add(d)
            out.append(d)
    return out


def _e_fornecedor(blob_sem_acento: str) -> bool:
    """O 'lead' é quem VENDE para o mesmo comprador (concorrente), não quem compra?

    As frases vêm do nicho (``busca.fornecedores``): só entram frases que um
    COMPRADOR não usa para descrever a si mesmo.
    """
    return any(f in blob_sem_acento for f in _nicho.normalizados(_nicho.ativo().fornecedores))


def _vale_entregar(hot, piso_score: int) -> bool:
    """O lead tem qualidade para ir ao cliente?

    A nota sozinha não decide: ela lê o TEXTO do site, e empresa grande costuma
    ter site institucional enxuto. Então entra quem passa do piso OU quem exibe
    evidência OBJETIVA de porte (quantidade declarada acima do mínimo do nicho, ou
    porte Grande na Receita). Fora isso, fica de fora: lead fraco não chega ao vendedor.
    """
    if getattr(hot, "score", 0) >= piso_score:
        return True
    minimo = _nicho.ativo().porte.qualifica_a_partir_de
    if minimo and getattr(hot, "porte_numero", 0) >= minimo:
        return True
    return getattr(hot, "porte", "") == "Grande"


def _is_relevant(lead: Lead, domain: str) -> bool:
    """Mantém empresas plausíveis; corta ruído (diretórios, notícias, marketplaces)."""
    name = (lead.company or "").strip()
    if len(name) <= 2:
        return False
    if domain.endswith(".org") or ".org." in domain:   # associações/ONGs, não são compradoras
        return False
    blob = (domain + " " + lead.title + " " + lead.description).lower()
    ruido = _ruido()
    if any(n in domain for n in ruido) or any(n in strip_accents(blob) for n in ruido):
        return False
    if _e_fornecedor(strip_accents(blob)):
        return False
    return True


# Eixos de variação da busca quando o nicho não define os seus. Combinados com as
# palavras-chave, geram buscas DISTINTAS (cada combinação revela empresas novas).
_MODIFICADORES_PADRAO = ["", "", "empresa", "grupo", "site oficial", "fale conosco",
                         "matriz", "CNPJ", "razão social", "tradicional", "líder"]
_REGIOES_PADRAO = ["", "", "São Paulo", "São Paulo", "Minas Gerais", "Rio de Janeiro",
                   "Paraná", "Santa Catarina", "Rio Grande do Sul", "Bahia", "Pernambuco",
                   "Ceará", "Goiás", "Distrito Federal", "Espírito Santo", "Mato Grosso",
                   "Pará", "Amazonas"]


def _rotating_queries(n: int, region_terms: list[str] | None = None) -> list[str]:
    """Monta ``n`` buscas: ~40% buscas premium do nicho + palavras-chave decoradas.

    Com filtro de região (``region_terms``), decora bem mais vezes com os lugares
    da região — os resultados puxam para lá; o portão de entrega cuida do resto.
    """
    ni = _nicho.ativo()
    prem = list(ni.buscas_premium)
    random.shuffle(prem)
    n_premium = min(len(prem), max(2, n * 4 // 10)) if prem else 0
    prem = prem[:n_premium]
    base = list(ni.palavras_chave)
    random.shuffle(base)
    base = base[:max(0, n - n_premium)]
    forms = [f for f in ni.formas if f]
    mods = [m for m in (ni.modificadores or _MODIFICADORES_PADRAO) if m]
    regs = region_terms if region_terms else [r for r in (ni.regioes_busca or _REGIOES_PADRAO) if r]
    filtering = bool(region_terms)
    queries: list[str] = []
    for kw in prem:
        queries.append(f"{kw} {random.choice(regs)}" if (filtering and random.random() < 0.65)
                       or (not filtering and random.random() < 0.25) else kw)
    for kw in base:
        roll = random.random()
        if filtering:                                  # puxa forte para a região
            if roll < 0.55:
                q = f"{kw} {random.choice(regs)}"
            elif roll < 0.78 and forms:
                q = f"{random.choice(forms)} {kw} {random.choice(regs)}"
            elif roll < 0.90:
                q = f"{random.choice(mods)} {kw}"
            else:
                q = kw
        elif roll < 0.40:                              # busca pura (ampla)
            q = kw
        elif roll < 0.62 and forms:                    # + forma de operação
            q = f"{random.choice(forms)} {kw}"
        elif roll < 0.80:                              # + modificador
            q = f"{random.choice(mods)} {kw}"
        else:                                          # + região
            q = f"{kw} {random.choice(regs)}"
        queries.append(q)
    random.shuffle(queries)
    return list(dict.fromkeys(queries))


def _score_and_enrich(leads: list[Lead], config: dict, logger) -> list:
    fetch_cfg = config["fetch"]
    scoring = _nicho.ativo().scoring()

    def score_one(lead: Lead) -> Lead:
        page = fetch_homepage(lead.website, timeout=fetch_cfg["timeout_seconds"],
                              max_chars=fetch_cfg["max_text_chars"],
                              user_agent=fetch_cfg["user_agent"], logger=logger)
        if page.ok:
            lead.title = page.title or lead.title
            lead.description = page.description or lead.description
        blob = " ".join([lead.company, normalize_domain(lead.website),
                         lead.search_keyword, lead.title, lead.description, page.text])
        r = score_text(blob, scoring)
        lead.score, lead.classification, lead.keywords_found = r.score, r.classification, r.keywords_found
        return lead

    with ThreadPoolExecutor(max_workers=fetch_cfg["max_workers"]) as ex:
        scored = list(ex.map(score_one, leads))
    # PRÉ-FILTRO: a classificação é definida AQUI (na home) e não muda no enriquecimento.
    # Então enriquece (caro: páginas profundas + telefone/CNPJ na web) SÓ quem já é WARM/HOT —
    # nada de gastar tempo com COLD que seria descartado depois.
    warm = scoring.get("warm_threshold", 35)
    worth = [l for l in scored if l.score >= warm]
    logger.info("Pré-filtro: %d de %d são WARM/HOT e seguem p/ enriquecimento (COLD descartado já).",
                len(worth), len(scored))
    with ThreadPoolExecutor(max_workers=config["enrichment"]["max_workers"]) as ex:
        return list(ex.map(lambda l: _process_lead(l, config, logger), worth))


def _warn_if_systemic(failures: int, total: int, first_error: str, logger,
                      fase: str = "enriquecimento") -> None:
    """Grita quando MUITOS leads falham — falha sistêmica não pode passar como rotina.

    Uma falha isolada (site fora do ar, timeout) é normal e fica em DEBUG. Mas se
    metade do lote quebra, é bug nosso: sem este aviso o lote sai vazio de contatos
    e parece só um dia ruim de busca.
    """
    if not total or not failures:
        return
    taxa = failures / total
    msg = "Falha no %s: %d de %d lead(s) (%.0f%%). Primeiro erro: %s"
    if taxa >= 0.5:
        logger.error(msg, fase, failures, total, taxa * 100, first_error or "?")
    elif taxa >= 0.2:
        logger.warning(msg, fase, failures, total, taxa * 100, first_error or "?")


def _process_one(lead: Lead, config: dict, logger):
    """Pontua a homepage e SEMPRE enriquece (nunca descarta) — garante a entrega.

    Não joga fora ninguém aqui: os mais fracos entram como PREENCHIMENTO,
    ranqueados abaixo das HOT, e o piso de entrega decide depois quem vai ao cliente. A busca de contato cara só roda nos HOT
    (web_contact_lookup), então enriquecer todos continua rápido.
    """
    fetch_cfg = config["fetch"]
    scoring = _nicho.ativo().scoring()
    page = fetch_homepage(lead.website, timeout=fetch_cfg["timeout_seconds"],
                          max_chars=fetch_cfg["max_text_chars"],
                          user_agent=fetch_cfg["user_agent"], logger=logger)
    if page.ok:
        lead.title = page.title or lead.title
        lead.description = page.description or lead.description
    blob = " ".join([lead.company, normalize_domain(lead.website),
                     lead.search_keyword, lead.title, lead.description, page.text])
    r = score_text(blob, scoring)
    lead.score, lead.classification, lead.keywords_found = r.score, r.classification, r.keywords_found
    # Portal de notícia do setor fala do assunto do nicho o dia inteiro e pontua alto —
    # mas não compra nada. O domínio não denuncia (aparecem portais novos toda
    # semana); a estrutura do conteúdo, sim.
    if page.ok and parece_portal_de_noticia(page.text):
        lead.classification = "COLD"
        lead.score = 0
        logger.debug("Descartado (portal de notícia): %s", lead.website)
    return _process_lead(lead, config, logger, deep=False)   # LEVE (só homepage) — rápido p/ filtrar


_LOCK_PATH = Path("exports/.lote.lock")
_LOCK_VALIDADE_S = 45 * 60      # acima disto o lock é considerado abandonado


def _processo_vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)         # sinal 0 não mata: só pergunta se existe
    except (OSError, ValueError):
        return False
    return True


@contextmanager
def _lote_exclusivo(logger):
    """Impede DOIS lotes ao mesmo tempo na mesma instalação.

    Todo lote escreve nos MESMOS arquivos (``exports/seed_leads.xlsx``,
    ``web/index.html``). Com 5 a 12 vendedores na conta, dois cliques
    simultâneos se sobrescrevem e o segundo lote sai corrompido ou pela metade.
    Um lock de arquivo com PID resolve: se o dono do lock morreu ou o lock é
    antigo, ele é considerado abandonado e a execução segue — nunca trava o
    sistema por um processo que caiu.
    """
    _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _LOCK_PATH.exists():
        try:
            pid_txt, quando = _LOCK_PATH.read_text(encoding="utf-8").split("|", 1)
            pid, idade = int(pid_txt), time.time() - float(quando)
        except Exception:  # noqa: BLE001 - lock ilegível = lock abandonado
            pid, idade = -1, _LOCK_VALIDADE_S + 1
        if pid != os.getpid() and _processo_vivo(pid) and idade < _LOCK_VALIDADE_S:
            logger.error("JÁ HÁ UM LOTE EM ANDAMENTO (iniciado há %s). Espere ele terminar: "
                         "dois lotes ao mesmo tempo escrevem nos mesmos arquivos e um "
                         "sobrescreve o outro.", _fmt_duration(idade))
            yield False
            return
        logger.debug("Lock antigo/órfão encontrado (pid %s); assumindo.", pid)
    _LOCK_PATH.write_text(f"{os.getpid()}|{time.time()}", encoding="utf-8")
    try:
        yield True
    finally:
        try:    # só remove se ainda for MEU (o dono pode ter mudado num lock órfão)
            if _LOCK_PATH.exists() and _LOCK_PATH.read_text(encoding="utf-8").startswith(f"{os.getpid()}|"):
                _LOCK_PATH.unlink()
        except Exception:  # noqa: BLE001 - falhar ao limpar não pode derrubar o lote
            pass


def _fmt_duration(seconds: float) -> str:
    """Formata segundos de forma legível: '45s' ou '3min 18s'."""
    seconds = int(round(seconds))
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}min {seconds % 60:02d}s"


def main() -> int:
    enable_utf8_console()
    config = load_config()
    logger = setup_logger(level=config["logging"]["level"], directory=config["logging"]["directory"])
    # UM LOTE POR VEZ nesta instalação (ver _lote_exclusivo).
    with _lote_exclusivo(logger) as livre:
        if not livre:
            return 1
        return _gerar_lote(config, logger)


def _gerar_lote(config: dict, logger) -> int:
    t0 = time.time()                      # cronômetro: tempo total de geração do lote
    target = _target()
    # A empresa dona do lote é OBRIGATÓRIA. Sem ela não há memória de domínios,
    # cota nem dono — e um lote sem empresa seria um vazamento esperando acontecer.
    org_id = os.environ.get("ORG_ID", "").strip()
    if not org_id:
        logger.error("ORG_ID ausente: o lote precisa saber de qual empresa é.")
        return 2
    # Filtro OPCIONAL por macro-região (a API passa via PROSPECT_REGION). Vazio = Brasil inteiro.
    region = os.environ.get("PROSPECT_REGION", "").strip() or WORLD
    # SÓ COM CONTATO: um lead sem NENHUM canal (e-mail, telefone ou LinkedIn) não
    # serve para trabalhar — não conta para o alvo.
    require_contact = os.environ.get("PROSPECT_REQUIRE_CONTACT", "").strip() == "1"
    region_on = is_region(region)
    # "Brasil inteiro" também é uma região (mantém o portão de país ligado). Mas o
    # caminho CARO — mais rodadas, mais tempo, pool 2x — é só para filtro ESTREITO
    # de macro-região, onde boa parte do que a web devolve cai fora.
    region_narrow = region_on and region != WORLD
    region_terms = CONTINENTS[region]["query"] if region_on else None
    # TETO DO PLANO conferido AQUI, onde o lote é gerado de fato. A tela limita o
    # pedido, mas a tela é só uma das portas.
    with db.conn() as c:
        org = orgs_repo.get(c, org_id)
        if not org or not org["active"]:
            logger.error("Empresa %s não existe ou está desativada.", org_id)
            return 2
        _plano, _ate = org["plano"], org["trial_ate"]
        _usados = leads_repo.leads_desde(c, org_id, datetime.now().strftime("%Y-%m-01"))
        already = leads_repo.dominios_vistos(c, org_id)
    _teto_clique = limite_plano(_plano, "leads_clique", _ate)
    if target > _teto_clique:
        logger.warning("O plano %s traz até %d empresa(s) por clique; o pedido de %d foi "
                       "reduzido para %d.", nome_plano(_plano, _ate), _teto_clique, target,
                       _teto_clique)
        target = _teto_clique
    _cota_mes = limite_plano(_plano, "leads_mes", _ate)
    if not plano_ilimitado(_cota_mes):
        _resta = max(0, _cota_mes - _usados)
        if _resta <= 0:
            logger.error("COTA DO MÊS ESGOTADA: o plano %s dá %d lead(s) por mês e a empresa já "
                         "gerou %d. Mude de plano ou aguarde o próximo mês.",
                         nome_plano(_plano, _ate), _cota_mes, _usados)
            return 0
        if target > _resta:
            logger.warning("Restam %d lead(s) na cota do mês (plano %s: %d); o pedido de %d foi "
                           "reduzido.", _resta, nome_plano(_plano, _ate), _cota_mes, target)
            target = _resta
    logger.info("DESCOBERTA (%s): alvo de %d empresa(s) nova(s)%s. Memória tem %d já vista(s).",
                _nicho.ativo().nome, target,
                f" · região: {region}" if region_narrow else " · Brasil inteiro", len(already))

    search_cfg = config["search"]
    engine = SearchEngine(
        max_results=search_cfg["max_results"], region=search_cfg["region"],
        safesearch=search_cfg["safesearch"], pause_seconds=search_cfg["pause_seconds"],
        max_retries=min(2, search_cfg["max_retries"]),
        query_workers=search_cfg.get("query_workers", 1), logger=logger,
    )
    per_round = max(QUERIES_PER_RUN, min(30, -(-target // 8)))    # mais fontes para alvos maiores
    max_rounds = max(12, -(-target // 8) + 6)                     # rodadas suficientes p/ alvos grandes
    # GARANTIA DE ENTREGA: junta ~alvo+folga e enriquece TODOS (nenhum
    # descartado), entregando os melhores N. RÁPIDO: sem filtro junta pouco mais que o alvo;
    # ao filtrar região, parte cai fora do continente -> junta um pouco mais (mais tempo/rodadas).
    gb = float(search_cfg.get("gather_budget_seconds", 0) or 0)
    if gb > 0:
        gather_budget = gb
    elif region_narrow:
        gather_budget = max(110.0, target * 2.0)   # macro-região rende menos por rodada
    else:
        gather_budget = max(35.0, target * 0.9)    # Brasil inteiro: quase tudo serve
    if region_narrow:
        per_round = max(per_round, 20)              # mais buscas por rodada (mais fontes da região)
        max_rounds = max(max_rounds, 40)            # mais rodadas p/ fechar o alvo na região
    else:
        per_round = max(per_round, 14)              # 7 motores por query -> menos rodadas bastam
    dry_limit = 10 if region_narrow else 4          # 4 rodadas secas já indicam pool esgotado
    t_gather = time.time()

    # PIPELINE: cada candidato inédito é enriquecido ASSIM QUE descoberto, em paralelo às
    # próximas rodadas. _process_one SEMPRE devolve um lead (nunca None) -> garante a entrega.
    enrich_ex = ThreadPoolExecutor(max_workers=config["enrichment"]["max_workers"])
    futures: list = []
    seen_now: set[str] = set()
    # Folga: na região, pool LEVE maior (alguns viram "outro continente" só no profundo,
    # então precisa de reserva p/ re-aplicar o portão e ainda fechar o alvo).
    goal = target + (max(10, target) if region_narrow else max(6, target // 3))
    if require_contact:
        goal = max(goal, int(target * 1.7))   # parte não publica contato -> garimpa mais
    # Teto de DESPACHO: sem filtro quase todo candidato vale -> pouco acima da meta. Ao filtrar
    # região, parte cai fora do continente -> despacha mais p/ ainda juntar a meta.
    dispatch_cap = (goal * 5 + 20) if region_narrow else (goal * 2 + 16)

    def _kept() -> int:
        """Candidatos JÁ terminados que valem p/ a região (todos os níveis — fortes e fracos)."""
        n = 0
        for f in futures:
            if f.done():
                try:
                    r = f.result()
                    if r is not None and keep_for_region(r.country, region):
                        n += 1
                except Exception:  # noqa: BLE001
                    pass
        return n

    dry = 0
    for rnd in range(1, max_rounds + 1):
        if _kept() >= goal or len(futures) >= dispatch_cap:
            break
        if time.time() - t_gather > gather_budget:
            logger.info("Busca atingiu o teto de %.0fs; completando pela base curada.", gather_budget)
            break
        raw = engine.search_many(_rotating_queries(per_round, region_terms))
        kept, _d = filter_blacklist(deduplicate(raw, logger=logger), config["blacklist"], logger=logger)
        added = 0
        for lead in kept:
            if len(futures) >= dispatch_cap:    # já despachou o suficiente p/ a meta
                break
            d = normalize_domain(lead.website)
            if not d or d in already or d in seen_now or not _is_relevant(lead, d):
                continue
            if region_on:                       # ccTLD de OUTRO continente -> pula SEM enriquecer (rápido)
                _cc = detect_country(d, "")
                if _cc and not keep_for_region(_cc, region):
                    seen_now.add(d)
                    continue
            seen_now.add(d)
            futures.append(enrich_ex.submit(_process_one, lead, config, logger))   # enriquece já, em paralelo
            added += 1
        logger.info("Rodada %d: +%d candidato(s); %d válido(s) p/ entrega (meta %d).",
                    rnd, added, _kept(), goal)
        dry = dry + 1 if added == 0 else 0
        if dry >= dry_limit:                    # rodadas secas seguidas -> web esgotou
            break

    # Coleta o enriquecimento (rodou em paralelo à busca); mantém só WARM/HOT.
    logger.info("Coletando enriquecimento de %d candidato(s)...", len(futures))
    quality: list = []
    failures, first_error = 0, ""
    # PISO DE ENTREGA: preferimos entregar MENOS a completar a cota com encaixe fraco.
    piso_score = int(_nicho.ativo().warm)
    fracos = 0
    for fut in futures:
        try:
            r = fut.result()
        except Exception as error:  # noqa: BLE001 - um lead que falhou não derruba o lote
            failures += 1
            first_error = first_error or f"{type(error).__name__}: {error}"[:160]
            logger.debug("Falha ao enriquecer um lead: %s", str(error)[:120])
            continue
        if r is not None and keep_for_region(r.country, region):
            if _vale_entregar(r, piso_score):
                quality.append(r)
            else:
                fracos += 1
    enrich_ex.shutdown(wait=True)
    _warn_if_systemic(failures, len(futures), first_error, logger)
    if fracos:
        logger.info("Descartadas %d empresa(s) por encaixe fraco (nota < %d, sem porte "
                    "declarado suficiente nem porte Grande) — o lote entrega menos, e melhor.",
                    fracos, piso_score)

    # Completa pela base curada se ainda faltar p/ o ALVO. A base é BRASILEIRA, então só
    # vale quando a região INCLUI o Brasil (Mundo / Brasil / América do Sul).
    allow_seeds = (not region_on) or "Brazil" in CONTINENTS[region]["countries"]
    if len(quality) < target and allow_seeds:
        pool = [d for d in _read_seeds() if d not in already and normalize_domain(d) not in seen_now]
        random.shuffle(pool)
        # Folga generosa: parte dos domínios da base não responde (site fora do ar,
        # bloqueio, timeout). Pedir só o que falta fazia o lote sair curto sempre que
        # um deles falhava. Pede o dobro, limitado ao que existe.
        need = min(len(pool), (target - len(quality)) * 2 + 8)
        seeds = [Lead(company=company_name_from_domain(d), website="https://" + d,
                      search_keyword="base curada", title="", description="") for d in pool[:need]]
        if seeds:
            with ThreadPoolExecutor(max_workers=config["enrichment"]["max_workers"]) as _sx:
                enriched = list(_sx.map(lambda l: _process_one(l, config, logger), seeds))
            quality.extend([r for r in enriched if r is not None
                            and keep_for_region(r.country, region)
                            and _vale_entregar(r, piso_score)])
            logger.info("Completado com %d empresa(s) da base curada.", len(seeds))

    if not quality:
        logger.warning("Nenhuma empresa nova encontrada (web bloqueada e base esgotada).")
        return 0

    # ENTREGA (melhores primeiro, fracos como preenchimento): confirmados na região ->
    # classe (HOT>WARM>COLD) -> completude -> score. Corta no ALVO. As empresas mais
    # fracas (material mais barato) só ficam de fora se houver fortes suficientes.
    _rank = {"HOT": 2, "WARM": 1, "COLD": 0}

    def _completeness(h) -> int:
        return bool(h.solutions) + bool(h.phone) + bool(h.email) + bool(getattr(h, "city", ""))

    def _porte_peso(h) -> int:
        """Porte maior primeiro: empresa grande e pequena são negócios diferentes."""
        n = int(getattr(h, "porte_numero", 0) or 0)
        pc = _nicho.ativo().porte
        if n >= pc.grande_a_partir_de:
            return 3
        if n >= pc.media_a_partir_de:
            return 2
        if n:
            return 1
        return {"Grande": 3, "Média": 2, "Pequena": 1}.get(getattr(h, "porte", ""), 0)

    def _sort_key(h):
        return (in_region_confirmed(h.country, region), _rank.get(h.classification, 0),
                _porte_peso(h), _completeness(h), h.score)

    quality.sort(key=_sort_key, reverse=True)

    # ENRIQUECIMENTO PROFUNDO só nos entregues (páginas internas + contato dos HOT) — o
    # filtro/ranking acima foi LEVE (rápido). CRÍTICO: o profundo re-detecta o país (mais
    # preciso) -> RE-APLICA o portão de região no país profundo, em LOTES, até fechar o
    # alvo só com a região certa. Assim NUNCA entra outro continente que só apareceu agora.
    def _to_lead(h):
        ld = Lead(company=h.company, website=h.website, search_keyword="", title="", description="")
        ld.score, ld.classification, ld.keywords_found = h.score, h.classification, list(h.keywords_found or [])
        return ld

    def _n_region(items) -> int:
        return sum(1 for h in items if keep_for_region(h.country, region))

    deep_all: list = []
    _i = 0
    # Aprofunda em lotes ATÉ ter o alvo DA REGIÃO (ou esgotar o pool). Não descarta no
    # caminho — o portão de região é aplicado na SELEÇÃO, garantindo o número exato.
    while _i < len(quality) and _n_region(deep_all) < target:
        _need = (target - _n_region(deep_all)) + 6
        _batch = quality[_i: _i + _need]
        _i += len(_batch)
        logger.info("Aprofundando lote de %d (na região: %d/%d)...", len(_batch), _n_region(deep_all), target)
        with ThreadPoolExecutor(max_workers=config["enrichment"]["max_workers"]) as _dx:
            _futs = [_dx.submit(_process_lead, _to_lead(h), config, logger, True) for h in _batch]
        _deep, _fail, _err = [], 0, ""
        for _f, _shallow in zip(_futs, _batch):
            try:
                _deep.append(_f.result())
            except Exception as error:  # noqa: BLE001 - um lead ruim não derruba a fase
                _fail += 1
                _err = _err or f"{type(error).__name__}: {error}"[:160]
                _deep.append(_shallow)          # mantém a versão rasa em vez de perder o lead
        _warn_if_systemic(_fail, len(_batch), _err, logger, fase="aprofundamento")
        deep_all.extend([h for h in _deep if h is not None])
    deep_all.sort(key=_sort_key, reverse=True)
    # SELEÇÃO: primeiro quem é DA região (país confirmado OU indeterminado). Se a web não
    # rendeu o alvo na região, completa EXATAMENTE o número com os melhores restantes
    # (ranqueados por baixo) — assim o lote SEMPRE entrega a quantidade pedida, com qualidade.
    in_reg = [h for h in deep_all if keep_for_region(h.country, region)]
    if require_contact:
        in_reg = [h for h in in_reg if (h.email or h.phone or h.linkedin)]
    results = in_reg[:target]
    if len(results) < target and not require_contact:
        _have = {h.website for h in results}
        extra = [h for h in deep_all if h.website not in _have]
        results.extend(extra[:target - len(results)])
        if region_on and len(in_reg) < target:
            logger.info("Região %s: web rendeu %d na região; completei o alvo com %d de melhor encaixe.",
                        region, len(in_reg), len(results) - len(in_reg))
    results = results[:target]
    web_found = len(results)
    # ENTREGA vs PEDIDO — explícito. Entregar 40 quando se pediu 150 e não dizer nada
    # deixa o usuário achando que o mercado acabou, quando o que acabou foi o pool:
    # a memória já viu tudo, ou a busca aberta está bloqueada (IP de datacenter).
    if len(results) < target:
        _motivo = ("só entram empresas COM canal de contato e não havia tantas assim; "
                   "desmarque 'Só empresas com contato' para completar o número"
                   if require_contact else
                   "pool esgotado (a memória já viu %d domínio(s)) ou busca aberta "
                   "bloqueada" % len(already))
        logger.error("ENTREGA INCOMPLETA: %d de %d pedidos — %s.",
                     len(results), target, _motivo)
    else:
        logger.info("Entrega completa: %d de %d pedidos.", len(results), target)
    _com_email = sum(1 for h in results if h.email)
    _com_fone = sum(1 for h in results if h.phone)
    _com_li = sum(1 for h in results if h.linkedin)
    _com_algum = sum(1 for h in results if h.email or h.phone or h.linkedin)
    _completos = sum(1 for h in results if h.email and h.phone and h.solutions)
    if results:
        n = len(results)
        _com_porte = sum(1 for h in results if h.porte_numero or h.porte)
        _decl = [h.porte_numero for h in results if h.porte_numero]
        logger.info("Porte identificado: %d/%d | declarado em %d (maior: %d).",
                    _com_porte, len(results), len(_decl), max(_decl) if _decl else 0)
        logger.info("Completude: %d/%d com CONTATO (e-mail %d · telefone %d · LinkedIn %d) "
                    "| %d/%d com e-mail+telefone+necessidade.",
                    _com_algum, n, _com_email, _com_fone, _com_li, _completos, n)
    if region_on:
        _conf = sum(1 for h in results if in_region_confirmed(h.country, region))
        logger.info("Região %s: %d de %d com país confirmado no continente (demais: país indeterminado).",
                    region, _conf, len(results))

    # Id do lote (carimbo de data). Único dentro da empresa: um lote por vez.
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    elapsed = time.time() - t0
    device = os.environ.get("PROSPECT_DEVICE", "").strip() or "Computador"
    region_label = region if region_on else WORLD
    owner_id = os.environ.get("OWNER_ID", "").strip()
    try:
        with db.conn() as c:
            gravados = leads_repo.gravar(c, org_id, results,
                                         now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                         lote=stamp, gen_seconds=elapsed, device=device,
                                         region=region_label, owner_id=owner_id)
    except Exception as error:  # noqa: BLE001
        logger.error("Falha ao gravar o lote no banco: %s", error)
        return 3

    hot = sum(1 for h in results if h.classification == "HOT")
    logger.info("=" * 60)
    logger.info("LOTE NOVO PRONTO: %d empresas (%d HOT) — %d da web.", gravados, hot,
                min(web_found, len(results)))
    logger.info("Com e-mail: %d | Com telefone: %d | Com necessidade: %d",
                sum(1 for h in results if h.email), sum(1 for h in results if h.phone),
                sum(1 for h in results if h.solutions))
    per = elapsed / len(results) if results else 0
    logger.info("Tempo de geração: %s (%.1f s/empresa)", _fmt_duration(elapsed), per)
    # Linha lida pela API (api/jobs.py) para ligar o job ao lote. Não mude o formato.
    logger.info("LOTE_ID: %s", stamp)
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
