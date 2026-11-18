"""API do ProspectAI (multiempresa) — ponto de entrada.

Rodar local (a partir de apps/api):
    .venv/bin/python -m api.migrate
    .venv/bin/uvicorn api.main:app --reload --port 8000

Documentação interativa: http://localhost:8000/docs (só fora de produção).
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

# Datas e horários no fuso de Brasília, como no painel (o servidor roda em UTC).
os.environ["TZ"] = "America/Sao_Paulo"
try:
    time.tzset()
except AttributeError:
    pass

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import db

from . import jobs, migrate
from .routers import admin, auth, jobs_email, leads, plataforma
from .security import csrf_guard
from .settings import load_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(message)s")
log = logging.getLogger("prospectai.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = app.state.settings
    applied, pending = migrate.status()
    if pending:
        if settings.production:
            # Em produção o schema só muda pelo pipeline (python -m api.migrate).
            # Subir com schema velho quebraria no meio de uma requisição.
            raise RuntimeError(f"Migrations pendentes: {', '.join(pending)}. "
                               "Rode `python -m api.migrate` antes do deploy.")
        log.warning("Aplicando migrations pendentes no banco local: %s", ", ".join(pending))
        migrate.apply_pending(log.info)
    n = jobs.recover_interrupted()
    if n:
        log.warning("%d tarefa(s) interrompida(s) pelo reinício foram marcadas como erro.", n)
    yield
    db.close_pool()


def create_app() -> FastAPI:
    settings = load_settings()
    app = FastAPI(
        title="ProspectAI API",
        version="1.0.0",
        lifespan=lifespan,
        dependencies=[Depends(csrf_guard)],
        docs_url=None if settings.production else "/docs",
        redoc_url=None,
        openapi_url=None if settings.production else "/openapi.json",
    )
    app.state.settings = settings

    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                           allow_credentials=True, allow_methods=["GET", "POST", "PUT",
                                                                  "PATCH", "DELETE"],
                           allow_headers=["content-type", "x-requested-with"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(Exception)
    async def erro_inesperado(request: Request, exc: Exception):
        # Nunca devolve stack trace nem mensagem interna ao cliente.
        log.exception("Erro não tratado em %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "Erro interno. Tente novamente em instantes."},
                            status_code=500)

    @app.get("/health", tags=["infra"])
    def health():
        # "ocupado" é lido pelo Worker da Cloudflare antes de desligar o container.
        return {"ok": True, "db": "postgres" if db.is_postgres() else "sqlite",
                "ocupado": jobs.ocupado()}

    for r in (auth.router, leads.router, jobs_email.router, admin.router, plataforma.router):
        app.include_router(r)
    return app


app = create_app()
