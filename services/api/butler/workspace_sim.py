"""工作区里和“来源平台模拟器”相关的接口：状态、预设变更、立即同步、查找、媒体文件、审计查询。
在 workspace.py 末尾安装（需要它里面的路由、依赖和数据库）。
"""
from __future__ import annotations
import json
import re
import time
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field

from . import company
from .answer.remote import RemoteModel, llm_env, parse_json_object
from .platforms import media as media_store
from .platforms.hub import Hub, PLATFORMS
from . import workspace as W
from .workspace import ADMIN_ROLES, AUDIT_ROLES, FULL_AUDIT_ROLES, MODE, StrictBody, admin, auditor, can_read, checked, current, router
from .models import Doc


def _runtime():
    if company.RUNTIME is None:
        raise HTTPException(404, "当前不是公司演示世界。")
    return company.RUNTIME


# ================= 模拟平台 =================
@router.get("/sim/status")
def sim_status(who=Depends(current)):
    rt = company.RUNTIME
    if rt is None:
        return {"enabled": False}
    snap = rt.snapshot()
    with W.database.transaction() as tx:
        docs = tx.count("document")
    return {"enabled": True, **snap, "documents": docs}


def presets(hub: Hub) -> list[dict]:
    P = hub.directory.by_id
    name = lambda i: P[i].name if i in P else i
    return [
        {"id": "runbook", "platform": "confluence", "title": "更新 payment-service runbook：新增第 7 步（切换账本写节点）", "scenario": "数据新鲜度",
         "action": "confluence.update_page", "params": {"id": "9100", "append": "### Step 7 — Fail over the ledger writer (added today)\nIf the ledger writer shows replication lag above 30 seconds or the writer instance is unhealthy, promote the standby in ap-southeast-1b with `ledger-failover promote --az ap-southeast-1b`, then restart payment-service with the new writer endpoint. Confirm in Grafana that write latency recovers within 5 minutes."},
         "then": {"user": "raj", "question": "What's the latest runbook for the payment-service incident? Include every step."}},
        {"id": "atlas-post", "platform": "slack", "title": "在 #proj-atlas 发一条新的阻塞消息（刚刚）", "scenario": "数据新鲜度",
         "action": "slack.post", "params": {"channel": "CH-ATLAS", "user": "mliu", "text": "New blocker just now: rehearsal #3 dry run failed at step 6, the Aurora parameter group max_logical_replication_workers is too low. ATLAS-106 stays blocked."},
         "then": {"user": "mliu", "question": "What's the status of the database migration project and were there any blockers raised in Slack this week?"}},
        {"id": "remove-alice", "platform": "slack", "title": f"把 {name('alice')} 移出私有频道 #settlement-war-room", "scenario": "权限实时变更",
         "action": "slack.remove_member", "params": {"channel": "CH-SETTLE", "user": "alice"}, "undo": {"action": "slack.add_member", "params": {"channel": "CH-SETTLE", "user": "alice"}},
         "then": {"user": "alice", "question": "Why was the settlement batch delayed on Oct 12 and what's the workaround?"}},
        {"id": "restrict-playbook", "platform": "confluence", "title": "把「Settlement delay playbook」页面限制为只有 Marcus 可见", "scenario": "权限实时变更",
         "action": "confluence.restrict_page", "params": {"id": "9300", "users": ["marcus"]},
         "then": {"user": "alice", "question": "What does the settlement delay playbook say to do when the bank rejects a batch?"}},
        {"id": "unshare-msa", "platform": "drive", "title": f"取消 Acme Cloud MSA 对 {name('grace')} 的共享", "scenario": "权限实时变更",
         "action": "drive.unshare", "params": {"id": "fH-MSA", "kind": "user", "who": "grace"}, "undo": {"action": "drive.share", "params": {"id": "fH-MSA", "kind": "user", "who": "grace", "role": "reader"}},
         "then": {"user": "grace", "question": "What does the Acme Cloud MSA say about early termination fees?"}},
        {"id": "secure-pay9002", "platform": "jira", "title": "把 PAY-9002 的安全级别设为 Security Team", "scenario": "权限实时变更",
         "action": "jira.set_security", "params": {"key": "PAY-9002", "level": "Security Team"}, "undo": {"action": "jira.set_security", "params": {"key": "PAY-9002", "level": None}},
         "then": {"user": "jdoe", "question": "What follow-up tickets were created after the payment outage?"}},
    ]


@router.get("/sim/presets")
def sim_presets(who=Depends(admin)):
    rt = _runtime()
    with W.database.transaction() as tx:
        checked(tx, who, ADMIN_ROLES)
    return {"presets": presets(rt.hub), "actions": Hub.ACTIONS}


class MutateBody(StrictBody):
    action: str = Field(min_length=1, max_length=64)
    params: dict = Field(default_factory=dict)


@router.post("/sim/mutate")
def sim_mutate(body: MutateBody, who=Depends(admin)):
    rt = _runtime()
    with W.database.transaction() as tx:
        who = checked(tx, who, ADMIN_ROLES)
    if body.action not in Hub.ACTIONS or len(json.dumps(body.params)) > 4000:
        raise HTTPException(422, "不支持的来源平台操作。")
    try:
        return rt.apply(body.action, body.params, actor=who.id)
    except (KeyError, ValueError) as error:
        raise HTTPException(422, f"操作未完成：{type(error).__name__}")


@router.post("/sim/sync")
def sim_sync(who=Depends(admin)):
    rt = _runtime()
    with W.database.transaction() as tx:
        checked(tx, who, ADMIN_ROLES)
    t = time.time()
    out = rt.sync_now()
    return {"seconds": round(time.time() - t, 2), "result": out}


@router.get("/sim/lookup")
def sim_lookup(kind: str, q: str = "", who=Depends(admin)):
    rt = _runtime()
    with W.database.transaction() as tx:
        checked(tx, who, ADMIN_ROLES)
    hub, needle = rt.hub, q.strip().lower()
    out: list[dict] = []
    if kind == "user":
        out = [{"id": p.id, "label": f"{p.name} · {p.title}"} for p in hub.directory.people if not needle or needle in p.id or needle in p.name.lower()]
    elif kind == "page":
        out = [{"id": p.id, "label": f"{p.title} [{p.space}]"} for p in hub.confluence.pages.values() if not needle or needle in p.title.lower()]
    elif kind == "issue":
        out = [{"id": i.key, "label": f"{i.key} {i.summary}"} for i in hub.jira.issues.values() if not needle or needle in i.summary.lower() or needle in i.key.lower()]
    elif kind == "channel":
        out = [{"id": c.id, "label": f"#{c.name} ({c.kind})"} for c in hub.slack.channels.values() if not needle or needle in c.name.lower()]
    elif kind == "file":
        out = [{"id": f.id, "label": f.name} for f in hub.drive.files.values() if not needle or needle in f.name.lower()]
    return {"items": out[:25]}


# ================= 媒体文件（受同样的权限约束）=================
@router.get("/media/{doc_id:path}")
def media_file(doc_id: str, who=Depends(current)):
    """原图 / 扫描 PDF / 录音。先按入库快照判权，再按平台原生语义实时复核；任一不通过一律 404（不区分“不存在”和“无权”）。"""
    with W.database.transaction() as tx:
        who = checked(tx, who)
        row = tx.get("document", doc_id)
        meta = (row or {}).get("meta") or {}
        if not row or not meta.get("media"):
            raise HTTPException(404, "没有这个文件。")
        fresh = (row.get("sync") or {}).get("acl_fresh_until")
        if (fresh is not None and fresh < time.time()) or not can_read(who, Doc(doc_id, row["source"], row["title"], "", frozenset(row["acl"]))):
            raise HTTPException(404, "没有这个文件。")
    rt = company.RUNTIME
    if rt is not None and doc_id.split(":")[0] in PLATFORMS and not rt.hub.can_access(who.id, doc_id):
        raise HTTPException(404, "没有这个文件。")
    path = media_store.path_of(meta["media"])
    if path is None:
        raise HTTPException(404, "没有这个文件。")
    kind = {"image": "image/png", "pdf": "application/pdf", "audio": "audio/mpeg"}.get(meta.get("modality", ""), "application/octet-stream")
    return FileResponse(path, media_type=kind, headers={"cache-control": "private, max-age=60"})


@router.get("/transcript/{doc_id:path}")
def transcript(doc_id: str, who=Depends(current)):
    """录音的带时间戳转写（说话人分段），同样先判权。"""
    with W.database.transaction() as tx:
        who = checked(tx, who)
        row = tx.get("document", doc_id)
        meta = (row or {}).get("meta") or {}
        if not row or meta.get("modality") not in ("audio", "video") or not can_read(who, Doc(doc_id, row["source"], row["title"], "", frozenset(row["acl"]))):
            raise HTTPException(404, "没有这个文件。")
    t = media_store.transcript(meta.get("media") or "")
    return t or {"duration": 0, "segments": []}


# ================= 审计查询 =================
def _doc_info(tx, ids: set[str]) -> dict[str, dict]:
    out = {}
    for i in ids:
        row = tx.get("document", i)
        meta = (row or {}).get("meta") or {}
        out[i] = {"id": i, "title": (row or {}).get("title", i), "platform": i.split(":")[0] if ":" in i else "upload", "container": meta.get("container", ""), "space": meta.get("space") or meta.get("project") or meta.get("channel") or "", "modality": meta.get("modality", "text")}
    return out


def audit_query(tx, who, *, user: str = "", platform: str = "", container: str = "", doc: str = "", days: int = 0, decision: str = "", event: str = "ask", text: str = "", limit: int = 100) -> dict:
    """可查询的审计：谁、什么时候、问了什么（只存哈希）、检索到哪些文档、每份文档的授权决定（放行/拒绝）。"""
    visible = None if who.role in FULL_AUDIT_ROLES else {d.id for d in __import__("butler.workspace", fromlist=["visible_docs"]).visible_docs(tx, who)}
    cutoff = time.time() - days * 86400 if days else 0
    entries = tx.tail("audit_entry", 6000)
    infos: dict[str, dict] = {}
    rows = []
    ref: set[str] = set()
    for _, e in entries:
        p = e["payload"]
        if event and p.get("event") != event:
            continue
        if user and p.get("user") != user:
            continue
        if cutoff and p.get("ts", 0) < cutoff:
            continue
        allowed = [d for d in (p.get("retrieved") or p.get("docs") or [])]
        denied = list(p.get("denied") or [])
        ref.update(allowed + denied)
        rows.append((e, p, allowed, denied))
    infos = _doc_info(tx, ref)
    out = []
    for e, p, allowed, denied in rows:
        norm = lambda x: re.sub(r"[^a-z0-9]", "", str(x).lower())     # payment-gateway / Payment Gateway (PGW) / PGW 都认
        want = norm(container)

        def keep(i):
            inf = infos.get(i, {})
            return ((not platform or inf.get("platform") == platform) and (not want or want in norm(inf.get("container", "")) or want == norm(inf.get("space", ""))) and (not doc or doc.lower() in i.lower() or doc.lower() in inf.get("title", "").lower()))
        a = [i for i in allowed if keep(i)]
        dn = [i for i in denied if keep(i)]
        if (platform or container or doc) and not (a or dn):
            continue
        if decision == "allowed" and not a:
            continue
        if decision == "denied" and not dn:
            continue
        if visible is not None:   # 范围受限的审计员：不属于自己范围的文档不显示
            a = [i if i in visible else "[受限]" for i in a]
            dn = [i if i in visible else "[受限]" for i in dn]
        out.append({"ts": p.get("ts"), "user": p.get("user"), "event": p.get("event"), "status": p.get("status"), "question_hash": p.get("question_hash"),
                    "allowed": [infos.get(i, {"id": i, "title": "[受限]", "platform": "", "container": ""}) for i in a], "denied": [infos.get(i, {"id": i, "title": "[受限]", "platform": "", "container": ""}) for i in dn],
                    "synthetic": bool(p.get("synthetic")), "hash": e["hash"][:12]})
    out.sort(key=lambda r: -(r["ts"] or 0))
    return {"total": len(out), "rows": out[:max(1, min(limit, 500))], "scanned": len(entries)}


@router.get("/audit/query")
def audit_query_api(user: str = "", platform: str = "", container: str = "", doc: str = "", days: int = 0, decision: str = "", limit: int = 100, who=Depends(auditor)):
    with W.database.transaction() as tx:
        who = checked(tx, who, AUDIT_ROLES)
        from .audit.persistent import PersistentAudit
        result = audit_query(tx, who, user=user[:60], platform=platform[:20], container=container[:80], doc=doc[:120], days=max(0, min(days, 400)), decision=decision[:10], limit=limit)
        PersistentAudit(tx).append({"event": "audit.queried", "user": who.id, "filters": {k: v for k, v in dict(user=user, platform=platform, container=container, doc=doc, days=days, decision=decision).items() if v}})
        return result


class AuditAskBody(StrictBody):
    text: str = Field(min_length=2, max_length=400)


_AUDIT_PROMPT = ("Convert the compliance officer's audit question into a JSON filter. Keys (all optional): "
                 '"user" (login id such as jdoe), "platform" (confluence|jira|slack|drive), "container" (space key, project key, channel or drive name, e.g. payment-gateway or PGW), '
                 '"days" (integer window, e.g. last 30 days = 30), "decision" ("allowed" or "denied"), "doc" (a document id or title fragment). Return ONLY the JSON.')


def parse_audit_text(text: str, people: list[str]) -> dict:
    """把一句话的审计问法变成过滤条件：有模型用模型，没有就用规则。"""
    t = text.lower()
    f: dict = {}
    m = re.search(r"\b(" + "|".join(re.escape(p) for p in people) + r")\b", t)
    if m:
        f["user"] = m.group(1)
    for plat in PLATFORMS:
        if plat in t:
            f["platform"] = plat
    d = re.search(r"(\d+)\s*(?:days|day|天)", t) or re.search(r"last\s+(\d+)", t)
    if d:
        f["days"] = int(d.group(1))
    elif "last week" in t or "上周" in t:
        f["days"] = 7
    elif "last month" in t or "上个月" in t:
        f["days"] = 31
    if "denied" in t or "refused" in t or "拒绝" in t:
        f["decision"] = "denied"
    s = re.search(r"['\"“”‘’]?([a-z][a-z0-9\-]{3,40})['\"“”‘’]?\s+(?:confluence\s+)?(?:space|project|channel)", t)
    if s and s.group(1) not in ("the", "this", "that"):
        f["container"] = s.group(1)
    return f


@router.post("/audit/ask")
def audit_ask(body: AuditAskBody, who=Depends(auditor)):
    """一句话审计问法 → 过滤条件 → 查询。例：Show me everything user 'jdoe' accessed related to the 'payment-gateway' Confluence space in the last 30 days."""
    rt = company.RUNTIME
    people = [p.id for p in rt.hub.directory.people] if rt else []
    filters = parse_audit_text(body.text, people)
    via = "rules"
    key, base = llm_env()
    import os
    name = os.getenv("BUTLER_LLM_PLANNER_MODEL") or os.getenv("BUTLER_LLM_JUDGE_MODEL")
    if key and base.startswith("https://") and name:
        try:
            data = parse_json_object(RemoteModel(base, key, name, 400).complete(_AUDIT_PROMPT, body.text))
            llm = {k: v for k, v in data.items() if k in ("user", "platform", "container", "days", "decision", "doc") and v not in (None, "")}
            if llm.get("platform") in PLATFORMS or "platform" not in llm:
                filters, via = {**filters, **llm}, "llm"
        except Exception:   # noqa: BLE001 — 退回规则
            pass
    with W.database.transaction() as tx:
        who = checked(tx, who, AUDIT_ROLES)
        from .audit.persistent import PersistentAudit
        result = audit_query(tx, who, user=str(filters.get("user", ""))[:60], platform=str(filters.get("platform", ""))[:20], container=str(filters.get("container", ""))[:80],
                             doc=str(filters.get("doc", ""))[:120], days=int(filters.get("days") or 0), decision=str(filters.get("decision", ""))[:10])
        PersistentAudit(tx).append({"event": "audit.queried", "user": who.id, "filters": filters, "via": via, "nl": True})
    return {"filters": filters, "via": via, **result}


# ================= 赛题用例验收：自动执行并逐项断言 =================
SCENARIOS = [
    {"id": "s1", "title": "1 · 统一自然语言查询", "brief": "跨平台取权限过滤后的上下文，给出带引用的综合回答；私有频道只给在里面的人。",
     "steps": [
         {"kind": "ask", "as": "mliu", "q": "What's the status of the database migration project and were there any blockers raised in Slack last week?",
          "expect": [("cites_platforms", ["jira", "slack"]), ("not_cites_prefix", ["slack:CH-ATLASP"]), ("not_contains", ["18%", "contingency"]), ("contains_any", ["ATLAS-106", "CDC lag"])], "label": "Maya（不在领导层私有频道）问迁移状态与 Slack 阻塞"},
         {"kind": "ask", "as": "pete", "q": "What's the status of the database migration project and were there any blockers raised in Slack last week?",
          "expect": [("cites_prefix", ["slack:CH-ATLASP"]), ("contains_any", ["18%", "over the original estimate"])], "label": "Pete（在私有频道里）问同一个问题：多出预算超支"}]},
    {"id": "s2", "title": "2 · 数据新鲜度", "brief": "来源平台上刚更新的内容，在一次同步窗口内进入回答，而不是用早上的缓存。",
     "steps": [
         {"kind": "mutate", "action": "confluence.restore_page", "params": {"id": "9100"}, "label": "先把 runbook 还原到更新前"},
         {"kind": "ask", "as": "raj", "q": "What's the latest runbook for the payment-service incident? Include every step.", "expect": [("cites_prefix", ["confluence:9100"]), ("not_contains", ["Step 7"])], "label": "更新前：runbook 里没有第 7 步"},
         {"kind": "mutate", "action": "confluence.update_page", "params": {"id": "9100", "append": "### Step 7 — Fail over the ledger writer (added today)\nIf the ledger writer shows replication lag above 30 seconds or the writer instance is unhealthy, promote the standby in ap-southeast-1b with `ledger-failover promote --az ap-southeast-1b`, then restart payment-service with the new writer endpoint."}, "label": "On-call 在 Confluence 上追加第 7 步（故障切换）", "expect": [("sync_seconds_under", 60)]},
         {"kind": "ask", "as": "raj", "q": "What's the latest runbook for the payment-service incident? Include every step.", "expect": [("contains_any", ["Step 7", "ledger-failover"])], "label": "更新后：回答里有新增的第 7 步"}]},
    {"id": "s3", "title": "3 · 权限负例（不泄露存在性）", "brief": "没有权限时拒绝或过滤，回答与“根本没有这份资料”完全一样。",
     "steps": [
         {"kind": "ask", "as": "ken", "q": "Show me the security incident report from the Q3 breach", "expect": [("not_cites_prefix", ["confluence:9200", "drive:fH-FORENSICS", "drive:fH-Q3", "jira:SEC-"]), ("not_contains", ["3,412", "credential stuffing", "INC-SEC-0917"])], "label": "外包人员问 Q3 事件报告：内容不出现"},
         {"kind": "ask", "as": "jdoe", "q": "show me all security vulnerabilities", "expect": [("not_cites_prefix", ["confluence:9200", "jira:SEC-"]), ("not_contains", ["3,412"])], "label": "初级工程师问所有安全漏洞：看不到安全团队的页面和工单"},
         {"kind": "ask", "as": "sara", "q": "Show me the security incident report from the Q3 breach", "expect": [("cites_prefix", ["confluence:9200"]), ("contains_any", ["3,412"])], "label": "安全团队问同一个问题：能看到"}]},
    {"id": "s4", "title": "4 · 实时权限变更", "brief": "来源平台撤权后，下一次提问立刻不再返回不该看的内容（先实时复核，再由同步追平快照）。",
     "steps": [
         {"kind": "mutate", "action": "slack.add_member", "params": {"channel": "CH-SETTLE", "user": "alice"}, "label": "先确保 Alice 在私有频道里"},
         {"kind": "ask", "as": "alice", "q": "Why was the settlement batch delayed on Oct 12 and what's the workaround?", "expect": [("cites_prefix", ["slack:CH-SETTLE"])], "label": "撤权前：回答里有私有频道的细节"},
         {"kind": "mutate", "action": "slack.remove_member", "params": {"channel": "CH-SETTLE", "user": "alice"}, "label": "管理员把 Alice 移出 #settlement-war-room", "expect": [("sync_seconds_under", 60)]},
         {"kind": "ask", "as": "alice", "q": "Why was the settlement batch delayed on Oct 12 and what's the workaround?", "expect": [("not_cites_prefix", ["slack:CH-SETTLE"]), ("not_contains", ["18,402"])], "label": "撤权后：私有频道的内容不再出现"},
         {"kind": "mutate", "action": "slack.add_member", "params": {"channel": "CH-SETTLE", "user": "alice"}, "label": "还原：把 Alice 加回频道"}]},
    {"id": "s5", "title": "5 · 审计查询", "brief": "合规官还原：谁、什么时候、问了什么、检索到哪些文档、每份文档的授权决定。",
     "steps": [
         {"kind": "audit", "as": "amy", "text": "Show me everything user 'jdoe' accessed related to the 'payment-gateway' Confluence space in the last 30 days.", "expect": [("rows_at_least", 10), ("filters_include", {"user": "jdoe", "platform": "confluence", "days": 30})], "label": "合规官用一句话查 jdoe 在 payment-gateway 空间 30 天的访问"},
         {"kind": "audit", "as": "amy", "text": "Which attempts were denied for user ken?", "expect": [("denied_at_least", 1)], "label": "查外包人员被拒绝的访问尝试"},
         {"kind": "verify", "as": "amy", "expect": [("chain_ok", True)], "label": "校验审计哈希链完整"}]},
    {"id": "s6", "title": "6 · CTO 的两个示例问题", "brief": "跨 Confluence / Jira / Slack 的复盘与设计讨论汇总。",
     "steps": [
         {"kind": "ask", "as": "alice", "q": "What was the root cause of the payment outage last quarter, and what follow-up tickets were created?", "expect": [("cites_prefix", ["confluence:9400"]), ("cites_prefix", ["jira:PAY-900"]), ("contains_any", ["connection pool", "pool"])], "label": "上季度支付故障的根因与后续工单"},
         {"kind": "ask", "as": "alice", "q": "Summarize the design discussion around the new auth service from last sprint's Slack threads and link the Confluence decision doc.", "expect": [("cites_prefix", ["slack:CH-AUTH"]), ("cites_prefix", ["confluence:9500"])], "label": "认证服务设计讨论摘要 + 决策文档链接"}]},
    {"id": "s7", "title": "7 · 多模态", "brief": "图片 / 扫描 PDF / 录音里的内容被识别入库，权限与来源文档一致。",
     "steps": [
         {"kind": "ask", "as": "alice", "q": "What does the payment gateway architecture diagram show?", "expect": [("cites_modality", ["image"]), ("contains_any", ["api-gateway", "ledger"])], "label": "问架构图里画了什么（图像识别文本）"},
         {"kind": "ask", "as": "alice", "q": "What was said on the incident bridge call about the root cause?", "expect": [("cites_modality", ["audio"]), ("contains_any", ["pool", "fifty"])], "label": "问事故电话会议里说了什么（语音转写）"},
         {"kind": "ask", "as": "grace", "q": "What does the Acme Cloud MSA say about early termination fees?", "expect": [("cites_modality", ["pdf"]), ("contains_any", ["25%", "90 days"])], "label": "财务官问合同扫描件里的违约金条款（OCR）"},
         {"kind": "ask", "as": "ken", "q": "What does the Acme Cloud MSA say about early termination fees?", "expect": [("not_cites_prefix", ["drive:fH-MSA"]), ("not_contains", ["25%"])], "label": "外包人员问同一个问题：看不到"}]},
]


def _judge(answer: dict, expect: list, extra: dict | None = None) -> list[dict]:
    text = (answer or {}).get("text", "")
    low = text.lower()
    cites = [c["id"] for c in (answer or {}).get("citations", [])]
    mods = {c.get("modality") for c in (answer or {}).get("citations", [])}
    plats = {c["id"].split(":")[0] for c in (answer or {}).get("citations", [])}
    out = []
    for kind, arg in expect:
        ex = extra or {}
        if kind == "cites_prefix":
            ok, label = any(c.startswith(p) for p in arg for c in cites), f"引用了 {' / '.join(arg)}"
        elif kind == "not_cites_prefix":
            ok, label = not any(c.startswith(p) for p in arg for c in cites), f"没有引用 {' / '.join(arg)}"
        elif kind == "cites_platforms":
            ok, label = all(p in plats for p in arg), f"同时引用了 {' + '.join(arg)}"
        elif kind == "cites_modality":
            ok, label = any(m in mods for m in arg), f"引用了 {' / '.join(arg)} 模态的资料"
        elif kind == "contains_any":
            ok, label = any(a.lower() in low for a in arg), f"回答里包含 {' / '.join(repr(a) for a in arg)}"
        elif kind == "not_contains":
            ok, label = not any(a.lower() in low for a in arg), f"回答里不包含 {' / '.join(repr(a) for a in arg)}"
        elif kind == "sync_seconds_under":
            ok, label = ex.get("sync_seconds", 999) < arg, f"来源变更在 {arg} 秒内进入索引（实测 {ex.get('sync_seconds', '—')} 秒）"
        elif kind == "rows_at_least":
            ok, label = ex.get("total", 0) >= arg, f"至少 {arg} 条访问记录（实际 {ex.get('total', 0)}）"
        elif kind == "denied_at_least":
            ok, label = sum(1 for r in ex.get("rows", []) if r["denied"]) >= arg, f"至少 {arg} 条被拒绝的记录"
        elif kind == "filters_include":
            ok, label = all(str(ex.get("filters", {}).get(k)) == str(v) for k, v in arg.items()), "一句话被正确解析成过滤条件 " + ", ".join(f"{k}={v}" for k, v in arg.items())
        elif kind == "chain_ok":
            ok, label = bool(ex.get("chain_ok")) == arg, "审计哈希链校验通过"
        else:
            ok, label = False, kind
        out.append({"label": label, "ok": bool(ok)})
    return out


@router.get("/scenarios")
def scenarios_list(who=Depends(current)):
    return [{"id": s["id"], "title": s["title"], "brief": s["brief"], "steps": [{"label": st["label"], "kind": st["kind"], "as": st.get("as"), "q": st.get("q") or st.get("text")} for st in s["steps"]]} for s in SCENARIOS]


@router.post("/scenarios/{scenario_id}/run")
def scenarios_run(scenario_id: str, who=Depends(admin)):
    """依次执行一个用例的所有步骤（真实提问、真实变更、真实同步），逐项断言，按行流式返回。需要管理权限，因为会改来源平台。"""
    import uuid
    from fastapi.responses import StreamingResponse
    sc = next((s for s in SCENARIOS if s["id"] == scenario_id), None)
    if sc is None:
        raise HTTPException(404, "没有这个用例。")
    rt = _runtime()
    with W.database.transaction() as tx:
        checked(tx, who, ADMIN_ROLES)

    def identity_of(uid: str):
        with W.database.transaction() as tx:
            row = tx.get("member", uid)
        if not row:
            raise HTTPException(404, f"没有账号 {uid}")
        return W.identity(row)

    def run():
        passed = 0
        for i, st in enumerate(sc["steps"]):
            yield json.dumps({"event": "step", "i": i, "label": st["label"], "kind": st["kind"], "as": st.get("as"), "q": st.get("q") or st.get("text"), "status": "running"}, ensure_ascii=False) + "\n"
            t0 = time.time()
            answer, extra = None, {}
            try:
                if st["kind"] == "ask":
                    sid = f"scn-{uuid.uuid4().hex[:10]}"
                    answer = W._ask(W.AskBody(question=st["q"], session_id=sid), identity_of(st["as"]))
                    with W.database.transaction() as tx:      # 验收用的会话不留在用户的历史里
                        tx.delete("conversation", f"{st['as']}:{sid}")
                elif st["kind"] == "mutate":
                    r = rt.apply(st["action"], st["params"], actor=f"scenario:{scenario_id}")
                    extra["sync_seconds"] = round(time.time() - t0, 2)
                elif st["kind"] == "audit":
                    who2 = identity_of(st["as"])
                    people = [p.id for p in rt.hub.directory.people]
                    filters = parse_audit_text(st["text"], people)
                    if "denied" in st["text"].lower():
                        filters["decision"] = "denied"
                    with W.database.transaction() as tx:
                        res = audit_query(tx, who2, user=filters.get("user", ""), platform=filters.get("platform", ""), container=filters.get("container", ""), days=int(filters.get("days") or 0), decision=filters.get("decision", ""))
                    extra = {**res, "filters": filters}
                elif st["kind"] == "verify":
                    from .audit.chain import verify
                    with W.database.transaction() as tx:
                        ok, _ = verify(tx.iter("audit_entry"), tx.get("meta", "audit_head")["hash"])
                    extra["chain_ok"] = ok
                checks = _judge(answer, st.get("expect", []), extra)
                ok = all(c["ok"] for c in checks) if checks else True
                passed += ok
                payload = {"event": "result", "i": i, "status": "pass" if ok else "fail", "seconds": round(time.time() - t0, 1), "checks": checks}
                if answer:
                    payload["answer"] = {"text": answer["text"], "status": answer.get("status"), "citations": [{"id": c["id"], "title": c["title"], "source": c["source"], "modality": c.get("modality")} for c in answer["citations"]], "trace": answer.get("trace")}
                if st["kind"] == "audit":
                    payload["audit"] = {"filters": extra.get("filters"), "total": extra.get("total"), "sample": extra.get("rows", [])[:3]}
                yield json.dumps(payload, ensure_ascii=False) + "\n"
            except HTTPException as error:
                yield json.dumps({"event": "result", "i": i, "status": "fail", "seconds": round(time.time() - t0, 1), "checks": [{"label": str(error.detail), "ok": False}]}, ensure_ascii=False) + "\n"
            except Exception as error:   # noqa: BLE001
                yield json.dumps({"event": "result", "i": i, "status": "fail", "seconds": round(time.time() - t0, 1), "checks": [{"label": f"执行失败：{type(error).__name__}", "ok": False}]}, ensure_ascii=False) + "\n"
        yield json.dumps({"event": "done", "passed": passed, "total": len(sc["steps"])}) + "\n"

    return StreamingResponse(run(), media_type="application/x-ndjson", headers={"cache-control": "no-store"})
