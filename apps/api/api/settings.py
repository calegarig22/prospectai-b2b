"""Configuração da API — tudo vem de variáveis de ambiente, nada fica no código.

Em produção (``APP_ENV=production``) a API se recusa a subir sem os segredos
obrigatórios: melhor falhar no deploy do que rodar com sessão forjável.

Variáveis:
    APP_ENV           development | production (padrão: development)
    DATABASE_URL      Postgres (Neon). Vazio = SQLite local em data/leads.db
    JWT_SECRET        assina o cookie de sessão (>= 32 caracteres)
    APP_PASSWORD      autoriza criar o 1º administrador
    EMAIL_ENC_KEY     chave Fernet que cifra a senha SMTP de cada remetente
    SMTP_FROM / SMTP_PASSWORD / SMTP_HOST / SMTP_PORT / SMTP_USER
                      conta que envia o código de "esqueci a senha"
    CORS_ORIGINS      origens extras liberadas, separadas por vírgula. Vazio é o
                      normal: o front chama a API pelo proxy da Vercel (mesma origem)
    COOKIE_SECURE     1/0 — cookie só em HTTPS (padrão: 1 em produção)
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field

log = logging.getLogger("prospectai.api")

SESSION_HOURS = 8            # janela de inatividade da sessão
SESSION_REFRESH_MIN = 15     # reemite o cookie quando o token passa desta idade


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name, default) or "").strip()


@dataclass(frozen=True)
class Settings:
    env: str
    database_url: str
    jwt_secret: str
    app_password: str
    smtp_from: str
    smtp_password: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    cors_origins: list[str] = field(default_factory=list)
    cookie_secure: bool = True

    @property
    def production(self) -> bool:
        return self.env == "production"


def load_settings() -> Settings:
    env = _env("APP_ENV", "development").lower()
    production = env == "production"

    jwt_secret = _env("JWT_SECRET")
    if len(jwt_secret) < 32:
        if production:
            raise RuntimeError("JWT_SECRET ausente ou curto (mínimo 32 caracteres).")
        # Desenvolvimento: segredo efêmero. As sessões caem a cada reinício, o que
        # é aceitável localmente e impossível de esquecer ligado em produção.
        jwt_secret = secrets.token_urlsafe(48)
        log.warning("JWT_SECRET não definido: usando segredo temporário (só desenvolvimento).")

    database_url = _env("DATABASE_URL")
    if production and not database_url:
        raise RuntimeError("DATABASE_URL é obrigatório em produção.")

    smtp_from = _env("SMTP_FROM")
    cookie_default = "1" if production else "0"
    return Settings(
        env=env,
        database_url=database_url,
        jwt_secret=jwt_secret,
        app_password=_env("APP_PASSWORD"),
        smtp_from=smtp_from,
        smtp_password=_env("SMTP_PASSWORD"),
        smtp_host=_env("SMTP_HOST", "smtp.gmail.com"),
        smtp_port=int(_env("SMTP_PORT", "587") or 587),
        smtp_user=_env("SMTP_USER") or smtp_from,
        cors_origins=[o.strip() for o in _env("CORS_ORIGINS").split(",") if o.strip()],
        cookie_secure=_env("COOKIE_SECURE", cookie_default) == "1",
    )
