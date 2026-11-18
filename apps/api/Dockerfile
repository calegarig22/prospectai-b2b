# Imagem da API do ProspectAI (Container na Cloudflare).
# Contexto de build = apps/api. Só entra o que a API e o motor usam (ver .dockerignore).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Sao_Paulo \
    APP_ENV=production

RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY app ./app
COPY api ./api
COPY config ./config
COPY migrations ./migrations
COPY discover.py .

# Usuário sem privilégio; o motor só escreve em pastas de trabalho temporárias.
RUN mkdir -p data exports logs \
 && useradd --system --uid 10001 --home /srv prospect \
 && chown -R prospect /srv
USER prospect

EXPOSE 8000
# O container só recebe tráfego do Worker da Cloudflare (proxy confiável).
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
