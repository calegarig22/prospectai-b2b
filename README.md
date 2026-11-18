# ProspectAI B2B

Plataforma de prospecção B2B multiempresa: uma instância atende várias empresas, cada uma com o seu nicho configurável e dados isolados.

## O que faz
- Gera lotes de leads buscando empresas na web a partir das palavras-chave, regiões e filtros do nicho.
- Visita o site de cada lead, extrai e classifica e-mails (pessoa, caixa geral, comercial, atendimento…) e identifica decisores.
- Calcula uma nota (HOT/WARM/COLD) por sinais de necessidade e sugere as soluções do catálogo da empresa que fazem sentido.
- Enriquece com dados públicos de CNPJ e exporta planilha `.xlsx`.
- Envia e-mails frios por remetente de cada vendedor, com template, blacklist, log de envio e opt-out.
- Três papéis: dono da plataforma (empresas, planos, nicho, marca), admin da empresa (usuários, remetentes) e vendedor.

## Destaques técnicos
- Isolamento multi-tenant: `org_id NOT NULL` em toda tabela de cliente, `org_id` sempre lido da sessão e testes que tentam acessar dados de outra empresa (`tests_api/test_isolamento.py`).
- Nicho como configuração (YAML validado e guardado no banco): o mesmo motor serve setores diferentes sem mudar código.
- Fetcher com proteção contra SSRF (bloqueia IPs privados, loopback e metadados de nuvem) e checagem de domínio/MX antes de enviar e-mail.
- Senhas SMTP dos remetentes cifradas com Fernet; sessão por JWT em cookie httpOnly; rate limit nas rotas de autenticação.
- Front Next.js fala com a API só via proxy `/api/*` (mesma origem); tipos gerados do `/openapi.json`.
- CI no GitHub Actions (ruff, migrations do zero, pytest, typecheck/lint/build) e deploy da API em Cloudflare Containers.

## Stack
Python 3.12 · FastAPI · Uvicorn · PyJWT · BeautifulSoup/lxml · ddgs · openpyxl · Postgres (Neon) ou SQLite local · Next.js 16 · React 19 · TypeScript · Cloudflare Workers/Containers · Vercel

## Como rodar
Precisa de Python 3.12 e Node 20+.

```bash
# API (terminal 1)
cd apps/api
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env            # preencha APP_PASSWORD e JWT_SECRET
set -a; . ./.env; set +a
.venv/bin/uvicorn api.main:app --port 8000   # sem DATABASE_URL usa SQLite local

# Front (terminal 2)
cd apps/web
npm install
cp .env.example .env.local
npm run dev                     # http://localhost:3000
```

No primeiro acesso a tela pede a senha do time (`APP_PASSWORD`) e cria o dono da plataforma.

Testes: `cd apps/api && .venv/bin/python -m pytest tests_api -q` e `.venv/bin/python tests/test_contatos.py`.

## Estrutura
```
apps/api/
  api/          FastAPI: rotas (auth, leads, e-mail, admin, plataforma), sessão, fila de lotes
  app/          motor: busca, fetcher, contatos, decisor, pontuação, enriquecimento, e-mail
  config/       config técnica do motor, nicho de exemplo (fictício) e templates de e-mail
  migrations/   schema SQL versionado (python -m api.migrate)
  cloudflare/   Worker que sobe a API como Container
apps/web/       Next.js: login, painel, e-mails, admin, plataforma
docs/           guias: configurar nicho, nova empresa, publicação
```
