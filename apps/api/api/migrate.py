"""Aplica as migrations versionadas de ``migrations/`` — a ÚNICA porta de mudança no banco.

Uso:
    python -m api.migrate            aplica as pendentes
    python -m api.migrate --status   só lista (não muda nada; sai com 1 se houver pendente)

Regras:
- Cada arquivo ``NNNN_nome.sql`` roda uma vez, em ordem, numa transação.
- O registro fica em ``schema_migrations`` com o checksum do arquivo.
  Editar uma migration JÁ aplicada é erro: a mudança precisa de um arquivo novo.
- No Postgres, um advisory lock impede dois deploys de migrarem ao mesmo tempo.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import datetime
from pathlib import Path

from app import db

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
TABLE = "schema_migrations"
_LOCK_KEY = 74_201_687          # número arbitrário e fixo do advisory lock
_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class MigrationError(RuntimeError):
    pass


def _files() -> list[tuple[str, Path, str]]:
    out = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        if not _NAME.match(path.name):
            raise MigrationError(f"Nome fora do padrão NNNN_nome.sql: {path.name}")
        text = path.read_text(encoding="utf-8")
        out.append((path.stem, path, hashlib.sha256(text.encode()).hexdigest()))
    versions = [v.split("_", 1)[0] for v, _, _ in out]
    if len(versions) != len(set(versions)):
        raise MigrationError("Dois arquivos de migration com o mesmo número.")
    return out


def _statements(sql: str) -> list[str]:
    """Separa por ';' no fim da linha, ignorando comentários. As migrations deste
    projeto não usam funções/procedures, então isso basta e é previsível."""
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    parts = re.split(r";\s*$", "\n".join(lines), flags=re.MULTILINE)
    return [p.strip() for p in parts if p.strip()]


def _ensure_table(c: db.Conn) -> None:
    c.run(f"CREATE TABLE IF NOT EXISTS {TABLE} "
          "(version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)")


def _applied(c: db.Conn) -> dict[str, str]:
    return {v: chk for v, chk in c.all(f"SELECT version, checksum FROM {TABLE}")}


def status() -> tuple[list[str], list[str]]:
    """(aplicadas, pendentes). Só LÊ o banco — sem a tabela de controle, tudo está
    pendente. Levanta MigrationError se alguma aplicada foi editada."""
    with db.conn() as c:
        try:
            applied = _applied(c)
        except Exception:  # noqa: BLE001 - banco que nunca foi migrado
            applied = {}
    pending = []
    for version, _path, checksum in _files():
        if version in applied:
            if applied[version] != checksum:
                raise MigrationError(
                    f"A migration {version} foi editada depois de aplicada. "
                    "Crie um arquivo novo em vez de mudar um antigo.")
        else:
            pending.append(version)
    return sorted(applied), pending


def apply_pending(log=print) -> list[str]:
    done: list[str] = []
    with db.conn() as c:
        if c.pg:
            c.raw.autocommit = True
            c.run("SELECT pg_advisory_lock(%s)", (_LOCK_KEY,))
        try:
            _ensure_table(c)
            applied = _applied(c)
            for version, path, checksum in _files():
                if version in applied:
                    if applied[version] != checksum:
                        raise MigrationError(
                            f"A migration {version} foi editada depois de aplicada.")
                    continue
                log(f"Aplicando {path.name}…")
                _apply_one(c, path.read_text(encoding="utf-8"), version, checksum)
                done.append(version)
        finally:
            if c.pg:
                c.run("SELECT pg_advisory_unlock(%s)", (_LOCK_KEY,))
    return done


def _apply_one(c: db.Conn, sql: str, version: str, checksum: str) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    record = (f"INSERT INTO {TABLE} (version, checksum, applied_at) "
              f"VALUES ({c.ph}, {c.ph}, {c.ph})")
    if c.pg:
        c.raw.autocommit = False
        try:
            with c.raw.cursor() as cur:
                for stmt in _statements(sql):
                    cur.execute(stmt)
                cur.execute(record, (version, checksum, now))
            c.raw.commit()
        except Exception:
            c.raw.rollback()
            raise
        finally:
            c.raw.autocommit = True
        return
    try:
        c.raw.execute("BEGIN")
        for stmt in _statements(sql):
            c.raw.execute(stmt)
        c.raw.execute(record, (version, checksum, now))
        c.raw.commit()
    except Exception:
        c.raw.rollback()
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--status", action="store_true", help="só lista, não aplica")
    args = parser.parse_args(argv)
    alvo = "Postgres (DATABASE_URL)" if db.is_postgres() else f"SQLite ({db.SQLITE_PATH})"
    print(f"Banco: {alvo}")
    try:
        if args.status:
            applied, pending = status()
            print(f"Aplicadas: {', '.join(applied) or '—'}")
            print(f"Pendentes: {', '.join(pending) or '—'}")
            return 1 if pending else 0
        done = apply_pending()
        print(f"OK — {len(done)} migration(s) aplicada(s)." if done else "Nada pendente.")
        return 0
    except MigrationError as erro:
        print(f"ERRO: {erro}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
