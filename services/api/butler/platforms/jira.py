"""Jira 模拟器：项目角色 + 权限方案（谁能 Browse）+ 问题级安全级别。

语义：用户先要能浏览项目（属于被授予 Browse 的某个角色：角色成员可以是用户或组）；
问题设了安全级别时，还必须属于该级别的成员（用户 / 组 / 项目角色），或是允许的“报告人”。
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .base import Attachment, ChangeLog, NotFound, Throttle, paginate
from .people import Directory


@dataclass
class Actors:
    users: set[str] = field(default_factory=set)
    groups: set[str] = field(default_factory=set)


@dataclass
class SecurityLevel:
    name: str
    users: set[str] = field(default_factory=set)
    groups: set[str] = field(default_factory=set)
    roles: set[str] = field(default_factory=set)
    reporter_can_see: bool = True


@dataclass
class Project:
    key: str
    name: str
    lead: str
    roles: dict[str, Actors] = field(default_factory=dict)
    browse_roles: set[str] = field(default_factory=set)
    levels: dict[str, SecurityLevel] = field(default_factory=dict)


@dataclass
class Comment:
    author: str
    body: str
    ts: float


@dataclass
class Issue:
    key: str
    project: str
    type: str
    summary: str
    description: str
    status: str
    priority: str
    reporter: str
    assignee: str | None
    created: float
    updated: float
    labels: list[str] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)     # (关系, 另一个对象的编号/标题)
    comments: list[Comment] = field(default_factory=list)
    security: str | None = None
    attachments: list[Attachment] = field(default_factory=list)
    version: int = 1


class JiraServer:
    name = "jira"

    def __init__(self, directory: Directory, throttle_every: int = 0):
        self.dir, self.groups = directory, directory.groups()
        self.projects: dict[str, Project] = {}
        self.issues: dict[str, Issue] = {}
        self.log = ChangeLog()
        self.throttle = Throttle(throttle_every)

    def add_project(self, p: Project) -> None:
        self.projects[p.key] = p

    def add_issue(self, i: Issue) -> None:
        self.issues[i.key] = i
        self.log.bump(i.key, ts=i.updated)

    def get(self, key: str) -> Issue:
        if key not in self.issues:
            raise NotFound(key)
        return self.issues[key]

    def search(self, start_at: int = 0, max_results: int = 100):
        self.throttle.hit()
        return paginate(sorted(self.issues.values(), key=lambda i: i.key), start_at, max_results)

    # ---- 权限：原生语义 ----
    def _actors(self, a: Actors) -> set[str]:
        out = set(a.users)
        for g in a.groups:
            out |= self.groups.get(g, set())
        return out

    def role_members(self, project: str, role: str) -> set[str]:
        p = self.projects[project]
        return self._actors(p.roles[role]) if role in p.roles else set()

    def browsers(self, project: str) -> set[str]:
        p = self.projects[project]
        out: set[str] = set()
        for r in p.browse_roles:
            out |= self.role_members(project, r)
        return out

    def level_members(self, project: str, level: str) -> set[str]:
        lv = self.projects[project].levels[level]
        out = set(lv.users)
        for g in lv.groups:
            out |= self.groups.get(g, set())
        for r in lv.roles:
            out |= self.role_members(project, r)
        return out

    def can_access(self, person: str, key: str) -> bool:
        i = self.get(key)
        if person not in self.browsers(i.project):
            return False
        if i.security is None:
            return True
        lv = self.projects[i.project].levels[i.security]
        return person in self.level_members(i.project, i.security) or (lv.reporter_can_see and person == i.reporter)

    # ---- 权限：编译成令牌 ----
    def obj_tokens(self, key: str) -> frozenset[str]:
        i = self.get(key)
        if i.security is None:
            return frozenset({f"jira:browse:{i.project}"})
        lv = self.projects[i.project].levels[i.security]
        allowed = self.level_members(i.project, i.security)
        if lv.reporter_can_see:
            allowed = allowed | {i.reporter}
        return frozenset(f"user:{p}" for p in allowed & (self.browsers(i.project)))

    def user_tokens(self, person: str) -> set[str]:
        return {f"user:{person}"} | {f"jira:browse:{k}" for k in self.projects if person in self.browsers(k)}

    # ---- 演示用的变更 ----
    def add_comment(self, key: str, author: str, body: str, now: float) -> Issue:
        i = self.get(key)
        i.comments.append(Comment(author, body, now))
        i.updated, i.version = now, i.version + 1
        self.log.bump(key, ts=now)
        return i

    def set_security(self, key: str, level: str | None, now: float) -> Issue:
        i = self.get(key)
        i.security, i.updated, i.version = level, now, i.version + 1
        self.log.bump(key, ts=now)
        return i

    def set_status(self, key: str, status: str, now: float) -> Issue:
        i = self.get(key)
        i.status, i.updated, i.version = status, now, i.version + 1
        self.log.bump(key, ts=now)
        return i
