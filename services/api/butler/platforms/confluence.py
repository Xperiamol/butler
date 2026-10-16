"""Confluence 模拟器：空间权限 + 页面级限制（子页面继承祖先的限制）。

语义（与 Atlassian 一致）：用户必须有**空间查看权限**，并且从根到本页的每一级限制都放行（限制里列了用户或组）。
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .base import Attachment, ChangeLog, NotFound, Throttle, paginate
from .people import Directory


@dataclass
class Space:
    key: str
    name: str
    kind: str                                   # team | project | knowledge | restricted
    view_groups: set[str] = field(default_factory=set)
    view_users: set[str] = field(default_factory=set)
    description: str = ""


@dataclass
class Page:
    id: str
    space: str
    title: str
    body: str
    author: str
    created: float
    updated: float
    parent: str | None = None
    version: int = 1
    labels: list[str] = field(default_factory=list)
    restrict_users: set[str] | None = None      # None = 没有页面级限制
    restrict_groups: set[str] = field(default_factory=set)
    attachments: list[Attachment] = field(default_factory=list)
    links: list[str] = field(default_factory=list)   # 引用的其他对象（Jira 编号、页面标题），用于跨平台关联


class ConfluenceServer:
    name = "confluence"

    def __init__(self, directory: Directory, throttle_every: int = 0):
        self.dir, self.groups = directory, directory.groups()
        self.spaces: dict[str, Space] = {}
        self.pages: dict[str, Page] = {}
        self.log = ChangeLog()
        self.throttle = Throttle(throttle_every)
        self.baseline: dict[str, str] = {}      # 页面第一次被改动前的正文：演示里“还原”用

    # ---- 数据 ----
    def add_space(self, s: Space) -> None:
        self.spaces[s.key] = s

    def add_page(self, p: Page) -> None:
        self.pages[p.id] = p
        self.log.bump(p.id, ts=p.updated)

    def get(self, page_id: str) -> Page:
        if page_id not in self.pages:
            raise NotFound(page_id)
        return self.pages[page_id]

    # ---- 平台 API（分页 + 限流）----
    def list_pages(self, start: int = 0, limit: int = 100):
        self.throttle.hit()
        return paginate(sorted(self.pages.values(), key=lambda p: p.id), start, limit)

    # ---- 权限：原生语义 ----
    def _members(self, groups: set[str], users: set[str]) -> set[str]:
        out = set(users)
        for g in groups:
            out |= self.groups.get(g, set())
        return out

    def space_viewers(self, key: str) -> set[str]:
        s = self.spaces[key]
        return self._members(s.view_groups, s.view_users)

    def _chain(self, page: Page) -> list[Page]:
        out, cur, seen = [], page, set()
        while cur is not None and cur.id not in seen:
            seen.add(cur.id)
            out.append(cur)
            cur = self.pages.get(cur.parent) if cur.parent else None
        return out

    def restricted_to(self, page: Page) -> set[str] | None:
        """从页面到根的所有限制取交集；没有任何限制返回 None。"""
        allowed: set[str] | None = None
        for p in self._chain(page):
            if p.restrict_users is not None:
                here = self._members(p.restrict_groups, p.restrict_users)
                allowed = here if allowed is None else allowed & here
        return allowed

    def can_access(self, person: str, page_id: str) -> bool:
        page = self.get(page_id)
        if person not in self.space_viewers(page.space):
            return False
        allowed = self.restricted_to(page)
        return allowed is None or person in allowed

    # ---- 权限：编译成令牌 ----
    def obj_tokens(self, page_id: str) -> frozenset[str]:
        page = self.get(page_id)
        allowed = self.restricted_to(page)
        if allowed is None:
            return frozenset({f"cf:space:{page.space}"})
        return frozenset(f"user:{p}" for p in allowed & self.space_viewers(page.space))

    def user_tokens(self, person: str) -> set[str]:
        return {f"user:{person}"} | {f"cf:space:{k}" for k in self.spaces if person in self.space_viewers(k)}

    # ---- 演示用的变更（来源平台上的真实操作）----
    def update_page(self, page_id: str, *, append: str = "", replace: str | None = None, now: float) -> Page:
        p = self.get(page_id)
        self.baseline.setdefault(page_id, p.body)
        p.body = replace if replace is not None else (p.body.rstrip() + "\n\n" + append if append else p.body)
        p.version += 1
        p.updated = now
        self.log.bump(page_id, ts=now)
        return p

    def restrict_page(self, page_id: str, users: set[str], groups: set[str] = frozenset(), now: float = 0.0) -> Page:
        p = self.get(page_id)
        p.restrict_users, p.restrict_groups, p.updated = set(users), set(groups), now or p.updated
        for q in self.pages.values():            # 子页面的有效权限也变了
            if p.id in {c.id for c in self._chain(q)}:
                self.log.bump(q.id, ts=now)
        return p

    def set_space_view(self, key: str, groups: set[str], users: set[str], now: float = 0.0) -> None:
        s = self.spaces[key]
        s.view_groups, s.view_users = set(groups), set(users)
        for q in self.pages.values():
            if q.space == key:
                self.log.bump(q.id, ts=now)

    def restore_page(self, page_id: str, now: float) -> Page:
        p = self.get(page_id)
        if page_id in self.baseline:
            p.body, p.version, p.updated = self.baseline[page_id], p.version + 1, now
            self.log.bump(page_id, ts=now)
        return p
