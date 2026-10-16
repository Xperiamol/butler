"""首次全量同步的批量路径：每批一个事务写入文档、同步状态，批量建索引。之后的增量变更仍走 sync.py 的队列（幂等、乱序、对账都在那条路径上）。

可以中断后重跑：已经同步过且版本不低于来源版本的对象会被跳过。
"""
from __future__ import annotations
import time
from typing import Callable

from ..audit.persistent import PersistentAudit
from ..ingest.index import index_documents
from ..knowledge import upsert_documents
from .sync import DEFAULT_ACL_TTL, doc_id, map_principals


def bulk_load(database, connector, embedder, principal_map: dict, ttl: float = DEFAULT_ACL_TTL, batch: int = 250,
              progress: Callable[[int, int], None] | None = None, now: Callable[[], float] = time.time) -> dict:
    listed = connector.list_ids()
    with database.transaction() as tx:
        have = {d["sync"]["external_id"]: float(d["sync"]["version"]) for d in tx.all("document") if (d.get("sync") or {}).get("source") == connector.name}
    todo = [(ext, v) for ext, v in listed if have.get(ext, -1.0) < v]
    total, done, skipped, errors = len(listed), len(listed) - len(todo), 0, 0
    cursor = None
    if progress:
        progress(done, total)
    for i in range(0, len(todo), batch):
        rows = []
        t = now()
        for ext, version in todo[i:i + batch]:
            try:
                d = connector.fetch(ext)
                if d is None:
                    skipped += 1
                    continue
                principals = connector.fetch_principals(ext)
            except Exception:   # noqa: BLE001 — 单个对象失败不拖垮整批；对账会补
                errors += 1
                continue
            groups = map_principals(principals, principal_map)
            rows.append(({"id": doc_id(connector, ext), "source": d.source, "title": d.title, "text": d.text, "acl": groups, "url": d.url, "meta": d.meta,
                          "sync": {"source": connector.name, "external_id": ext, "version": version, "principals": sorted(principals), "acl_checked_at": t,
                                   "acl_fresh_until": t + ttl, "deleted": False}}, ext, version))
        with database.transaction() as tx:
            upsert_documents(tx, [r[0] for r in rows], allow_empty_acl=True)
            for _, ext, version in rows:
                tx.put("meta", f"sync_state:{connector.name}:{ext}", {"version": version, "deleted": False})
        index_documents(database, embedder, [r[0]["id"] for r in rows])
        done += len(rows)
        if progress:
            progress(done, total)
    with database.transaction() as tx:
        # 游标设为现在：之后的变更走增量
        tx.put("meta", f"sync_cursor:{connector.name}", {"value": str(connector.server.log.version)} if hasattr(connector, "server") else {"value": None})
        PersistentAudit(tx).append({"event": "sync.initial_load", "source": connector.name, "documents": done, "errors": errors, "ts": now()})
    return {"loaded": done, "total": total, "errors": errors, "skipped": skipped}
