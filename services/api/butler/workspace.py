"""Authenticated, persistent workspace. Public demonstration uses a different runtime."""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, ConfigDict

from .acl.policy import can_read
from .answer.mosaic import KeywordJudge
from .answer.pipeline import answer_question
from .answer.remote import ModelFailure, RemoteJudge, RemoteModel
from .answer.session import Session
from .audit.chain import GENESIS, _h, verify
from .audit.checkpoint import sign_checkpoint
from .connectors.fake import load_world
from .database import Database
from .models import Doc, Fact, Identity
from . import passwords
from .retrieval.store import Store

ADMIN_ROLES = {"admin", "security"}
AUDIT_ROLES = ADMIN_ROLES | {"auditor"}
MODE = os.getenv("BUTLER_MODE", "demo")
if MODE not in {"demo", "enterprise"}:
    raise RuntimeError("BUTLER_MODE must be demo or enterprise")
_local = Path(__file__).resolve().parents[3] / ".runtime"
_local.mkdir(exist_ok=True)
url = os.getenv("DATABASE_URL") if MODE == "enterprise" else os.getenv("BUTLER_DEMO_DATABASE_URL")
if MODE == "enterprise" and (not url or not url.startswith("postgresql")):
    raise RuntimeError("Enterprise mode requires a PostgreSQL DATABASE_URL")
if MODE == "enterprise" and len(os.getenv("BUTLER_INTERNAL_TOKEN", "")) < 32:
    raise RuntimeError("Enterprise mode requires BUTLER_INTERNAL_TOKEN (32+ characters)")
if passwords.auth_mode() not in {"local", "oidc"}:
    raise RuntimeError("BUTLER_AUTH_MODE must be local or oidc")
if MODE == "enterprise" and passwords.auth_mode() == "oidc" and (not os.getenv("BUTLER_OIDC_ISSUER", "").startswith("https://") or not os.getenv("BUTLER_BOOTSTRAP_ADMIN_SUB")):
    raise RuntimeError("Enterprise mode requires an HTTPS BUTLER_OIDC_ISSUER and BUTLER_BOOTSTRAP_ADMIN_SUB")
database = Database(url or f"sqlite:///{_local / 'workspace-demo.sqlite'}")
router = APIRouter(prefix="/workspace")


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Settings(StrictBody):
    organization: str = Field(min_length=1, max_length=80)
    generation_model: str = Field(default="", max_length=100)
    judge_model: str = Field(default="", max_length=100)
    max_tokens: int = Field(default=1200, ge=256, le=4096)


class MemberBody(StrictBody):
    role: Literal["admin", "security", "auditor", "employee", "engineer", "contractor", "pm"]
    groups: list[str] = Field(max_length=50)
    active: bool = True


class DocumentBody(StrictBody):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[\w.-]+$")
    source: Literal["slack", "confluence", "jira", "drive", "upload"] = "upload"
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=50000)
    acl: list[str] = Field(min_length=1, max_length=50)


class FactBody(StrictBody):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[\w.-]+$")
    source_doc: str = Field(min_length=1, max_length=128)
    statement: str = Field(min_length=1, max_length=2000)


class ImportBody(StrictBody):
    documents: list[DocumentBody] = Field(min_length=1, max_length=200)
    facts: list[FactBody] = Field(default_factory=list, max_length=500)


class AskBody(StrictBody):
    question: str = Field(min_length=1, max_length=4000)
    session_id: str = Field(min_length=1, max_length=128, pattern=r"^[\w:-]+$")


class ProvisionBody(StrictBody):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    issuer: str = Field(min_length=1, max_length=500)
    subject: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=100)


def identity(row):
    return Identity(row["id"], row["name"], frozenset(row["groups"]), row["role"])


def documents(tx):
    return [Doc(d["id"], d["source"], d["title"], d["text"], frozenset(d["acl"])) for d in tx.all("document")]


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def facts(tx):
    # 事实绑定来源正文的版本：正文变了而事实没重新登记，旧事实不再参与检查也不再有效
    current = {d["id"]: d.get("content_hash") or text_hash(d["text"]) for d in tx.all("document")}
    return [Fact(f["id"], f["source_doc"], frozenset(f["acl"]), f["statement"], tuple(f.get("keywords", []))) for f in tx.all("fact")
            if f["source_doc"] in current and f.get("content_hash", current[f["source_doc"]]) == current[f["source_doc"]]]


def bootstrap(db):
    with db.transaction() as tx:
        deployment = tx.get("meta", "deployment_mode")
        if deployment and deployment["value"] != MODE:
            raise RuntimeError("Demo and enterprise must use separate databases")
        if not deployment and MODE == "enterprise" and tx.get("settings", "main"):
            raise RuntimeError("Existing unclassified database requires an explicit migration")
        tx.put("meta", "deployment_mode", {"value": MODE})
        if tx.get("meta", "audit_head") is None:
            old = tx.get("audit", "chain", {"entries": [], "checkpoint": GENESIS})
            for index, entry in enumerate(old["entries"]):
                tx.put("audit_entry", f"{index:020d}", entry)
            tx.put("meta", "audit_head", {"count": len(old["entries"]), "hash": old["checkpoint"]})
            tx.delete("audit", "chain")
        if tx.get("settings", "main") is not None:
            return
        tx.put("settings", "main", Settings(organization="Tidepool Pay" if MODE == "demo" else "Butler 工作区").model_dump())
        tx.put("meta", "revision", {"value": 1})
        if MODE == "demo":
            people, docs, restricted = load_world()
            for person in people:
                tx.put("member", person["id"], {**person, "active": True})
            for doc in docs:
                tx.put("document", doc.id, {**asdict(doc), "acl": sorted(doc.acl)})
            for fact in restricted:
                tx.put("fact", fact.id, {**asdict(fact), "acl": sorted(fact.acl), "keywords": list(fact.keywords)})


bootstrap(database)
passwords.bootstrap(database)


def current(x_butler_identity: Optional[str] = Header(default=None)):
    if not x_butler_identity:
        raise HTTPException(401, "请先登录。")
    with database.transaction() as tx:
        row = tx.get("member", x_butler_identity)
        if not row or not row.get("active"):
            raise HTTPException(401, "账号已停用或不存在。")
        return identity(row)


def admin(who=Depends(current)):
    if who.role not in ADMIN_ROLES:
        raise HTTPException(403, "需要管理员权限。")
    return who


def auditor(who=Depends(current)):
    if who.role not in AUDIT_ROLES:
        raise HTTPException(403, "需要审计权限。")
    return who


def checked(tx, who, roles=None):
    """Authorize again inside the mutation/read transaction, closing revocation races."""
    row = tx.get("member", who.id)
    if not row or not row.get("active"):
        raise HTTPException(401, "账号已停用或不存在。")
    fresh = identity(row)
    if roles is not None and fresh.role not in roles:
        raise HTTPException(403, "账号权限已更新。")
    return fresh


def revision(tx, who):
    groups_hash = hashlib.sha256(json.dumps(sorted(who.groups), ensure_ascii=False).encode()).hexdigest()
    return f"{tx.get('meta', 'revision')['value']}:{groups_hash}"


def cite(docs):
    return [{"id": d.id, "source": d.source, "title": d.title} for d in docs]


class PersistentAudit:
    def __init__(self, tx):
        self.tx = tx
        self.head = tx.get("meta", "audit_head")

    def append(self, payload):
        payload = {**payload, "ts": payload.get("ts", time.time())}
        entry = {"prev_hash": self.head["hash"], "payload": payload, "hash": _h(self.head["hash"], payload)}
        self.tx.put("audit_entry", f"{self.head['count']:020d}", entry)
        self.head = {"hash": entry["hash"], "count": self.head["count"] + 1}
        self.tx.put("meta", "audit_head", self.head)
        return entry

    def checkpoint(self):
        return self.head["hash"]


@router.post("/provision")
def provision(body: ProvisionBody):
    # Only the BFF, after ID-token verification, may call this internal route.
    if MODE != "enterprise" or passwords.auth_mode() != "oidc" or body.issuer != os.getenv("BUTLER_OIDC_ISSUER"):
        raise HTTPException(403, "企业登录未配置。")
    key = hashlib.sha256(f"{body.issuer}\0{body.subject}".encode()).hexdigest()
    with database.transaction() as tx:
        row = tx.get("member", key)
        if not row:
            bootstrap_subject = os.getenv("BUTLER_BOOTSTRAP_ADMIN_SUB")
            row = {"id": key, "name": body.name, "groups": [], "active": True,
                   "role": "admin" if bootstrap_subject and body.subject == bootstrap_subject else "employee"}
        if not row["active"]:
            raise HTTPException(403, "账号已停用。")
        row["name"] = body.name
        tx.put("member", key, row)
        return row


@router.get("/me")
def me(who=Depends(current)):
    with database.transaction() as tx:
        who = checked(tx, who)
        row = tx.get("member", who.id)
        return {"id": who.id, "name": who.name, "role": who.role, "groups": sorted(who.groups),
                "session_version": row.get("session_version", 0), "username": row.get("username")}


@router.get("/status")
def status(who=Depends(current)):
    with database.transaction() as tx:
        who = checked(tx, who)
        settings = tx.get("settings", "main")
        docs = documents(tx)
        configured = bool(os.getenv("HUNYUAN_API_KEY") and settings["generation_model"] and settings["judge_model"])
        return {"organization": settings["organization"], "mode": MODE, "auth_mode": passwords.auth_mode(), "database": database.engine.dialect.name,
                "model_ready": MODE == "demo" or configured,
                "visible_documents": len([d for d in docs if can_read(who, d)]),
                "conversations": len([c for c in tx.all("conversation") if c["owner"] == who.id]),
                "audit_entries": tx.get("meta", "audit_head")["count"] if who.role in AUDIT_ROLES else None,
                "can_admin": who.role in ADMIN_ROLES, "can_audit": who.role in AUDIT_ROLES}


@router.get("/settings")
def settings_get(who=Depends(admin)):
    with database.transaction() as tx:
        who = checked(tx, who, ADMIN_ROLES)
        return {**tx.get("settings", "main"), "mode": MODE,
                "model_key_configured": bool(os.getenv("HUNYUAN_API_KEY")),
                "model_base_url": os.getenv("HUNYUAN_BASE_URL", "https://api.hunyuan.cloud.tencent.com/v1"),
                "oidc_configured": bool(os.getenv("BUTLER_OIDC_ISSUER")),
                "auth_mode": passwords.auth_mode(),
                "database": database.engine.dialect.name}


@router.put("/settings")
def settings_put(body: Settings, who=Depends(admin)):
    with database.transaction() as tx:
        who = checked(tx, who, ADMIN_ROLES)
        tx.put("settings", "main", body.model_dump())
        PersistentAudit(tx).append({"event": "settings.updated", "user": who.id})
    return {"ok": True}


@router.get("/members")
def members(who=Depends(admin)):
    with database.transaction() as tx:
        who = checked(tx, who, ADMIN_ROLES)
        return tx.all("member")


class PasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=128)


class LoginBody(PasswordBody):
    username: str = Field(min_length=1, max_length=80)


class CreateMemberBody(LoginBody):
    name: str = Field(min_length=1, max_length=100)


class ChangePasswordBody(PasswordBody):
    current_password: str = Field(min_length=1, max_length=128)


def local_only():
    if passwords.auth_mode() != "local":
        raise HTTPException(403, "当前使用统一身份登录。")


def new_password(value):
    try:
        return passwords.credential(value)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error


@router.post("/auth/password")
def password_login(body: LoginBody):
    # Anonymous only at the web server; enterprise API still requires the BFF token.
    local_only()
    login = body.username.strip().lower()
    result, limited = None, False
    with database.transaction() as tx:
        stored = tx.get("credential", login)
        if not passwords.consume_attempt(tx, "global", 30, 60):
            limited = True
        elif stored and not passwords.consume_attempt(tx, "account:" + login):
            limited = True
        else:
            valid = passwords.matches(body.password, stored)
            row = tx.get("member", stored["member"]) if stored else None
            if valid and row and row["active"]:
                tx.delete("login_limit", "account:" + login)
                result = row
                PersistentAudit(tx).append({"event": "auth.login", "user": row["id"]})
    # Raise after commit: failed attempts must persist too.
    if limited:
        raise HTTPException(429, "尝试次数过多，请稍后再试。")
    if not result:
        raise HTTPException(401, "账号或密码不正确，或账号已停用。")
    return result


@router.post("/members")
def member_create(body: CreateMemberBody, who=Depends(admin)):
    local_only()
    try:
        login = passwords.username(body.username)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if not body.name.strip():
        raise HTTPException(422, "请填写姓名。")
    stored = new_password(body.password)
    with database.transaction() as tx:
        who = checked(tx, who, ADMIN_ROLES)
        if tx.get("credential", login):
            raise HTTPException(409, "账号已存在。")
        key = "local-" + hashlib.sha256(login.encode()).hexdigest()
        row = {"id": key, "name": body.name.strip(), "username": login, "role": "employee", "groups": [], "active": True, "session_version": 1}
        tx.put("member", key, row)
        tx.put("credential", login, {**stored, "member": key})
        PersistentAudit(tx).append({"event": "member.created", "user": who.id, "member": key})
    return row


def replace_password(tx, row, stored):
    tx.put("credential", row["username"], {**stored, "member": row["id"]})
    tx.put("member", row["id"], {**row, "session_version": row.get("session_version", 0) + 1})
    tx.delete("login_limit", "account:" + row["username"])
    tx.delete("login_limit", "change:" + row["id"])


@router.put("/account/password")
def password_change(body: ChangePasswordBody, who=Depends(current)):
    local_only()
    stored = new_password(body.password)
    success, limited = False, False
    with database.transaction() as tx:
        who = checked(tx, who)
        row = tx.get("member", who.id)
        if not row.get("username"):
            raise HTTPException(403, "这个账号没有本地密码。")
        if not passwords.consume_attempt(tx, "change:" + who.id):
            limited = True
        elif passwords.matches(body.current_password, tx.get("credential", row["username"])):
            replace_password(tx, row, stored)
            PersistentAudit(tx).append({"event": "auth.password_changed", "user": who.id})
            success = True
    if limited:
        raise HTTPException(429, "尝试次数过多，请稍后再试。")
    if not success:
        raise HTTPException(400, "当前密码不正确。")
    return {"ok": True}


@router.put("/members/{key}/password")
def password_reset(key: str, body: PasswordBody, who=Depends(admin)):
    local_only()
    stored = new_password(body.password)
    with database.transaction() as tx:
        who = checked(tx, who, ADMIN_ROLES)
        row = tx.get("member", key)
        if not row or not row.get("username"):
            raise HTTPException(404, "本地账号不存在。")
        if key == who.id:
            raise HTTPException(409, "请在账号设置中修改自己的密码。")
        replace_password(tx, row, stored)
        PersistentAudit(tx).append({"event": "auth.password_reset", "user": who.id, "member": key})
    return {"ok": True}


@router.put("/members/{key}")
def member_put(key: str, body: MemberBody, who=Depends(admin)):
    groups = sorted({g.strip() for g in body.groups if g.strip()})
    if any(len(g) > 80 for g in groups):
        raise HTTPException(422, "权限组名称过长。")
    with database.transaction() as tx:
        who = checked(tx, who, ADMIN_ROLES)
        row = tx.get("member", key)
        if not row:
            raise HTTPException(404, "成员不存在。")
        if key == who.id and (not body.active or body.role not in ADMIN_ROLES):
            raise HTTPException(409, "不能移除自己的管理权限。")
        version = row.get("session_version", 0) + (1 if row["active"] != body.active else 0)
        tx.put("member", key, {**row, **body.model_dump(), "groups": groups, "session_version": version})
        PersistentAudit(tx).append({"event": "member.updated", "user": who.id, "member": key})
    return {"ok": True}


@router.get("/sources")
def sources(who=Depends(current)):
    with database.transaction() as tx:
        who = checked(tx, who)
        visible = Store(documents(tx)).visible(who)
        return {"visible": len(visible), "docs": cite(visible)}


@router.get("/knowledge")
def knowledge(who=Depends(admin)):
    with database.transaction() as tx:
        who = checked(tx, who, ADMIN_ROLES)
        return {"documents": [{k: v for k, v in d.items() if k != "text"} for d in tx.all("document")],
                "facts": len(tx.all("fact")), "revision": tx.get("meta", "revision")["value"]}


@router.post("/knowledge/import")
def knowledge_import(body: ImportBody, who=Depends(admin)):
    with database.transaction() as tx:
        who = checked(tx, who, ADMIN_ROLES)
        docs = {d["id"]: d for d in tx.all("document")}
        if len({d.id for d in body.documents}) != len(body.documents) or len({f.id for f in body.facts}) != len(body.facts):
            raise HTTPException(422, "同一次导入不能包含重复编号。")
        changed_docs: set[str] = set()
        for doc in body.documents:
            data = doc.model_dump()
            data["acl"] = sorted({g.strip() for g in doc.acl if g.strip()})
            if not data["acl"]:
                raise HTTPException(422, "资料必须设置可读权限组。")
            data["content_hash"] = text_hash(doc.text)
            old = docs.get(doc.id)
            if old and (old.get("content_hash") or text_hash(old["text"])) != data["content_hash"]:
                changed_docs.add(doc.id)
            docs[doc.id] = data
            tx.put("document", doc.id, data)
        supplied = {f.id for f in body.facts}
        for fact in tx.all("fact"):
            # 正文已变：旧版本派生的事实整体失效，只保留本次重新登记的
            if fact["source_doc"] in changed_docs and fact["id"] not in supplied:
                tx.delete("fact", fact["id"])
        for fact in body.facts:
            if fact.source_doc not in docs:
                raise HTTPException(422, "受限事实必须关联已有资料。")
            tx.put("fact", fact.id, {**fact.model_dump(), "acl": docs[fact.source_doc]["acl"], "keywords": [],
                                 "content_hash": docs[fact.source_doc]["content_hash"]})
        # Updating a source ACL must also update all inherited fact ACLs.
        for fact in tx.all("fact"):
            if fact["source_doc"] in docs:
                tx.put("fact", fact["id"], {**fact, "acl": docs[fact["source_doc"]]["acl"]})
        rev = tx.get("meta", "revision")["value"] + 1
        tx.put("meta", "revision", {"value": rev})
        PersistentAudit(tx).append({"event": "knowledge.imported", "user": who.id, "count": len(body.documents)})
    return {"ok": True, "documents": len(body.documents), "facts": len(body.facts), "revision": rev}


@router.get("/conversations")
def conversations(who=Depends(current)):
    with database.transaction() as tx:
        who = checked(tx, who)
        return [{"id": c["id"], "title": c["title"], "updated": c["updated"],
                 "stale": c["revision"] != revision(tx, who)}
                for c in sorted(tx.all("conversation"), key=lambda c: -c["updated"]) if c["owner"] == who.id]


@router.get("/conversations/{key}")
def conversation_get(key: str, who=Depends(current)):
    with database.transaction() as tx:
        who = checked(tx, who)
        c = tx.get("conversation", f"{who.id}:{key}")
        if not c:
            raise HTTPException(404, "会话不存在。")
        # A saved answer can become unauthorized after ACL/content changes.
        # Invalidate rather than returning old text/citations under new permissions.
        if c["revision"] != revision(tx, who):
            return {"id": key, "turns": [], "stale": True}
        return {"id": key, "turns": c["turns"], "stale": False}


@router.post("/ask")
def ask(body: AskBody, who=Depends(current)):
    with database.transaction() as tx:
        row = tx.get("member", who.id)
        if not row or not row["active"]:
            raise HTTPException(401, "账号已停用。")
        who = identity(row)  # Re-read under the same lock as the answer.
        key = f"{who.id}:{body.session_id}"
        rev = revision(tx, who)
        c = tx.get("conversation", key)
        if c and c["revision"] != rev:
            raise HTTPException(409, "资料或权限已更新，请新建会话。")
        if c and len(c["turns"]) >= 30:
            raise HTTPException(409, "此会话已达 30 轮，请新建会话。")
        session = Session(who.id, c["doc_ids"] if c else [], c["claims"] if c else [])
        settings = tx.get("settings", "main")
        options = {}
        judge = KeywordJudge()
        if MODE == "enterprise":
            key_value = os.getenv("HUNYUAN_API_KEY")
            if not key_value or not settings["generation_model"] or not settings["judge_model"]:
                raise HTTPException(503, "请先在配置中心完成生成模型和安全检查模型配置。")
            base = os.getenv("HUNYUAN_BASE_URL", "https://api.hunyuan.cloud.tencent.com/v1")
            if not base.startswith("https://"):
                raise HTTPException(503, "模型服务必须使用 HTTPS。")
            options["generate"] = RemoteModel(base, key_value, settings["generation_model"], settings["max_tokens"])
            judge = RemoteJudge(RemoteModel(base, key_value, settings["judge_model"], 4096))
        docs = documents(tx)
        try:
            a = answer_question(who, body.question, Store(docs), facts(tx), judge,
                                PersistentAudit(tx), session=session, **options)
        except ModelFailure as error:
            raise HTTPException(503, str(error))
        answer = {"text": a.text, "citations": cite([d for d in docs if d.id in a.citations]),
                  "latency_ms": a.latency_ms, "data_source": "fake" if MODE == "demo" else "workspace"}
        tx.put("conversation", key, {"id": body.session_id, "owner": who.id,
               "title": body.question[:40] if not c else c["title"], "updated": time.time(), "revision": rev,
               "turns": (c["turns"] if c else []) + [{"question": body.question, "answer": answer}],
               "doc_ids": session.doc_ids, "claims": session.claims})
        return answer


@router.get("/audit")
def audit_list(who=Depends(auditor)):
    with database.transaction() as tx:
        who = checked(tx, who, AUDIT_ROLES)
        visible = {d.id for d in Store(documents(tx)).visible(who)}
        entries = tx.all("audit_entry")
        rows = []
        for i, e in list(enumerate(entries))[-200:]:
            p = e["payload"]
            rows.append({**e, "index": i, "payload": {"guard": True, "question_hash": "", "blocked_facts": [],
                         "degraded": False, **p, "docs": [d if d in visible else "[受限]" for d in p.get("docs", [])]}})
        return {"entries": rows, "length": len(entries)}


def signing_key() -> bytes:
    value = os.getenv("BUTLER_AUDIT_SIGNING_KEY", "")
    if not value:
        raise HTTPException(503, "未配置审计签名密钥（BUTLER_AUDIT_SIGNING_KEY）。")
    return (Path(value).read_bytes() if not value.startswith("-----") and Path(value).exists() else value.encode())


@router.get("/audit/export")
def audit_export(who=Depends(admin)):
    """完整原始链，哈希才能被独立验证；只给管理员/安全角色，范围受限的审计员看不到。"""
    with database.transaction() as tx:
        who = checked(tx, who, ADMIN_ROLES)
        key = signing_key()
        entries = tx.all("audit_entry")
        head = tx.get("meta", "audit_head")
        checkpoint = sign_checkpoint(key, head["count"], head["hash"])
        PersistentAudit(tx).append({"event": "audit.exported", "user": who.id, "count": head["count"]})
        return {"entries": entries, "checkpoint": checkpoint}


@router.get("/audit/verify")
def audit_verify(who=Depends(auditor)):
    with database.transaction() as tx:
        who = checked(tx, who, AUDIT_ROLES)
        entries = tx.all("audit_entry")
        ok, bad = verify(entries, tx.get("meta", "audit_head")["hash"])
        return {"ok": ok, "first_bad_index": bad, "length": len(entries)}
