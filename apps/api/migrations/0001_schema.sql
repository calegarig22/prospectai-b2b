-- 0001 — schema multiempresa (multi-tenant) do ProspectAI.
--
-- REGRA DE ISOLAMENTO: toda tabela com dado de cliente tem org_id NOT NULL e
-- toda consulta da aplicação filtra por ele. Não existe "empresa padrão": um
-- registro sem empresa simplesmente não pode ser gravado.
-- SQL portável: roda igual em Postgres e SQLite.

-- Empresas clientes (tenants). A empresa 'plataforma' é a do dono do sistema
-- (superadmin): não tem nicho nem leads, só administra as outras.
CREATE TABLE IF NOT EXISTS orgs (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    plano       TEXT NOT NULL DEFAULT 'essencial',
    trial_ate   TEXT,
    nicho       TEXT,                 -- JSON: o que buscar, pontuar e oferecer (app/nicho.py)
    marca       TEXT                  -- JSON: nome de exibição, cor, logo
);

CREATE TABLE IF NOT EXISTS users (
    id             TEXT PRIMARY KEY,
    org_id         TEXT NOT NULL REFERENCES orgs (id),
    email          TEXT NOT NULL UNIQUE,   -- login: um e-mail pertence a UMA empresa
    name           TEXT,
    role           TEXT NOT NULL,          -- superadmin | admin | vendedor
    password_hash  TEXT NOT NULL,
    active         INTEGER NOT NULL DEFAULT 1,
    created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS users_org_idx ON users (org_id);

CREATE TABLE IF NOT EXISTS password_resets (
    user_id     TEXT PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    code_hash   TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS login_attempts (
    email         TEXT PRIMARY KEY,
    fails         INTEGER NOT NULL DEFAULT 0,
    locked_until  TEXT
);

-- A mesma empresa-lead pode existir para várias empresas clientes: é dado
-- público, e o funil de uma não pode ser furado pelo da outra.
CREATE TABLE IF NOT EXISTS leads (
    org_id        TEXT NOT NULL REFERENCES orgs (id),
    website       TEXT NOT NULL,
    company       TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    score         INTEGER,
    lote          TEXT NOT NULL,
    payload       TEXT,               -- JSON com as colunas do lead
    gen_seconds   REAL,
    device        TEXT,
    region        TEXT,
    owner_id      TEXT,               -- quem trabalha o lead agora
    generated_by  TEXT,               -- quem gerou (não muda)
    PRIMARY KEY (org_id, website)
);
CREATE INDEX IF NOT EXISTS leads_org_lote_idx ON leads (org_id, lote);
CREATE INDEX IF NOT EXISTS leads_org_owner_idx ON leads (org_id, owner_id);

-- E-mails já enviados: dedupe e cota diária POR EMPRESA (a mesma pessoa pode
-- ser contatada por duas empresas clientes diferentes).
CREATE TABLE IF NOT EXISTS sent_emails (
    org_id   TEXT NOT NULL REFERENCES orgs (id),
    email    TEXT NOT NULL,
    sent_at  TEXT NOT NULL,
    sender   TEXT,
    PRIMARY KEY (org_id, email)
);

-- Remetente de cada vendedor (senha de app cifrada com Fernet).
CREATE TABLE IF NOT EXISTS email_senders (
    user_id            TEXT PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    org_id             TEXT NOT NULL REFERENCES orgs (id),
    from_name          TEXT,
    from_email         TEXT NOT NULL,
    smtp_host          TEXT NOT NULL,
    smtp_port          INTEGER NOT NULL,
    smtp_user          TEXT NOT NULL,
    smtp_password_enc  TEXT NOT NULL,
    reply_to           TEXT,
    updated_at         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS email_senders_org_idx ON email_senders (org_id);

-- Preferências por empresa (ex.: template de e-mail de cada usuário).
CREATE TABLE IF NOT EXISTS app_settings (
    org_id      TEXT NOT NULL REFERENCES orgs (id),
    key         TEXT NOT NULL,
    value       TEXT,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (org_id, key)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id         TEXT PRIMARY KEY,
    org_id     TEXT NOT NULL REFERENCES orgs (id),
    ts         TEXT NOT NULL,
    user_id    TEXT,
    user_name  TEXT,
    action     TEXT NOT NULL,
    detail     TEXT
);
CREATE INDEX IF NOT EXISTS audit_org_ts_idx ON audit_log (org_id, ts);

-- Tarefas longas (gerar lote, disparar e-mails). A requisição só cria a linha;
-- uma thread executa e grava o progresso aqui.
CREATE TABLE IF NOT EXISTS jobs (
    id           TEXT PRIMARY KEY,
    org_id       TEXT NOT NULL REFERENCES orgs (id),
    user_id      TEXT NOT NULL,
    kind         TEXT NOT NULL,       -- discover | email
    status       TEXT NOT NULL,       -- queued | running | done | error
    params       TEXT,
    progress     TEXT,
    result       TEXT,
    error        TEXT,
    created_at   TEXT NOT NULL,
    started_at   TEXT,
    finished_at  TEXT
);
CREATE INDEX IF NOT EXISTS jobs_user_idx ON jobs (user_id, created_at);
CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs (status);
