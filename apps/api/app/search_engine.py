"""Mecanismo de busca baseado em DuckDuckGo (biblioteca gratuita ``ddgs``).

Encapsula o acesso à rede para que o restante do pipeline dependa apenas de
uma interface simples: dada uma palavra-chave, devolve uma lista de ``Lead``.
Inclui pausa entre buscas e novas tentativas para reduzir bloqueios.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from ddgs import DDGS

from .models import Lead
from .utils import company_name_from_domain, normalize_domain


class SearchEngine:
    """Wrapper fino sobre o DuckDuckGo Search."""

    def __init__(
        self,
        max_results: int = 20,
        region: str = "wt-wt",
        safesearch: str = "moderate",
        pause_seconds: float = 2.0,
        max_retries: int = 3,
        query_workers: int = 1,
        logger: logging.Logger | None = None,
    ) -> None:
        self.max_results = max_results
        self.region = region
        self.safesearch = safesearch
        self.pause_seconds = pause_seconds
        self.max_retries = max_retries
        # Quantas QUERIES disparar em paralelo (cada query já abre os 3 motores juntos).
        # >1 acelera muito a fase de busca; mantenha moderado p/ não tomar rate-limit.
        self.query_workers = max(1, int(query_workers))
        self.logger = logger or logging.getLogger("prospectai")

    # SETE motores em vez de três. Não é só mais resultado por query: quando um
    # motor toma rate-limit (o DuckDuckGo gratuito toma rápido em uso seguido), a
    # rodada continuava voltando quase vazia e o lote precisava de MAIS rodadas —
    # que é onde o tempo ia embora. Com sete, uma queda não trava a rodada.
    _BACKENDS = ("duckduckgo", "google", "brave", "mojeek", "startpage", "yahoo", "yandex")
    # Teto por motor: um motor lento não pode segurar a rodada inteira. Quem passar
    # disso é abandonado e os outros entregam.
    _BACKEND_TIMEOUT = 9

    def _one_backend(self, keyword: str, backend: str) -> list[dict[str, Any]]:
        """Consulta UM motor. Isolado para rodar os motores EM PARALELO."""
        try:
            with DDGS() as ddgs:
                return list(ddgs.text(keyword, backend=backend, max_results=self.max_results))
        except Exception as error:  # noqa: BLE001 - um motor pode falhar; os outros cobrem
            self.logger.debug("Motor '%s' falhou para '%s': %s", backend, keyword, str(error)[:80])
            return []

    def _raw_search(self, keyword: str) -> list[dict[str, Any]]:
        """Busca em VÁRIOS motores gratuitos (7 motores gratuitos) e mescla os resultados.

        Mais motores = mais empresas e mais cobertura. Se um motor falha/bloqueia,
        os outros cobrem — sem depender de um só. Os motores rodam EM PARALELO
        (cada um recebe só 1 request por query, então não eleva o rate-limit) —
        elimina a espera em série e acelera a fase de busca ~2-3x.
        """
        merged: dict[str, dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=len(self._BACKENDS)) as ex:
            futuros = {ex.submit(self._one_backend, keyword, b): b for b in self._BACKENDS}
            for fut in as_completed(futuros, timeout=self._BACKEND_TIMEOUT + 3):
                try:
                    results = fut.result(timeout=self._BACKEND_TIMEOUT)
                except Exception:  # noqa: BLE001 - motor lento/quebrado: os outros cobrem
                    continue
                for item in results:
                    href = (item.get("href") or "").strip()
                    if href and href not in merged:
                        merged[href] = item
        self.logger.info("'%s' retornou %d resultado(s) (multi-motor).", keyword, len(merged))
        return list(merged.values())

    def search(self, keyword: str) -> list[Lead]:
        """Busca uma palavra-chave e converte os resultados em ``Lead``."""
        self.logger.info("Buscando: %s", keyword)
        raw_results = self._raw_search(keyword)

        leads: list[Lead] = []
        for result in raw_results:
            website = (result.get("href") or "").strip()
            if not website:
                continue

            domain = normalize_domain(website)
            company = company_name_from_domain(domain) or domain or "Desconhecida"

            leads.append(
                Lead(
                    company=company,
                    website=website,
                    search_keyword=keyword,
                    title=(result.get("title") or "").strip(),
                    description=(result.get("body") or "").strip(),
                )
            )

        self.logger.info("'%s' retornou %d resultado(s).", keyword, len(leads))
        return leads

    def search_many(self, keywords: list[str]) -> list[Lead]:
        """Executa a busca para várias palavras-chave.

        Com ``query_workers == 1`` mantém o modo seguro (sequencial, com pausa entre
        buscas). Com ``query_workers > 1`` dispara as queries EM PARALELO — ganho
        grande de tempo na fase de busca (o lever principal para entregas grandes).
        """
        if self.query_workers <= 1:
            all_leads: list[Lead] = []
            for index, keyword in enumerate(keywords):
                all_leads.extend(self.search(keyword))
                if index < len(keywords) - 1:      # pausa entre buscas (anti rate-limit)
                    time.sleep(self.pause_seconds)
            return all_leads

        with ThreadPoolExecutor(max_workers=self.query_workers) as ex:
            batches = ex.map(self.search, keywords)
        all_leads = []
        for batch in batches:
            all_leads.extend(batch)
        return all_leads
