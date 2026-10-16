"""“Tidepool Pay”演示世界在工作区里的接线：构建模拟平台、写入成员（带各平台令牌）、检索选项、引用元数据、审计历史种子。

BUTLER_DEMO_WORLD=company（默认）在演示模式下启动四个模拟平台和后台同步；=tiny 只用早期的小型示例资料（测试用）。
"""
from __future__ import annotations
import hashlib
import os
import random
import time

from .answer.planner import Planner
from .answer.remote import RemoteModel, llm_env
from .platforms.hub import PLATFORMS
from .platforms.people import FEATURED
from .platforms.runtime import SimRuntime
from .platforms.vocab import date
from .platforms.world import build_world

WORLD = os.getenv("BUTLER_DEMO_WORLD", "company")
RUNTIME: SimRuntime | None = None
_PLANNERS: dict[str, Planner] = {}

BLURBS = {
    "alice": "高级后端工程师：查故障、看进度、找操作手册",
    "ken": "外包人员：看看受限身份能问到什么",
    "sara": "安全工程师（管理权限）：审批、成员、配置、审计、来源平台控制台",
    "pete": "产品副总裁：能进领导层私有频道和受限资料",
    "amy": "合规官：审计查询与哈希链校验",
    "jdoe": "初级工程师：问“所有安全漏洞”试试",
    "mliu": "后端工程师（Atlas 迁移负责人）：不在领导层私有频道里",
    "raj": "SRE 值班工程师：查最新 runbook",
}


def enabled(mode: str) -> bool:
    return mode == "demo" and WORLD == "company"


def seed_members(database, hub) -> int:
    n = 0
    with database.transaction() as tx:
        for p in hub.directory.people:
            groups = sorted(set(p.legacy_groups) | hub.user_tokens(p.id))
            row = {"id": p.id, "name": f"{p.name}（{p.title}）", "groups": groups, "legacy_groups": list(p.legacy_groups), "role": p.role, "active": True,
                   "team": p.team, "title": p.title, "kind": p.kind, "featured": p.featured, "blurb": BLURBS.get(p.id, ""), "platform_id": p.id}
            old = tx.get("member", p.id)
            if old is None or {k: old.get(k) for k in row} != row:
                tx.put("member", p.id, {**(old or {}), **row})
                n += 1
        if n:
            tx.put("meta", "revision", {"value": tx.get("meta", "revision", {"value": 1})["value"] + 1})
    return n


def start(database, embedder_for, scale: float = 1.0, charts: int = 90, interval: float = 15.0, auto_start: bool = True) -> SimRuntime:
    global RUNTIME
    with database.transaction() as tx:
        epoch = (tx.get("meta", "sim_epoch") or {}).get("value")
        if epoch is None:
            epoch = time.time()
            tx.put("meta", "sim_epoch", {"value": epoch})
        mutations = (tx.get("meta", "platform_mutations") or {}).get("items", [])
    hub = build_world(epoch=epoch, scale=scale, charts=charts)
    hub.replay(mutations)
    seed_members(database, hub)
    RUNTIME = SimRuntime(database, embedder_for, hub, interval)
    RUNTIME.on_ready = lambda: seed_audit_history(database, hub, epoch)
    if auto_start:
        RUNTIME.start()
    return RUNTIME


# ---- 检索选项：规划器 + 实时复核 + 影子查询（审计用）----
def retrieval_options(settings: dict, live: bool, model_name: str = "") -> dict:
    if RUNTIME is None:
        return {}
    hub = RUNTIME.hub
    planner = None
    key, base = llm_env()
    name = os.getenv("BUTLER_LLM_PLANNER_MODEL") or os.getenv("BUTLER_LLM_JUDGE_MODEL") or settings.get("judge_model") or model_name
    cache_key = name if live else "rules"
    if cache_key not in _PLANNERS:
        model = RemoteModel(base, key, name, 600) if live and name and key and base.startswith("https://") else None
        _PLANNERS[cache_key] = Planner(model, today=date(time.time()))
    planner = _PLANNERS[cache_key]

    def recheck(identity, doc) -> bool:
        if doc.id.split(":")[0] not in PLATFORMS:
            return True                  # 早期示例资料不来自平台：没有平台可复核，仍受入库快照约束
        return hub.can_access(identity.id, doc.id)

    return {"planner": planner, "recheck": recheck, "shadow": True}


# ---- 引用的元数据：界面据此显示图标、模态、来源容器、新鲜度 ----
def cite_meta(tx, docs) -> list[dict]:
    out = []
    for d in docs:
        item = {"id": d.id, "source": d.source, "title": d.title}
        if d.spans:
            item["spans"] = [list(x) for x in d.spans]
            item["heading"] = d.heading
        row = tx.get("document", d.id) or {}
        meta = row.get("meta") or {}
        if meta:
            sync = row.get("sync") or {}
            item.update({"modality": meta.get("modality", "text"), "container": meta.get("container"), "url": row.get("url"), "updated": meta.get("updated"), "kind": meta.get("kind"),
                         "media": bool(meta.get("media")), "mime": meta.get("mime"), "parent": meta.get("parent"), "file_name": meta.get("file_name"), "synced": sync.get("acl_checked_at")})
        out.append(item)
    return out


# ---- 审计历史种子：过去 30 天的访问记录（合成），让“审计查询”用例有数据可查 ----
def seed_audit_history(database, hub, epoch: float, n: int = 640, seed: int = 5) -> int:
    from .audit.persistent import PersistentAudit
    with database.transaction() as tx:
        if tx.get("meta", "audit_history_seeded"):
            return 0
    rng = random.Random(seed)
    people = [p for p in hub.directory.people if p.kind == "employee"]
    weights = [6 if p.featured else 1 for p in people]
    pools = {"confluence": list(hub.confluence.pages), "jira": list(hub.jira.issues), "slack": list(hub.slack.all_objects()), "drive": list(hub.drive.files)}
    pgw = [pid for pid, p in hub.confluence.pages.items() if p.space == "PGW"]
    sec = [pid for pid, p in hub.confluence.pages.items() if p.space == "SEC"][:6] + ["9200"]
    events: list[dict] = []

    def add(user: str, day: float, docs: list[str], denied: list[str], status: str):
        ts = epoch - day * 86400 + rng.randint(8, 19) * 3600 + rng.randint(0, 3599)
        by = {}
        for d in docs:
            by[d.split(":")[0]] = by.get(d.split(":")[0], 0) + 1
        events.append({"ts": ts, "user": user, "question_hash": hashlib.sha256(f"{user}{ts}".encode()).hexdigest()[:16], "guard": True, "docs": docs, "degraded": False, "status": status,
                       "request_id": "", "quarantined": [], "question_flagged": False, "answer_digest": hashlib.sha256(f"a{ts}".encode()).hexdigest()[:16], "event": "ask",
                       "blocked_facts": [], "retrieved": docs, "denied": denied, "platforms": by, "synthetic": True})

    def accessible(person: str, count: int, platform: str | None = None, pool: list[str] | None = None) -> list[str]:
        out: list[str] = []
        tries = 0
        while len(out) < count and tries < 400:
            tries += 1
            plat = platform or rng.choice(list(pools))
            ext = rng.choice(pool or pools[plat])
            if hub.can_access(person, f"{plat}:{ext}"):
                out.append(f"{plat}:{ext}")
        return out

    for _ in range(n):
        p = rng.choices(people, weights)[0]
        docs = accessible(p.id, rng.randint(1, 4))
        add(p.id, rng.uniform(0, 30), docs, [], "answered" if docs else "no_evidence")
    for i in range(16):                                   # jdoe 在 payment-gateway 空间里的访问（审计用例的示例问法）
        add("jdoe", rng.uniform(0.2, 29), accessible("jdoe", rng.randint(1, 3), "confluence", pgw), [], "answered")
    for i in range(2):
        add("jdoe", rng.uniform(1, 25), accessible("jdoe", 1, "confluence", pgw), [f"confluence:{rng.choice(sec)}"], "answered")   # 顺带想看安全空间，被拒
    for i in range(3):                                    # 外包人员想看 Q3 事件报告：被拒绝，回答里没有任何内容
        add("ken", rng.uniform(0.5, 20), [], ["confluence:9200", "drive:fH-FORENSICS"], "no_evidence")
    events.sort(key=lambda e: e["ts"])
    with database.transaction() as tx:
        audit = PersistentAudit(tx)
        for e in events:
            audit.append(e)
        tx.put("meta", "audit_history_seeded", {"value": len(events)})
    return len(events)
