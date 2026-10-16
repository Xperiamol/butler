"""同步型连接器契约（拉取变更、读正文、实时展开权限）。与旧的 base.Connector 并存：旧的是演示用的整库读取。

不变量：
- fetch_principals 失败要抛异常，调用方不得沿用旧权限无限期放行（见 workers.sync 的权限新鲜期）
- 连接器只“读”，不做授权判断；平台主体到本地组的映射在 workers.sync 里完成，映射不出来就是无人可读
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Event:
    kind: str            # upsert | delete
    external_id: str
    version: float       # 单调递增的来源版本（git：提交序号），用来丢弃乱序到达的旧事件
    version_key: str     # 幂等键的一部分（git：内容 blob 哈希或提交哈希）
    observed_at: float   # 来源上发生变化的时间（用来度量撤权/更新延迟）


@dataclass(frozen=True)
class ExternalDoc:
    external_id: str
    title: str
    text: str
    url: str
    source: str = "upload"                       # 平台名（confluence / jira / slack / drive）；界面按它分组、显示图标
    meta: dict = field(default_factory=dict)      # 容器、作者、更新时间、模态、媒体键、关联对象……


class SyncConnector(Protocol):
    name: str
    data_source: str     # "real" | "fake"，界面必须展示

    def events(self, cursor: str | None) -> tuple[list[Event], str]:
        """cursor 之后的变更；cursor 为 None 表示首次全量。返回 (事件, 新 cursor)。"""

    def list_ids(self) -> list[tuple[str, float]]:
        """当前全部对象 (external_id, version)，用于对账补漏。"""

    def fetch(self, external_id: str) -> ExternalDoc | None:
        """正文；对象已不存在返回 None。"""

    def fetch_principals(self, external_id: str) -> frozenset[str]:
        """实时展开该对象当前可读的平台主体（用户/群组/角色标识）。失败抛异常。"""
