"""追加式哈希链。能发现篡改，不能阻止篡改——所以要把签名检查点存到库外（COS）。"""
import hashlib
import json
import time

GENESIS = "0" * 64


def _h(prev: str, payload: dict) -> str:
    body = json.dumps({"prev": prev, "payload": payload}, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(body.encode()).hexdigest()


class AuditLog:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def append(self, payload: dict) -> dict:
        prev = self.entries[-1]["hash"] if self.entries else GENESIS
        payload = {**payload, "ts": payload.get("ts", time.time())}
        e = {"prev_hash": prev, "payload": payload, "hash": _h(prev, payload)}
        self.entries.append(e)
        return e

    def checkpoint(self) -> str:
        return self.entries[-1]["hash"] if self.entries else GENESIS


def verify(entries: list[dict], checkpoint: str | None = None) -> tuple[bool, int | None]:
    """返回 (是否完整, 第一个出错位置)。"""
    prev = GENESIS
    for i, e in enumerate(entries):
        if e["prev_hash"] != prev or e["hash"] != _h(prev, e["payload"]):
            return False, i
        prev = e["hash"]
    if checkpoint is not None and prev != checkpoint:
        return False, len(entries)  # 尾部被截断
    return True, None
