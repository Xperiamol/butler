"""事务内的持久化审计链写入器（数据库版）；内存版见 chain.AuditLog。"""
from __future__ import annotations
import time

from .chain import GENESIS, _h


class PersistentAudit:
    def __init__(self, tx):
        self.tx = tx
        self.head = tx.get("meta", "audit_head") or {"hash": GENESIS, "count": 0}

    def append(self, payload):
        payload = {**payload, "ts": payload.get("ts", time.time())}
        entry = {"prev_hash": self.head["hash"], "payload": payload, "hash": _h(self.head["hash"], payload)}
        self.tx.put("audit_entry", f"{self.head['count']:020d}", entry)
        self.head = {"hash": entry["hash"], "count": self.head["count"] + 1}
        self.tx.put("meta", "audit_head", self.head)
        return entry

    def checkpoint(self):
        return self.head["hash"]
