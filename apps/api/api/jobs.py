"""Fila de tarefas longas: gerar lote (discover.py) e disparar e-mails.

Por que fila: um lote leva minutos. A requisição só registra o pedido em
``jobs`` e responde; uma thread executa e grava o progresso; o front
consulta ``GET /jobs/{id}`` até terminar. Se o servidor reiniciar no meio, o
job fica marcado como interrompido (nunca "rodando" para sempre).

Concorrência:
- Gerar lote: UM por vez na instalação inteira (a busca na web é o recurso
  compartilhado entre as empresas). Os demais esperam como "na fila".

Isolamento: cada lote roda num PROCESSO próprio, com ORG_ID da empresa e o
NICHO dela num arquivo temporário só daquele processo — o motor não tem como
enxergar outra empresa.
- E-mail: um disparo por usuário por vez (a cota é por remetente).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, status

from app import db, orgs
from app.device import classify_device
from app.nicho import ENV_FILE as NICHO_ENV, NichoInvalido

from . import email_service
from .plan import PlanCtx
from .security import Ctx

log = logging.getLogger("prospectai.api")
TABLE = "jobs"
ROOT = db.ROOT
DISCOVER_TIMEOUT_S = 45 * 60
# Comando do motor. Os testes trocam por um script falso.
DISCOVER_CMD = [sys.executable, str(ROOT / "discover.py")]

_discover_lock = threading.Lock()
_email_locks: dict[str, threading.Lock] = {}
_email_locks_guard = threading.Lock()

_STAMP_RE = re.compile(r"LOTE_ID: (\d{4}-\d{2}-\d{2}_\d{6})")
_PATH_RE = re.compile(r"/(?:mount|home|Users|private|tmp|var|app|srv|opt)/[^\s:'\"]+")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clean(line: str) -> str:
    """Tira o prefixo do log e caminhos do servidor antes de mostrar na tela."""
    msg = line.rsplit("| ", 1)[-1].strip()
    return _PATH_RE.sub("…", msg.replace(str(ROOT) + os.sep, ""))[:300]


# --------------------------------------------------------------- repositório
def _row_to_dict(r) -> dict:
    def _j(v):
        try:
            return json.loads(v) if v else None
        except ValueError:
            return None
    return {"id": r[0], "kind": r[1], "status": r[2], "params": _j(r[3]) or {},
            "progress": r[4] or "", "result": _j(r[5]), "error": r[6] or "",
            "created_at": r[7] or "", "started_at": r[8] or "", "finished_at": r[9] or "",
            "user_id": r[10], "org_id": r[11]}


_COLS = ("id, kind, status, params, progress, result, error, created_at, started_at, "
         "finished_at, user_id, org_id")


def _create(ctx: Ctx, kind: str, params: dict) -> dict:
    jid = uuid.uuid4().hex
    with db.conn() as c:
        c.run(f"INSERT INTO {TABLE} (id, org_id, user_id, kind, status, params, progress, "
              f"created_at) VALUES ({', '.join([c.ph] * 8)})",
              (jid, ctx.org_id, ctx.id, kind, "queued", json.dumps(params, ensure_ascii=False),
               "Na fila…", _now()))
    return get_raw(jid)


def get_raw(job_id: str) -> dict | None:
    with db.conn() as c:
        r = c.one(f"SELECT {_COLS} FROM {TABLE} WHERE id = {c.ph}", (job_id,))
    return _row_to_dict(r) if r else None


def _update(job_id: str, **fields) -> None:
    if not fields:
        return
    with db.conn() as c:
        sets = ", ".join(f"{k} = {c.ph}" for k in fields)
        vals = tuple(json.dumps(v, ensure_ascii=False) if k in ("result", "params") else v
                     for k, v in fields.items())
        c.run(f"UPDATE {TABLE} SET {sets} WHERE id = {c.ph}", vals + (job_id,))


def get_for(ctx: Ctx, job_id: str) -> dict:
    """O job, se o chamador pode vê-lo: o próprio dono, ou admin da MESMA conta."""
    job = get_raw(job_id) if re.fullmatch(r"[0-9a-f]{32}", job_id or "") else None
    if not job or job["org_id"] != ctx.org_id or (job["user_id"] != ctx.id and not ctx.is_admin):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tarefa não encontrada.")
    return job


def latest_active(ctx: Ctx, kind: str) -> dict | None:
    with db.conn() as c:
        r = c.one(f"SELECT {_COLS} FROM {TABLE} WHERE user_id = {c.ph} AND kind = {c.ph} "
                  f"AND status IN ('queued', 'running') ORDER BY created_at DESC LIMIT 1",
                  (ctx.id, kind))
    return _row_to_dict(r) if r else None


def recover_interrupted() -> int:
    """No boot: o que estava na fila/rodando morreu com o processo anterior."""
    with db.conn() as c:
        return c.run(f"UPDATE {TABLE} SET status = 'error', finished_at = {c.ph}, "
                     f"error = {c.ph} WHERE status IN ('queued', 'running')",
                     (_now(), "Interrompido: o servidor reiniciou. Tente novamente."))


def ocupado() -> bool:
    """Há lote ou disparo rodando AGORA neste processo? A Cloudflare consulta isto
    antes de desligar o container por inatividade — desligar no meio mataria o job."""
    with _email_locks_guard:
        emails = any(lk.locked() for lk in _email_locks.values())
    return _discover_lock.locked() or emails


def public(job: dict) -> dict:
    return {k: v for k, v in job.items() if k not in ("user_id", "org_id")}


# ------------------------------------------------------------------- discover
def start_discover(ctx: Ctx, plan: PlanCtx, quantidade: int, regiao: str | None,
                   so_com_contato: bool, user_agent: str) -> dict:
    from app.planos import ilimitado
    from app.regions import CONTINENTS, WORLD
    from .plan import leads_no_mes

    if latest_active(ctx, "discover"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Você já tem um lote sendo gerado.")
    teto = plan.limite("leads_clique")
    if quantidade > teto:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"O plano permite até {teto} empresas por clique.")
    regiao = (regiao or "").strip()
    if regiao == WORLD:
        regiao = ""
    if regiao and regiao not in CONTINENTS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Região inválida.")
    if regiao and not plan.tem("filtro_regiao"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Filtro por região não está no seu plano.")
    cota = plan.limite("leads_mes")
    if not ilimitado(cota):
        resta = max(0, cota - leads_no_mes(ctx.org_id))
        if resta < quantidade:
            raise HTTPException(status.HTTP_409_CONFLICT,
                                f"Faltam {resta} leads na cota deste mês e você pediu {quantidade}.")
    try:
        with db.conn() as c:
            nicho = orgs.nicho_de(c, ctx.org_id)
    except (NichoInvalido, ValueError) as erro:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"O nicho da sua empresa está com erro: {erro} Fale com o suporte.")
    params = {"quantidade": quantidade, "regiao": regiao, "so_com_contato": so_com_contato}
    job = _create(ctx, "discover", params)
    # O nicho vai num arquivo só deste lote (o processo filho lê e o apagamos ao fim).
    fd, nicho_path = tempfile.mkstemp(prefix="nicho-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(nicho.para_dict(), fh, ensure_ascii=False)
    env = _discover_env(ctx, plan, regiao, so_com_contato, user_agent, nicho_path)
    threading.Thread(target=_run_discover, args=(job["id"], quantidade, env),
                     name=f"discover-{job['id'][:8]}", daemon=True).start()
    return job


def _discover_env(ctx: Ctx, plan: PlanCtx, regiao: str, so_com_contato: bool,
                  user_agent: str, nicho_path: str) -> dict:
    # Ambiente PRÓPRIO do subprocesso (nunca mexe no os.environ da API, que é
    # compartilhado entre requisições).
    # Segredos que o motor NÃO precisa ficam de fora: ele só busca, lê sites e
    # grava leads. Assinar sessão, cifrar senha e mandar e-mail são da API.
    fora = {"JWT_SECRET", "APP_PASSWORD", "EMAIL_ENC_KEY", "SMTP_PASSWORD"}
    env = {k: v for k, v in os.environ.items() if k not in fora}
    env.update({
        "PROSPECT_DEVICE": classify_device(user_agent),
        "PROSPECT_REGION": regiao,
        "PROSPECT_REQUIRE_CONTACT": "1" if so_com_contato else "",
        "PROSPECT_PORTE": "1" if plan.tem("porte") else "",
        "PROSPECT_LINKEDIN": "1" if plan.tem("linkedin") else "",
        "OWNER_ID": ctx.id,
        "ORG_ID": ctx.org_id,
        NICHO_ENV: nicho_path,
        "PYTHONUNBUFFERED": "1",
    })
    return env


def _run_discover(job_id: str, quantidade: int, env: dict) -> None:
    try:
        _run_discover_locked(job_id, quantidade, env)
    finally:
        Path(env.get(NICHO_ENV, "")).unlink(missing_ok=True)


def _run_discover_locked(job_id: str, quantidade: int, env: dict) -> None:
    with _discover_lock:                                # um lote por vez na instalação
        t0 = time.time()
        _update(job_id, status="running", started_at=_now(), progress="Iniciando a busca…")
        tail: list[str] = []
        stamp, incompleto, erro_motor = "", "", ""
        try:
            proc = subprocess.Popen([*DISCOVER_CMD, str(quantidade)], cwd=str(ROOT), env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace")
            # Vigia de tempo: mata o motor mesmo que ele trave em silêncio.
            vigia = threading.Timer(DISCOVER_TIMEOUT_S, proc.kill)
            vigia.daemon = True
            vigia.start()
            ultimo = 0.0
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip()
                if not line:
                    continue
                tail = (tail + [_clean(line)])[-12:]
                if m := _STAMP_RE.search(line):
                    stamp = m.group(1)
                if "ENTREGA INCOMPLETA" in line:
                    incompleto = _clean(line)
                if "COTA DO MÊS ESGOTADA" in line or "JÁ HÁ UM LOTE" in line:
                    erro_motor = _clean(line)
                if time.time() - ultimo > 2:            # não martela o banco a cada linha
                    _update(job_id, progress=tail[-1])
                    ultimo = time.time()
            rc = proc.wait(timeout=60)
            vigia.cancel()
            if time.time() - t0 >= DISCOVER_TIMEOUT_S:
                raise TimeoutError("O lote passou do tempo máximo e foi interrompido.")
            secs = round(time.time() - t0, 1)
            if rc != 0 or erro_motor or not stamp:
                motivo = erro_motor or ("O lote terminou sem nenhuma empresa nova."
                                        if rc == 0 else "Não foi possível concluir agora.")
                _update(job_id, status="error", finished_at=_now(), error=motivo,
                        result={"log": tail, "segundos": secs})
                return
            _update(job_id, status="done", finished_at=_now(), progress="Lote pronto.",
                    result={"lote": stamp, "segundos": secs, "aviso": incompleto, "log": tail})
        except Exception as erro:  # noqa: BLE001 - o job nunca fica "rodando" para sempre
            log.exception("Falha no job %s", job_id)
            _update(job_id, status="error", finished_at=_now(),
                    error=str(erro) if isinstance(erro, TimeoutError)
                    else "Falha inesperada ao gerar o lote.", result={"log": tail})


# ---------------------------------------------------------------------- email
def _email_lock(user_id: str) -> threading.Lock:
    with _email_locks_guard:
        return _email_locks.setdefault(user_id, threading.Lock())


def start_email(ctx: Ctx, plan: PlanCtx, lote: str | None, classes: list[str]) -> dict:
    if latest_active(ctx, "email"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Já há um disparo seu em andamento.")
    sel = email_service.selection(ctx, plan, lote, classes)
    if not sel["pode_enviar"]:
        raise HTTPException(status.HTTP_409_CONFLICT, sel["motivo"])
    job = _create(ctx, "email", {"lote": lote, "classes": classes})
    threading.Thread(target=_run_email, args=(job["id"], ctx, plan, lote, classes),
                     name=f"email-{job['id'][:8]}", daemon=True).start()
    return job


def _run_email(job_id: str, ctx: Ctx, plan: PlanCtx, lote: str | None,
               classes: list[str]) -> None:
    from app import audit
    with _email_lock(ctx.id):
        _update(job_id, status="running", started_at=_now(), progress="Preparando o envio…")
        try:
            res = email_service.send_batch(ctx, plan, lote, classes,
                                           on_progress=lambda t: _update(job_id, progress=t))
            _update(job_id, status="done", finished_at=_now(),
                    progress=f"{res['enviados']} e-mail(s) enviado(s).", result=res)
            with db.conn() as c:
                audit.registrar(c, ctx.org_id, ctx.as_user(), "Enviou e-mails",
                                f"{res['enviados']} enviado(s)")
        except Exception as erro:  # noqa: BLE001
            log.exception("Falha no disparo %s", job_id)
            _update(job_id, status="error", finished_at=_now(),
                    error=str(erro) if isinstance(erro, RuntimeError)
                    else "Falha inesperada no disparo.")
