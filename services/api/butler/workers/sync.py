"""同步处理：拉取变更 → 入队 → worker 取任务 → 实时展开权限 → 走统一入库 → 建索引。

保证：
- 幂等：重复事件不重复处理（队列按事件键去重；内容和权限都没变的 upsert 是空操作，也不提升修订号）
- 乱序：每个对象记录已处理的来源版本，旧版本事件丢弃；删除留墓碑，之后到达的旧 upsert 不会让文档复活
- 权限失败即拒绝：fetch_principals 抛错 ⇒ 任务重试/进死信，已有文档的权限复核期（acl_fresh_until）过期后自动不可读
- 撤权可度量：权限变化时审计里记下 source_changed_at / detected_at / effective_at 三个时间点
"""
from __future__ import annotations
import time
from typing import Callable

from ..audit.persistent import PersistentAudit
from ..connectors.sync import Event, SyncConnector
from ..ingest.embedding import EmbeddingFailure
from ..ingest.index import index_documents
from ..knowledge import delete_document, upsert_documents
from . import queue

DEFAULT_ACL_TTL = 3600.0


def doc_id(connector: SyncConnector, external_id: str) -> str:
    return f"{connector.name}:{external_id}"


def map_principals(principals: frozenset[str], principal_map: dict[str, list[str]]) -> list[str]:
    """平台主体 → 本地权限组。映射不出来的主体被忽略；"*" 表示所有人都映射到的组。"""
    groups = set(principal_map.get("*", []))
    for p in principals:
        groups |= set(principal_map.get(p, []))
    return sorted(groups)


def pull(database, connector: SyncConnector, now: float | None = None) -> int:
    """取游标之后的变更并入队；游标与入队在同一事务，崩溃重跑只会得到重复事件（被去重）。"""
    now = time.time() if now is None else now
    with database.transaction() as tx:
        cursor = (tx.get("meta", f"sync_cursor:{connector.name}") or {}).get("value")
    events, new_cursor = connector.events(cursor)
    n = 0
    with database.transaction() as tx:
        for e in events:
            n += queue.enqueue(tx, connector.name, e.external_id, e.kind, e.version, e.version_key,
                               {"observed_at": e.observed_at}, now)
        tx.put("meta", f"sync_cursor:{connector.name}", {"value": new_cursor})
    return n


def reconcile(database, connector: SyncConnector, now: float | None = None, ttl: float = DEFAULT_ACL_TTL) -> dict:
    """对账补漏：来源有而本地没有 / 来源权限与本地不一致 / 权限复核快到期 / 本地有而来源已没有。"""
    now = time.time() if now is None else now
    listed = dict(connector.list_ids())
    with database.transaction() as tx:
        known = {d["sync"]["external_id"]: d for d in tx.all("document")
                 if (d.get("sync") or {}).get("source") == connector.name}
    head_version = max(listed.values(), default=0.0)
    queued = 0
    with database.transaction() as tx:
        for ext, version in listed.items():
            cur = known.get(ext)
            need = cur is None
            if cur is not None:
                try:
                    need = (sorted(connector.fetch_principals(ext)) != cur["sync"]["principals"]
                            or cur["sync"]["acl_fresh_until"] - now < ttl / 2)   # 权限变了，或复核快到期需要续期
                except Exception:   # noqa: BLE001 — 权限暂时拿不到：交给 upsert 任务重试，不在这里放行
                    need = True
            if need and not queue.has_open(tx, connector.name, ext):
                queued += queue.enqueue(tx, connector.name, ext, "upsert", version, f"reconcile:{version}:{int(now // 60)}",
                                        {"observed_at": now}, now)
        for ext, cur in known.items():
            if ext not in listed and not queue.has_open(tx, connector.name, ext):
                v = max(head_version, float(cur["sync"]["version"]))
                queued += queue.enqueue(tx, connector.name, ext, "delete", v, f"reconcile-delete:{v}", {"observed_at": now}, now)
    return {"listed": len(listed), "queued": queued}


def _state(tx, name: str, ext: str) -> dict:
    return tx.get("meta", f"sync_state:{name}:{ext}") or {"version": -1.0, "deleted": False}


def process(database, connector: SyncConnector, job: dict, principal_map: dict[str, list[str]],
            ttl: float = DEFAULT_ACL_TTL, now: float | None = None) -> str:
    """处理一个任务，返回 done | stale | noop | deleted。异常交给调用方走 fail/重试。"""
    now = time.time() if now is None else now
    ext, version, kind = job["external_id"], float(job["version"]), job["kind"]
    observed = (job.get("payload") or {}).get("observed_at", job["created"])
    with database.transaction() as tx:
        st = _state(tx, connector.name, ext)
        if version < st["version"]:
            return "stale"
        if st.get("deleted") and kind == "upsert" and version <= st["version"]:
            return "stale"   # 墓碑：删除之后到达的旧 upsert
    did = doc_id(connector, ext)
    if kind == "delete":
        with database.transaction() as tx:
            removed = delete_document(tx, did)
            tx.put("meta", f"sync_state:{connector.name}:{ext}", {"version": version, "deleted": True})
            if removed:
                PersistentAudit(tx).append({"event": "sync.deleted", "doc": did, "source_changed_at": observed,
                                            "detected_at": job["created"], "effective_at": now})
        return "deleted"
    ext_doc = connector.fetch(ext)                       # 事务外的网络/磁盘调用
    if ext_doc is None:                                  # 已经不存在：按删除处理
        return process(database, connector, {**job, "kind": "delete"}, principal_map, ttl, now)
    principals = connector.fetch_principals(ext)         # 失败直接抛，任务重试
    groups = map_principals(principals, principal_map)
    data = {"id": did, "source": "upload", "title": ext_doc.title, "text": ext_doc.text, "acl": groups,
            "url": ext_doc.url, "sync": {"source": connector.name, "external_id": ext, "version": version,
                                         "principals": sorted(principals), "acl_checked_at": now,
                                         "acl_fresh_until": now + ttl, "deleted": False}}
    with database.transaction() as tx:
        st = _state(tx, connector.name, ext)
        if version < st["version"]:
            return "stale"
        before = tx.get("document", did)
        if before is not None and before["text"] == data["text"] and sorted(before["acl"]) == data["acl"]:
            # 内容和权限都没变：只续期权限复核，不提升修订号、不重建索引
            tx.put("document", did, {**before, "sync": data["sync"]})
            tx.put("meta", f"sync_state:{connector.name}:{ext}", {"version": version, "deleted": False})
            return "noop"
        result = upsert_documents(tx, [data], allow_empty_acl=True)
        tx.put("meta", f"sync_state:{connector.name}:{ext}", {"version": version, "deleted": False})
        audit = PersistentAudit(tx)
        if did in result["acl_changed"]:
            old, new = result["acl_changed"][did]
            audit.append({"event": "sync.acl_changed", "doc": did, "removed": sorted(set(old) - set(new)),
                          "added": sorted(set(new) - set(old)), "source_changed_at": observed,
                          "detected_at": job["created"], "effective_at": now})
        if did in result["changed"]:
            audit.append({"event": "sync.updated", "doc": did, "version": version, "source_changed_at": observed,
                          "detected_at": job["created"], "effective_at": now})
    return "done"


def run_once(database, connector: SyncConnector, principal_map: dict[str, list[str]], embedder,
             ttl: float = DEFAULT_ACL_TTL, limit: int = 50, now: Callable[[], float] = time.time) -> dict:
    """领取并处理一批任务。向量化放在每个任务之后、事务之外；向量服务故障不让任务失败（文档词法兜底）。"""
    with database.transaction() as tx:
        jobs = queue.claim(tx, now(), limit)
    summary: dict[str, int] = {}
    indexed: list[str] = []
    for job in jobs:
        try:
            outcome = process(database, connector, job, principal_map, ttl, now())
            err = None
        except Exception as error:   # noqa: BLE001 — 任何失败都进重试/死信，错误只记类型
            outcome, err = "failed", type(error).__name__
        with database.transaction() as tx:
            if err:
                outcome = queue.fail(tx, job["id"], err, now())
            else:
                queue.finish(tx, job["id"], "done", outcome)
                if outcome == "done":
                    indexed.append(doc_id(connector, job["external_id"]))
        summary[outcome] = summary.get(outcome, 0) + 1
    if indexed:
        try:
            index_documents(database, embedder, indexed)
        except EmbeddingFailure:
            summary["index_pending"] = len(indexed)
    return summary


def drain(database, connector, principal_map, embedder, ttl=DEFAULT_ACL_TTL, max_rounds: int = 20, now=time.time) -> dict:
    total: dict[str, int] = {}
    for _ in range(max_rounds):
        s = run_once(database, connector, principal_map, embedder, ttl, now=now)
        if not s:
            break
        for k, v in s.items():
            total[k] = total.get(k, 0) + v
    return total
