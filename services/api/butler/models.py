from __future__ import annotations
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Identity:
    id: str
    name: str
    groups: frozenset[str]
    role: str


@dataclass(frozen=True)
class Doc:
    id: str
    source: str  # slack | confluence | jira | drive
    title: str
    text: str
    acl: frozenset[str]  # 可读该文档的组；空集 = 无人可读（未知即拒绝）
    spans: tuple[tuple[int, int], ...] = ()  # 检索返回的是原文的哪几段 [start, end)，引用据此定位；空 = 整篇
    heading: str = ""


@dataclass(frozen=True)
class Fact:
    """受限事实：继承来源文档 ACL，只供结论检查器使用，永不进入生成上下文。"""
    id: str
    source_doc: str
    acl: frozenset[str]
    statement: str
    keywords: tuple[str, ...] = ()
    premises: tuple[str, ...] = ()  # 推出该结论所需的资料编号：用户累计拿到全部前提 = 结论已可推出，与措辞无关


@dataclass
class Answer:
    text: str
    citations: list[str] = field(default_factory=list)  # doc ids
    degraded: bool = False
    status: str = "answered"  # answered | degraded | refused | citation_failed | no_evidence
    blocked_facts: list[str] = field(default_factory=list)  # 只给审计和演示对比用，不返回给提问者
    latency_ms: float = 0.0
    guard_ms: float = 0.0  # 结论检查额外耗时
    data_source: str = "fake"  # UI 必须展示
    sources: list = field(default_factory=list)  # 实际被引用的文档（含原文位置），供界面展示出处
