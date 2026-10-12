"""同步 worker：循环 拉取变更 → 定期对账 → 处理队列。不需要 Redis，也可以只靠 API 的手动触发。

    python -m butler.workers.run [--interval 30] [--reconcile-every 20] [--once]
"""
from __future__ import annotations
import argparse
import logging
import time

from . import sync
from .factory import build_connector

log = logging.getLogger("butler.worker")


def tick(database, embedder_for, n: int = 0, reconcile_every: int = 20) -> dict:
    """做一轮同步；失败只记录类型，不让进程退出。供循环、Celery 任务和 API 手动触发共用。"""
    with database.transaction() as tx:
        cfg = tx.get("sync_config", "main")
        settings = tx.get("settings", "main")
    if not cfg:
        return {"configured": False}
    try:
        connector = build_connector(cfg["connector"])
        ttl = float(cfg.get("acl_ttl_seconds", sync.DEFAULT_ACL_TTL))
        out = {"pulled": sync.pull(database, connector)}
        if n % reconcile_every == 0:
            out["reconcile"] = sync.reconcile(database, connector, ttl=ttl)
        out["processed"] = sync.drain(database, connector, cfg.get("principal_map", {}), embedder_for(settings), ttl)
        if out["processed"].get("done") or out["processed"].get("deleted"):
            from ..knowledge import refresh_auto_premises
            with database.transaction() as tx:
                out["auto_premises"] = refresh_auto_premises(tx)
        return out
    except Exception as error:   # noqa: BLE001
        log.error("sync tick failed: %s", type(error).__name__)
        return {"error": type(error).__name__}


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--interval", type=float, default=30.0)
    p.add_argument("--reconcile-every", type=int, default=20)
    p.add_argument("--once", action="store_true")
    a = p.parse_args(argv)
    from .. import workspace as w   # 复用同一个数据库与嵌入配置
    n = 0
    while True:
        log.info("tick %s", tick(w.database, w.embedder_for, n, a.reconcile_every))
        n += 1
        if a.once:
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    raise SystemExit(main())
