"""模拟平台的运行时：持有 Hub，负责首次全量同步、后台增量同步、成员令牌刷新，以及演示控制台的变更。

- 后台线程每 interval 秒做一轮：拉变更 → 处理队列 → 刷新成员的平台令牌；每 reconcile_every 轮做一次全量对账
- apply() 在来源平台上做一次真实变更，随后立即触发一轮同步（演示里“几秒内生效”；生产窗口由 interval 决定）
- 变更日志落库（meta: platform_mutations），重启后重放，平台状态不丢
"""
from __future__ import annotations
import threading
import time

from ..connectors.platforms import PlatformConnector
from ..audit.persistent import PersistentAudit
from ..workers import sync
from ..workers.bulk import bulk_load
from .hub import PLATFORMS, Hub

IDENTITY_MAP = {"__identity__": True}
ACL_TTL = 24 * 3600.0


class SimRuntime:
    def __init__(self, database, embedder_for, hub: Hub, interval: float = 15.0, reconcile_every: int = 4):
        self.db, self.embedder_for, self.hub = database, embedder_for, hub
        self.interval, self.reconcile_every = interval, reconcile_every
        self.connectors = {p: PlatformConnector(hub, p) for p in PLATFORMS}
        self.lock = threading.RLock()
        self.n = 0
        self.thread: threading.Thread | None = None
        self.status = {p: {"state": "pending", "loaded": 0, "total": 0, "last_sync": None, "last_changes": 0, "lag_seconds": 0.0, "errors": 0} for p in PLATFORMS}
        self.ready = False
        self.stop = threading.Event()
        self.on_ready = None

    # ---- 成员令牌 ----
    def refresh_members(self) -> int:
        """把每个成员在各平台上的当前令牌写回成员记录。变了就提升修订号，旧会话随之作废。"""
        changed = 0
        with self.db.transaction() as tx:
            for row in tx.all("member"):
                pid = row["id"]
                if pid not in self.hub.directory.by_id:
                    continue
                groups = sorted(set(row.get("legacy_groups", [])) | self.hub.user_tokens(pid))
                if groups != sorted(row.get("groups", [])):
                    tx.put("member", pid, {**row, "groups": groups})
                    changed += 1
            if changed:
                tx.put("meta", "revision", {"value": tx.get("meta", "revision", {"value": 1})["value"] + 1})
        return changed

    # ---- 同步 ----
    def initial_load(self) -> None:
        settings = self._settings()
        for p, conn in self.connectors.items():
            st = self.status[p]
            st["state"] = "loading"

            def prog(done, total, st=st):
                st["loaded"], st["total"] = done, total

            try:
                bulk_load(self.db, conn, self.embedder_for(settings), IDENTITY_MAP, ACL_TTL, progress=prog)
                st["state"], st["last_sync"] = "ready", time.time()
            except Exception as error:   # noqa: BLE001
                st["state"], st["errors"] = "error", st["errors"] + 1
                st["error"] = type(error).__name__
        self.refresh_members()
        self.ready = True
        if self.on_ready:
            try:
                self.on_ready()
            except Exception:   # noqa: BLE001 — 审计历史种子失败不影响使用
                pass

    def _settings(self):
        with self.db.transaction() as tx:
            return tx.get("settings", "main")

    def tick(self, force_reconcile: bool = False) -> dict:
        with self.lock:
            settings = self._settings()
            emb = self.embedder_for(settings)
            out = {}
            for p, conn in self.connectors.items():
                st = self.status[p]
                if st["state"] == "loading":
                    continue
                try:
                    pulled = sync.pull(self.db, conn)
                    rec = sync.reconcile(self.db, conn, ttl=ACL_TTL) if force_reconcile or self.n % self.reconcile_every == 0 else None
                    done = sync.drain(self.db, conn, IDENTITY_MAP, emb, ACL_TTL)
                    st.update(state="ready", last_sync=time.time(), last_changes=sum(v for k, v in done.items() if k in ("done", "deleted")), errors=0)
                    with self.db.transaction() as tx:
                        from ..workers import queue
                        st["lag_seconds"] = queue.stats(tx)["lag_seconds"]
                    out[p] = {"pulled": pulled, "processed": done, **({"reconcile": rec} if rec else {})}
                except Exception as error:   # noqa: BLE001
                    st["errors"] += 1
                    st["error"] = type(error).__name__
                    out[p] = {"error": type(error).__name__}
            out["members_changed"] = self.refresh_members()
            self.n += 1
            return out

    def sync_now(self) -> dict:
        return self.tick(force_reconcile=True)

    # ---- 来源平台上的变更 ----
    def apply(self, action: str, params: dict, actor: str = "console") -> dict:
        with self.lock:
            result = self.hub.apply(action, params, now=time.time())
            with self.db.transaction() as tx:
                tx.put("meta", "platform_mutations", {"items": self.hub.mutations})
                PersistentAudit(tx).append({"event": "source.mutation", "user": actor, "action": action, "object": result.get("object"), "platform": result.get("platform")})
        sync_result = self.sync_now() if self.ready else {}
        return {"result": result, "sync": sync_result}

    # ---- 线程 ----
    def start(self) -> None:
        if self.thread:
            return

        def loop():
            try:
                self.initial_load()
            except Exception:   # noqa: BLE001
                pass
            while not self.stop.wait(self.interval):
                try:
                    self.tick()
                except Exception:   # noqa: BLE001
                    continue

        self.thread = threading.Thread(target=loop, daemon=True, name="sim-sync")
        self.thread.start()

    def snapshot(self) -> dict:
        return {"ready": self.ready, "interval_seconds": self.interval, "platforms": self.status, "stats": self.hub.stats()}
