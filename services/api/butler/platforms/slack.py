"""Slack 模拟器：工作区成员 / 访客，频道成员关系，线程。

语义：
- 公开频道：该工作区的正式成员都能读；访客只有被邀请进该频道才能读
- 私有频道 / 群聊 / 私信：只有频道成员能读
- 保留策略：超过 retention_days 的消息不再可取（入库里对应的文档会被对账删除）
入库粒度：一个线程（根消息 + 回复）= 一份文档；没有回复的顶层消息按“频道 + 日期”合成一份摘要文档。
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field

from .base import Attachment, ChangeLog, NotFound, Throttle, paginate
from .people import Directory

DAY = 86400.0


@dataclass
class Message:
    ts: float
    user: str
    text: str
    thread_ts: float | None = None            # None = 顶层；否则是某线程的回复
    files: list[Attachment] = field(default_factory=list)


@dataclass
class Channel:
    id: str
    name: str
    ws: str
    kind: str                                   # public | private | mpim | im
    members: set[str] = field(default_factory=set)
    topic: str = ""
    retention_days: int | None = None
    messages: list[Message] = field(default_factory=list)


@dataclass
class Workspace:
    id: str
    name: str
    members: set[str] = field(default_factory=set)
    guests: set[str] = field(default_factory=set)


class SlackServer:
    name = "slack"

    def __init__(self, directory: Directory, throttle_every: int = 0, now: float | None = None):
        self.dir = directory
        self.workspaces: dict[str, Workspace] = {}
        self.channels: dict[str, Channel] = {}
        self.log = ChangeLog()
        self.throttle = Throttle(throttle_every)
        self.now = now or time.time()

    def add_workspace(self, w: Workspace) -> None:
        self.workspaces[w.id] = w

    def add_channel(self, c: Channel) -> None:
        self.channels[c.id] = c

    def add_message(self, channel: str, m: Message) -> None:
        """入库前的批量造数据：不记变更日志（首次全量同步会读到）。"""
        self.channels[channel].messages.append(m)

    def post_live(self, channel: str, user: str, text: str, now: float, thread_ts: float | None = None) -> Message:
        """来源平台上的一次真实发消息：记变更，所属线程/摘要文档随之更新。"""
        m = Message(now, user, text, thread_ts)
        c = self.channels[channel]
        c.messages.append(m)
        for eid, msgs in self.objects(c).items():
            if m in msgs:
                self.log.bump(eid, ts=now)
        return m

    # ---- 文档划分 ----
    @staticmethod
    def thread_id(channel: str, root_ts: float) -> str:
        return f"{channel}/t{root_ts:.3f}"

    @staticmethod
    def digest_id(channel: str, ts: float) -> str:
        return f"{channel}/d{time.strftime('%Y%m%d', time.gmtime(ts))}"

    @staticmethod
    def _has_replies(c: Channel, ts: float) -> bool:
        return any(m.thread_ts == ts for m in c.messages)

    def retained(self, c: Channel) -> list[Message]:
        if not c.retention_days:
            return list(c.messages)
        cutoff = self.now - c.retention_days * DAY
        return [m for m in c.messages if m.ts >= cutoff]

    def objects(self, c: Channel) -> dict[str, list[Message]]:
        """channel 里全部入库对象：external_id → 属于它的消息（按时间）。"""
        msgs = sorted(self.retained(c), key=lambda m: m.ts)
        roots = {m.ts for m in msgs if m.thread_ts is None and any(r.thread_ts == m.ts for r in msgs)}
        out: dict[str, list[Message]] = {}
        for m in msgs:
            if m.thread_ts is not None:
                out.setdefault(self.thread_id(c.id, m.thread_ts), []).append(m)
            elif m.ts in roots:
                out.setdefault(self.thread_id(c.id, m.ts), []).insert(0, m)
            else:
                out.setdefault(self.digest_id(c.id, m.ts), []).append(m)
        return out

    def all_objects(self) -> dict[str, tuple[Channel, list[Message]]]:
        out = {}
        for c in self.channels.values():
            for eid, ms in self.objects(c).items():
                out[eid] = (c, sorted(ms, key=lambda m: m.ts))
        return out

    def get(self, external_id: str):
        ch = external_id.split("/")[0]
        if ch not in self.channels:
            raise NotFound(external_id)
        objs = self.objects(self.channels[ch])
        if external_id not in objs:
            raise NotFound(external_id)
        return self.channels[ch], sorted(objs[external_id], key=lambda m: m.ts)

    # ---- 平台 API ----
    def list_objects(self, cursor: int = 0, limit: int = 200):
        self.throttle.hit()
        return paginate(sorted(self.all_objects().items()), cursor, limit)

    # ---- 权限：原生语义 ----
    def can_access(self, person: str, external_id: str) -> bool:
        c, _ = self.get(external_id)
        ws = self.workspaces[c.ws]
        if c.kind == "public":
            return person in ws.members or person in c.members
        return person in c.members

    # ---- 权限：编译成令牌 ----
    def obj_tokens(self, external_id: str) -> frozenset[str]:
        c, _ = self.get(external_id)
        if c.kind == "public":
            return frozenset({f"slack:ws:{c.ws}", f"slack:ch:{c.id}"})
        return frozenset({f"slack:ch:{c.id}"})

    def user_tokens(self, person: str) -> set[str]:
        out = {f"user:{person}"}
        for w in self.workspaces.values():
            if person in w.members:
                out.add(f"slack:ws:{w.id}")
        for c in self.channels.values():
            if person in c.members:
                out.add(f"slack:ch:{c.id}")
        return out

    # ---- 演示用的变更 ----
    def remove_member(self, channel: str, person: str, now: float) -> None:
        c = self.channels[channel]
        c.members.discard(person)
        for eid in self.objects(c):
            self.log.bump(eid, ts=now)

    def add_member(self, channel: str, person: str, now: float) -> None:
        c = self.channels[channel]
        c.members.add(person)
        for eid in self.objects(c):
            self.log.bump(eid, ts=now)

    def set_kind(self, channel: str, kind: str, now: float) -> None:
        c = self.channels[channel]
        c.kind = kind
        for eid in self.objects(c):
            self.log.bump(eid, ts=now)
