"""平台中枢：持有四个模拟平台，把“人员”翻译成各平台的令牌，做查询时的实时权限复核，并应用演示用的来源平台变更。

文档 id 约定：<平台>:<外部 id>，例如 confluence:10234  jira:ATLAS-9  slack:C0001/t1790000000.000  drive:f-123
附件（多模态）单独成为一份文档：<父对象 id>@<附件 id>，权限继承父对象。
"""
from __future__ import annotations
import json
import time
from dataclasses import dataclass, field

from .base import NotFound
from .confluence import ConfluenceServer
from .drive import DriveServer, Perm
from .jira import JiraServer
from .people import Directory
from .slack import SlackServer

PLATFORMS = ("confluence", "jira", "slack", "drive")


@dataclass
class Hub:
    directory: Directory
    confluence: ConfluenceServer
    jira: JiraServer
    slack: SlackServer
    drive: DriveServer
    epoch: float
    mutations: list[dict] = field(default_factory=list)

    def server(self, platform: str):
        return getattr(self, platform)

    # ---- 令牌 ----
    def user_tokens(self, person: str) -> set[str]:
        toks: set[str] = set()
        for p in PLATFORMS:
            toks |= self.server(p).user_tokens(person)
        return toks

    @staticmethod
    def split(doc_id: str) -> tuple[str, str, str | None]:
        """confluence:123@att-1 → (confluence, 123, att-1)"""
        platform, _, rest = doc_id.partition(":")
        ext, _, att = rest.partition("@")
        return platform, ext, att or None

    def obj_tokens(self, doc_id: str) -> frozenset[str]:
        platform, ext, _ = self.split(doc_id)
        return self.server(platform).obj_tokens(ext)

    # ---- 实时复核：平台原生语义，不看入库时的快照 ----
    def can_access(self, person: str, doc_id: str) -> bool:
        platform, ext, _ = self.split(doc_id)
        try:
            return self.server(platform).can_access(person, ext)
        except NotFound:
            return False     # 对象已不存在（删除/保留期过期）⇒ 不可读

    # ---- 来源平台上的变更（演示控制台调用）----
    ACTIONS = {
        "confluence.update_page": "更新 Confluence 页面",
        "confluence.restrict_page": "限制 Confluence 页面的访问",
        "confluence.set_space_view": "修改 Confluence 空间权限",
        "jira.add_comment": "在 Jira 问题上评论",
        "jira.set_security": "设置 Jira 问题安全级别",
        "slack.post": "在 Slack 频道发消息",
        "slack.remove_member": "把成员移出 Slack 频道",
        "slack.add_member": "把成员拉进 Slack 频道",
        "slack.set_kind": "修改 Slack 频道可见性",
        "drive.unshare": "取消 Drive 共享",
        "drive.share": "新增 Drive 共享",
        "drive.edit": "编辑 Drive 文件",
        "drive.set_limited": "把 Drive 文件设为受限访问",
    }

    def apply(self, action: str, params: dict, now: float | None = None, record: bool = True) -> dict:
        now = time.time() if now is None else now
        a, p = action, params
        if a == "confluence.update_page":
            page = self.confluence.update_page(p["id"], append=p.get("append", ""), replace=p.get("replace"), now=now)
            out = {"platform": "confluence", "object": f"confluence:{page.id}", "title": page.title, "version": page.version}
        elif a == "confluence.restrict_page":
            page = self.confluence.restrict_page(p["id"], set(p.get("users", [])), set(p.get("groups", [])), now)
            out = {"platform": "confluence", "object": f"confluence:{page.id}", "title": page.title}
        elif a == "confluence.set_space_view":
            self.confluence.set_space_view(p["key"], set(p.get("groups", [])), set(p.get("users", [])), now)
            out = {"platform": "confluence", "object": f"space:{p['key']}"}
        elif a == "jira.add_comment":
            i = self.jira.add_comment(p["key"], p.get("author", "system"), p["body"], now)
            out = {"platform": "jira", "object": f"jira:{i.key}", "title": i.summary}
        elif a == "jira.set_security":
            i = self.jira.set_security(p["key"], p.get("level"), now)
            out = {"platform": "jira", "object": f"jira:{i.key}", "title": i.summary}
        elif a == "slack.post":
            self.slack.post_live(p["channel"], p["user"], p["text"], now, p.get("thread_ts"))
            out = {"platform": "slack", "object": f"slack:{p['channel']}"}
        elif a == "slack.remove_member":
            self.slack.remove_member(p["channel"], p["user"], now)
            out = {"platform": "slack", "object": f"slack:{p['channel']}", "user": p["user"]}
        elif a == "slack.add_member":
            self.slack.add_member(p["channel"], p["user"], now)
            out = {"platform": "slack", "object": f"slack:{p['channel']}", "user": p["user"]}
        elif a == "slack.set_kind":
            self.slack.set_kind(p["channel"], p["kind"], now)
            out = {"platform": "slack", "object": f"slack:{p['channel']}"}
        elif a == "drive.unshare":
            f = self.drive.unshare(p["id"], p["kind"], p.get("who", ""), now)
            out = {"platform": "drive", "object": f"drive:{f.id}", "title": f.name}
        elif a == "drive.share":
            f = self.drive.share(p["id"], Perm(p["kind"], p.get("who", ""), p.get("role", "reader")), now)
            out = {"platform": "drive", "object": f"drive:{f.id}", "title": f.name}
        elif a == "drive.edit":
            f = self.drive.edit(p["id"], p["text"], now)
            out = {"platform": "drive", "object": f"drive:{f.id}", "title": f.name}
        elif a == "drive.set_limited":
            f = self.drive.set_limited(p["id"], bool(p["limited"]), now)
            out = {"platform": "drive", "object": f"drive:{f.id}", "title": f.name}
        else:
            raise ValueError(f"unknown action {action}")
        if record:
            self.mutations.append({"action": action, "params": params, "at": now})
        return out

    def replay(self, mutations: list[dict]) -> None:
        for m in mutations:
            try:
                self.apply(m["action"], m["params"], now=m["at"], record=True)
            except Exception:   # noqa: BLE001 — 个别变更重放失败（对象已不在）不影响启动
                continue

    def stats(self) -> dict:
        c, j, s, d = self.confluence, self.jira, self.slack, self.drive
        objs = s.all_objects()
        media = [f.attachment for f in d.files.values() if f.attachment] + [a for p in c.pages.values() for a in p.attachments] + [a for i in j.issues.values() for a in i.attachments] + [a for _, ms in objs.values() for m in ms for a in m.files]
        by: dict[str, int] = {}
        for a in media:
            by[a.modality] = by.get(a.modality, 0) + 1
        return {
            "confluence": {"spaces": len(c.spaces), "pages": len(c.pages), "restricted_pages": sum(1 for p in c.pages.values() if p.restrict_users is not None)},
            "jira": {"projects": len(j.projects), "issues": len(j.issues), "secured_issues": sum(1 for i in j.issues.values() if i.security)},
            "slack": {"workspaces": len(s.workspaces), "channels": len(s.channels), "private_channels": sum(1 for x in s.channels.values() if x.kind != "public"),
                      "threads": len(objs), "dms": sum(1 for x in s.channels.values() if x.kind in ("im", "mpim"))},
            "drive": {"shared_drives": len(d.drives), "files": len(d.files), "limited_files": sum(1 for f in d.files.values() if f.limited), "external_links": sum(1 for f in d.files.values() if any(p.kind == "anyone" for p in f.perms))},
            "multimodal": by,
            "people": len(self.directory.people),
        }
