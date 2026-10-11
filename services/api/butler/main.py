import os
from typing import Optional

import secrets
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .acl.policy import can_read
from .answer.mosaic import KeywordJudge
from .answer.pipeline import answer_question
from .answer.session import SessionStore
from .audit.chain import AuditLog, verify
from .connectors.fake import DATA_SOURCE, load_world
from .identity import registry
from .models import Identity
from .redteam.eval import load_cases, run_eval
from .retrieval.store import Store
from .workspace import MODE, database, router as workspace_router

app = FastAPI(title="Butler")
app.include_router(workspace_router)


@app.middleware("http")
async def enterprise_boundary(request: Request, call_next):
    if MODE == "enterprise" and request.url.path != "/health":
        if not request.url.path.startswith("/workspace/"):
            return JSONResponse({"detail": "公开演示接口已关闭。"}, status_code=404)
        expected = f"Bearer {os.environ['BUTLER_INTERNAL_TOKEN']}"
        if not secrets.compare_digest(request.headers.get("authorization", "").encode(), expected.encode()):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return await call_next(request)
_identities, _docs, _facts = load_world() if MODE == "demo" else ([], [], [])
registry.load(_identities)
store, audit, judge, sessions = Store(_docs), AuditLog(), KeywordJudge(), SessionStore()
_doc_by_id = {d.id: d for d in _docs}
# 演示开关：篡改日志、左右对比这类接口只在离线演示数据下开放
DEMO = MODE == "demo"
AUDIT_ROLES = {"auditor", "security"}


class AskBody(BaseModel):
    identity_id: str
    question: str
    session_id: Optional[str] = None


class SessionBody(BaseModel):
    session_id: str


class TamperBody(BaseModel):
    index: int


def _who(identity_id: str) -> Identity:
    try:
        return registry.get(identity_id)  # 身份由服务端绑定，模型不能指定 user_id
    except KeyError:
        raise HTTPException(404, "unknown identity")


def _require_demo() -> None:
    if not DEMO:
        raise HTTPException(403, "demo endpoints are disabled with real data")


def _cite(ids: list[str]) -> list[dict]:
    return [{"id": i, "source": _doc_by_id[i].source, "title": _doc_by_id[i].title} for i in ids]


def _ask(who: Identity, body: AskBody, guard: bool, session_key: Optional[str]):
    session = sessions.get(session_key, who.id) if session_key else None
    return answer_question(who, body.question, store, _facts, judge, audit, guard=guard, session=session)


@app.get("/health")
def health():
    try:
        with database.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(503, "database unavailable")
    return {"ok": True, "data_source": DATA_SOURCE if DEMO else "workspace", "demo": DEMO, "mode": MODE}


@app.get("/identities")
def identities():
    return [{"id": i.id, "name": i.name, "role": i.role, "groups": sorted(i.groups)}
            for i in registry.all_identities()]


@app.get("/sources")
def sources(identity_id: str):
    """提问者能看到哪些文档（只列标题），界面用来解释“为什么答案里没有某样东西”。"""
    who = _who(identity_id)
    visible = store.visible(who)
    return {"total": len(_docs), "visible": len(visible), "docs": _cite([d.id for d in visible]),
            "data_source": DATA_SOURCE}


@app.post("/ask")
def ask(body: AskBody):
    who = _who(body.identity_id)
    a = _ask(who, body, guard=True, session_key=body.session_id)
    # 不返回 degraded / blocked_facts：提问者不应分辨出“这里有秘密”
    return {"text": a.text, "citations": _cite(a.citations), "latency_ms": a.latency_ms,
            "data_source": DATA_SOURCE}


@app.post("/compare")
def compare(body: AskBody):
    """演示用：同一问题分别走“文档级权限 RAG”和 Butler，左右分屏展示。只暴露受限事实的 ID。"""
    _require_demo()
    who = _who(body.identity_id)
    out = {}
    for name, guard in (("baseline", False), ("butler", True)):
        key = f"{body.session_id}:{name}" if body.session_id else None
        a = _ask(who, body, guard=guard, session_key=key)
        out[name] = {"text": a.text, "citations": _cite(a.citations), "degraded": a.degraded,
                     "blocked_facts": a.blocked_facts, "latency_ms": a.latency_ms, "guard_ms": a.guard_ms}
    return {**out, "data_source": DATA_SOURCE}


@app.post("/session/reset")
def session_reset(body: SessionBody):
    for key in (body.session_id, f"{body.session_id}:baseline", f"{body.session_id}:butler"):
        sessions.reset(key)
    return {"ok": True}


@app.get("/audit")
def audit_list(viewer_id: str, user: Optional[str] = None, limit: int = 100):
    """审计查询。审计员也有范围：自己无权读的文档只显示为“受限”。"""
    viewer = _who(viewer_id)
    if viewer.role not in AUDIT_ROLES:
        raise HTTPException(403, "only auditors and security can read the audit log")
    rows = []
    for i, e in enumerate(audit.entries):
        p = e["payload"]
        if user and p.get("user") != user:
            continue
        docs = [d if d in _doc_by_id and can_read(viewer, _doc_by_id[d]) else "[受限]" for d in p.get("docs", [])]
        rows.append({"index": i, "prev_hash": e["prev_hash"], "hash": e["hash"], "payload": {**p, "docs": docs}})
    return {"entries": rows[-limit:], "length": len(audit.entries)}


@app.get("/audit/verify")
def audit_verify():
    ok, bad = verify(audit.entries, audit.checkpoint())
    return {"ok": ok, "first_bad_index": bad, "length": len(audit.entries)}


@app.post("/audit/tamper")
def audit_tamper(body: TamperBody):
    """演示用：偷偷改一条日志，展示哈希链从这一环起断开。"""
    _require_demo()
    if not 0 <= body.index < len(audit.entries):
        raise HTTPException(400, "index out of range")
    audit.entries[body.index]["payload"]["degraded"] = not audit.entries[body.index]["payload"].get("degraded")
    return audit_verify()


@app.post("/demo/reset")
def demo_reset():
    """演示用：清空审计日志和会话，重新开始一场演示。"""
    _require_demo()
    global audit, sessions
    audit, sessions = AuditLog(), SessionStore()
    return {"ok": True}


@app.get("/eval/cases")
def eval_cases():
    return load_cases()


@app.get("/eval")
def eval_report():
    r = run_eval({i.id: i for i in registry.all_identities()}, _docs, _facts, load_cases())
    return {**r, "judge": type(judge).__name__, "generator": "simulated", "data_source": DATA_SOURCE}
