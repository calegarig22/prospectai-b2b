# Publicar (Neon · Cloudflare · Vercel)

```
GitHub (main) ──► GitHub Actions: testes → migrations no Neon → deploy na Cloudflare (API)
              └─► Vercel: publica o front sozinha (Root Directory = apps/web)
```

Nada é publicado à mão: tudo sai do merge na `main`. Senha nenhuma vai para o
código — cada segredo é cadastrado na tela da plataforma onde ele é usado.

## 1. Neon (banco) — uma vez

1. Na sua conta Neon: **New Project** → nome `prospectai`, região **AWS São Paulo
   (sa-east-1)**. É um banco **só do ProspectAI** — nunca o de outro produto.
2. Em **Connect**, copie a *connection string* **direta** (sem `-pooler` no
   endereço). Ela é o `DATABASE_URL`.

## 2. Cloudflare (API) — uma vez

1. Plano **Workers Paid** (os Containers exigem).
2. Anote o **Account ID** (aparece na lateral da página inicial da conta).
3. **My Profile → API Tokens → Create Token** → modelo **Edit Cloudflare
   Workers**. Se o primeiro deploy reclamar de permissão de Containers,
   edite o token e acrescente a permissão de Containers.

## 3. GitHub (segredos do deploy) — uma vez

No repositório: **Settings → Environments → New environment** → `producao`.
Dentro dele, em **Environment secrets**, cadastre:

| Nome | Valor |
|---|---|
| `DATABASE_URL` | a connection string do passo 1 |
| `CLOUDFLARE_API_TOKEN` | o token do passo 2 |
| `CLOUDFLARE_ACCOUNT_ID` | o Account ID do passo 2 |

## 4. Primeiro deploy da API

Faça o merge do Pull Request na `main`. Em **Actions → Deploy da API**, os três
passos devem ficar verdes. O endereço da API aparece no fim do log do deploy
(`https://prospectai-api.<seu-subdominio>.workers.dev`).

## 5. Segredos da API (na Cloudflare) — uma vez

**Workers & Pages → prospectai-api → Settings → Variables and Secrets → Add**,
tipo **Secret**:

| Nome | Como gerar / o que é |
|---|---|
| `DATABASE_URL` | a mesma do passo 1 |
| `JWT_SECRET` | `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `APP_PASSWORD` | senha do time: autoriza criar o dono da plataforma |
| `EMAIL_ENC_KEY` | `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `SMTP_FROM` | e-mail que envia o código de "esqueci a senha" |
| `SMTP_PASSWORD` | senha de app desse e-mail |

(`SMTP_HOST`/`SMTP_PORT` só se não for Gmail.) Até esses segredos existirem a
API não sobe — de propósito: ela se recusa a rodar em produção sem eles.

Teste: abra `https://prospectai-api.<seu-subdominio>.workers.dev/health` →
deve responder `{"ok":true,"db":"postgres",...}`.

## 6. Vercel (front) — uma vez

1. **Add New → Project** → importe o repositório `prospectai`.
2. **Root Directory: `apps/web`** (o resto a Vercel detecta).
3. **Environment Variables:** `API_URL` = o endereço da API do passo 4.
4. **Deploy.** Daqui em diante, cada merge na `main` publica sozinho
   (e o front só é reconstruído quando `apps/web` muda — ver `apps/web/vercel.json`).

## 7. Primeiro acesso

Abra o site da Vercel → informe a senha do time (`APP_PASSWORD`) → crie o dono
da plataforma → siga [NOVO-CLIENTE.md](NOVO-CLIENTE.md).

## Dia a dia

- Mudança no código: branch → Pull Request (o **CI** testa) → merge → publica.
- Mudança no banco: arquivo novo em `apps/api/migrations/` (o deploy aplica
  antes de subir a API; a API não sobe com migration pendente).

## Pontos de atenção

- A busca aberta na web pode ser limitada em IP de datacenter. Se os lotes
  vierem curtos, use a `base_curada` do nicho.
- A API roda numa instância só (`max_instances: 1`, máquina `standard-1`): a
  fila de lotes vive na memória. O container não desliga por inatividade
  enquanto houver lote ou disparo rodando (`/health` → `ocupado`).
