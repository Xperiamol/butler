"""四个平台模拟器的同步连接器：实现 SyncConnector 契约（events / list_ids / fetch / fetch_principals）。

每个平台一个连接器实例，各自的游标、版本和权限解析互不相干（不拍平）。
- events(cursor)：游标是平台变更日志的版本号；首次（None）返回全部对象
- fetch_principals：实时用平台的原生语义编译出令牌；失败抛异常，调用方按“拒绝”处理
- 遇到 429 按 retry_after 退避重试（模拟平台限流）
"""
from __future__ import annotations
import re
import time

from ..platforms.base import NotFound, RateLimited
from ..platforms.hub import Hub
from .sync import Event, ExternalDoc

JIRA_KEY = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{1,5})\b")
BASE = {"confluence": "https://tidepool.atlassian.example/wiki", "jira": "https://tidepool.atlassian.example/browse", "slack": "https://tidepool.slack.example/archives", "drive": "https://drive.google.example/file/d"}


def _retry(fn, tries: int = 6):
    for i in range(tries):
        try:
            return fn()
        except RateLimited as e:
            time.sleep(min(e.retry_after, 0.05))
    raise RateLimited(0.0)


def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def _stamp(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts))


class PlatformConnector:
    data_source = "fake"   # 模拟平台；界面必须展示

    def __init__(self, hub: Hub, platform: str):
        self.hub, self.name = hub, platform
        self.server = hub.server(platform)

    # ---- 对象枚举 ----
    def _objects(self) -> dict[str, float]:
        """external_id → 当前版本（含附件，附件继承父对象的版本）。"""
        latest = {c.external_id: c.version for c in self.server.log.items}
        out: dict[str, float] = {}
        s = self.server
        if self.name == "confluence":
            pages = _all(lambda start: s.list_pages(start, 200))
            for p in pages:
                v = latest.get(p.id, 1.0)
                out[p.id] = v
                for a in p.attachments:
                    out[f"{p.id}@{a.id}"] = v
        elif self.name == "jira":
            for i in _all(lambda start: s.search(start, 200)):
                v = latest.get(i.key, 1.0)
                out[i.key] = v
                for a in i.attachments:
                    out[f"{i.key}@{a.id}"] = v
        elif self.name == "slack":
            for eid, (ch, msgs) in s.all_objects().items():
                v = latest.get(eid, 1.0)
                out[eid] = v
                for m in msgs:
                    for a in m.files:
                        out[f"{eid}@{a.id}"] = v
        else:
            for f in _all(lambda start: s.list_files(start, 200)):
                out[f.id] = latest.get(f.id, 1.0)
        return out

    def events(self, cursor: str | None):
        objs = self._objects()
        now = time.time()
        if cursor is None:
            return [Event("upsert", ext, v, f"{ext}@{v}", now) for ext, v in objs.items()], str(self.server.log.version)
        since = float(cursor)
        changed = {c.external_id: c for c in self.server.log.since(since)}
        out = []
        for ext, v in objs.items():
            base = ext.split("@")[0]
            if base in changed:
                out.append(Event("upsert", ext, v, f"{ext}@{v}", changed[base].ts))
        for c in self.server.log.since(since):       # 平台上已经不存在的对象（保留期过期、删除）由对账补删
            pass
        return out, str(self.server.log.version)

    def list_ids(self) -> list[tuple[str, float]]:
        return sorted(self._objects().items())

    # ---- 取内容 ----
    def fetch(self, external_id: str) -> ExternalDoc | None:
        try:
            return self._doc(external_id)
        except NotFound:
            return None

    def fetch_principals(self, external_id: str) -> frozenset[str]:
        return self.hub.obj_tokens(f"{self.name}:{external_id}")

    # ---- 文档渲染 ----
    def _links(self, text: str) -> list[str]:
        keys = [k for k in dict.fromkeys(JIRA_KEY.findall(text)) if k in self.hub.jira.issues]
        return [f"jira:{k}" for k in keys][:8]

    def _doc(self, ext: str) -> ExternalDoc:
        base, _, att_id = ext.partition("@")
        if self.name == "confluence":
            return self._confluence(base, att_id)
        if self.name == "jira":
            return self._jira(base, att_id)
        if self.name == "slack":
            return self._slack(base, att_id)
        return self._drive(base)

    def _attachment_doc(self, parent_ext: str, parent_title: str, att, container: str, updated: float, author: str, extra: dict) -> ExternalDoc:
        how = {"vision": "Image (vision model description and visible text)", "ocr": "Scanned document (OCR text)", "asr": "Recording (speech-to-text transcript)", "extract": "Extracted text"}.get(att.how, "Attachment")
        text = f"{how}: {att.name}\n\n{att.derived}"
        meta = {"platform": self.name, "kind": "attachment", "container": container, "author": author, "updated": updated, "modality": att.modality, "media": att.media, "mime": att.mime,
                "parent": f"{self.name}:{parent_ext}", "parent_title": parent_title, "file_name": att.name, **extra}
        return ExternalDoc(f"{parent_ext}@{att.id}", f"{parent_title} — {att.name}", text, self._url(parent_ext), self.name, meta)

    def _url(self, ext: str) -> str:
        base = ext.split("@")[0]
        if self.name == "confluence":
            p = self.server.get(base)
            return f"{BASE['confluence']}/spaces/{p.space}/pages/{p.id}"
        if self.name == "jira":
            return f"{BASE['jira']}/{base}"
        if self.name == "slack":
            ch, t = base.split("/")
            return f"{BASE['slack']}/{ch}/p{t[1:].replace('.', '')}"
        return f"{BASE['drive']}/{base}"

    def _confluence(self, pid: str, att_id: str) -> ExternalDoc:
        s = self.server
        p = s.get(pid)
        space = s.spaces[p.space]
        if att_id:
            a = next(x for x in p.attachments if x.id == att_id)
            return self._attachment_doc(pid, p.title, a, f"{space.name} ({p.space})", p.updated, p.author, {"space": p.space, "labels": p.labels})
        text = f"{p.body}\n\n(Last updated {_stamp(p.updated)} by {p.author}; version {p.version}.)"
        meta = {"platform": "confluence", "kind": "page", "container": f"{space.name} ({p.space})", "space": p.space, "author": p.author, "created": p.created, "updated": p.updated, "labels": p.labels,
                "modality": "text", "version": p.version, "links": self._links(p.body), "attachments": [f"confluence:{pid}@{a.id}" for a in p.attachments], "restricted": p.restrict_users is not None}
        return ExternalDoc(pid, p.title, text, self._url(pid), "confluence", meta)

    def _jira(self, key: str, att_id: str) -> ExternalDoc:
        s = self.server
        i = s.get(key)
        proj = s.projects[i.project]
        if att_id:
            a = next(x for x in i.attachments if x.id == att_id)
            return self._attachment_doc(key, f"{key}: {i.summary}", a, f"{proj.name} ({i.project})", i.updated, i.reporter, {})
        comments = "\n".join(f"- [{_day(c.ts)}] {c.author}: {c.body}" for c in i.comments)
        links = "\n".join(f"- {rel} {other}" for rel, other in i.links)
        text = (f"Type: {i.type} | Status: {i.status} | Priority: {i.priority} | Reporter: {i.reporter} | Assignee: {i.assignee or 'unassigned'}\n"
                f"Created {_day(i.created)}, last updated {_day(i.updated)}.\n\n{i.description}" + (f"\n\nComments:\n{comments}" if comments else "") + (f"\n\nLinks:\n{links}" if links else ""))
        meta = {"platform": "jira", "kind": "issue", "container": f"{proj.name} ({i.project})", "project": i.project, "author": i.reporter, "assignee": i.assignee, "created": i.created, "updated": i.updated,
                "status": i.status, "priority": i.priority, "issue_type": i.type, "labels": i.labels, "modality": "text", "links": self._links(text) , "secured": i.security is not None}
        meta["links"] = [l for l in meta["links"] if l != f"jira:{key}"]
        return ExternalDoc(key, f"{key}: {i.summary}", text, self._url(key), "jira", meta)

    def _slack(self, eid: str, att_id: str) -> ExternalDoc:
        s = self.server
        ch, msgs = s.get(eid)
        who = lambda u: self.hub.directory.by_id[u].name if u in self.hub.directory.by_id else u
        first = msgs[0]
        title = f"#{ch.name} — {first.text[:70]}{'…' if len(first.text) > 70 else ''}" if ch.kind in ("public", "private") else f"{'Direct message' if ch.kind == 'im' else 'Group message'} — {first.text[:60]}"
        if att_id:
            a = next(x for m in msgs for x in m.files if x.id == att_id)
            return self._attachment_doc(eid, title, a, f"#{ch.name}", msgs[-1].ts, first.user, {"channel": ch.id})
        lines = []
        for m in msgs:
            lines.append(f"[{_stamp(m.ts)}] {who(m.user)}: {m.text}" + "".join(f" [file: {f.name}]" for f in m.files))
        text = "\n".join(lines)
        meta = {"platform": "slack", "kind": "thread" if len(msgs) > 1 or msgs[0].thread_ts is None else "message", "container": f"#{ch.name}" if ch.kind in ("public", "private") else "direct message", "channel": ch.id,
                "channel_kind": ch.kind, "workspace": ch.ws, "author": first.user, "created": first.ts, "updated": msgs[-1].ts, "modality": "text", "links": self._links(text),
                "attachments": [f"slack:{eid}@{f.id}" for m in msgs for f in m.files]}
        return ExternalDoc(eid, title, text, self._url(eid), "slack", meta)

    def _drive(self, fid: str) -> ExternalDoc:
        s = self.server
        f = s.get(fid)
        container = s.drives[f.drive].name if f.drive else f"My Drive ({f.owner})"
        shared = []
        for p in f.perms:
            shared.append({"user": f"user {p.who}", "group": f"group {p.who}", "domain": "everyone in the company", "anyone": "anyone with the link"}[p.kind] + f" ({p.role})")
        if f.attachment:
            a = f.attachment
            how = {"vision": "Image (vision model description and visible text)", "ocr": "Scanned document (OCR text)", "asr": "Recording (speech-to-text transcript)"}.get(a.how, "File")
            body = f"{how}: {f.name}\n\n{a.derived}"
            modality = a.modality
        else:
            body = f.text or f.name
            modality = {"application/vnd.google-apps.spreadsheet": "sheet", "application/vnd.google-apps.presentation": "slides"}.get(f.mime, "text")
        text = f"{body}\n\n(Drive file in {container}; modified {_stamp(f.modified)}; owner {f.owner}.)"
        meta = {"platform": "drive", "kind": "file", "container": container, "drive": f.drive, "author": f.owner, "created": f.created, "updated": f.modified, "modality": modality, "mime": f.mime,
                "media": f.attachment.media if f.attachment else "", "file_name": f.name, "shared_with": shared, "limited": f.limited, "links": self._links(body), "public_link": any(p.kind == "anyone" for p in f.perms)}
        return ExternalDoc(fid, f.name, text, self._url(fid), "drive", meta)


def _all(page):
    out, start = [], 0
    while start is not None:
        chunk, start = _retry(lambda s=start: page(s))
        out.extend(chunk)
    return out
