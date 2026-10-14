"""数据库队列：幂等入队、租约领取、指数退避重试、死信。不依赖 Redis；Celery 适配层见 celery_app.py。

- 幂等：任务 ID = 哈希(来源|外部ID|类型|版本标识)，同一事件重复投递只会有一条
- 租约：领取时把 run_after 推到租约结束，worker 崩溃后到期会被重新领取
- 失败：attempts+1，退避 base * 2^n 秒，超过 max_attempts 进入 dead（死信），保留错误信息供排查
"""
from __future__ import annotations
import hashlib
import time

from sqlalchemy import func, select, update

from .. import database as D

MAX_ATTEMPTS = 5
BACKOFF_BASE = 5.0
LEASE_SECONDS = 120.0


def job_id(source: str, external_id: str, kind: str, version_key: str) -> str:
    return hashlib.sha256("\0".join([source, external_id, kind, version_key]).encode()).hexdigest()[:40]


def enqueue(tx, source: str, external_id: str, kind: str, version: float, version_key: str, payload: dict | None = None,
            now: float | None = None) -> bool:
    now = time.time() if now is None else now
    jid = job_id(source, external_id, kind, version_key)
    if tx.connection.execute(select(D.sync_jobs.c.id).where(D.sync_jobs.c.id == jid)).first():
        return False
    tx.connection.execute(D.sync_jobs.insert().values(
        id=jid, source=source, external_id=external_id, version=version, kind=kind, status="pending", attempts=0,
        run_after=now, error="", payload=payload or {}, created=now))
    return True


def has_open(tx, source: str, external_id: str) -> bool:
    return tx.connection.execute(select(D.sync_jobs.c.id).where(
        D.sync_jobs.c.source == source, D.sync_jobs.c.external_id == external_id,
        D.sync_jobs.c.status.in_(("pending", "retry", "running"))).limit(1)).first() is not None


def claim(tx, now: float | None = None, limit: int = 10, lease: float = LEASE_SECONDS) -> list[dict]:
    now = time.time() if now is None else now
    rows = tx.connection.execute(select(D.sync_jobs).where(
        D.sync_jobs.c.status.in_(("pending", "retry", "running")), D.sync_jobs.c.run_after <= now
    ).order_by(D.sync_jobs.c.version, D.sync_jobs.c.created).limit(limit)).mappings().all()
    jobs = []
    for r in rows:
        tx.connection.execute(update(D.sync_jobs).where(D.sync_jobs.c.id == r["id"]).values(
            status="running", run_after=now + lease, attempts=r["attempts"] + (1 if r["status"] == "running" else 0)))
        jobs.append(dict(r))
    return jobs


def finish(tx, jid: str, status: str = "done", note: str = "") -> None:
    tx.connection.execute(update(D.sync_jobs).where(D.sync_jobs.c.id == jid).values(status=status, error=note[:500]))


def fail(tx, jid: str, error: str, now: float | None = None, max_attempts: int = MAX_ATTEMPTS, base: float = BACKOFF_BASE) -> str:
    now = time.time() if now is None else now
    attempts = tx.connection.execute(select(D.sync_jobs.c.attempts).where(D.sync_jobs.c.id == jid)).scalar_one() + 1
    status = "dead" if attempts >= max_attempts else "retry"
    tx.connection.execute(update(D.sync_jobs).where(D.sync_jobs.c.id == jid).values(
        status=status, attempts=attempts, error=error[:500], run_after=now + base * (2 ** (attempts - 1))))
    return status


def stats(tx, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    by = dict(tx.connection.execute(select(D.sync_jobs.c.status, func.count()).group_by(D.sync_jobs.c.status)).all())
    oldest = tx.connection.execute(select(func.min(D.sync_jobs.c.created)).where(
        D.sync_jobs.c.status.in_(("pending", "retry", "running")))).scalar_one()
    dead = tx.connection.execute(select(D.sync_jobs.c.external_id, D.sync_jobs.c.error, D.sync_jobs.c.attempts).where(
        D.sync_jobs.c.status == "dead").limit(20)).all()
    return {"by_status": by, "lag_seconds": round(now - oldest, 1) if oldest else 0.0,
            "dead_letters": [{"external_id": r[0], "error": r[1], "attempts": r[2]} for r in dead]}
