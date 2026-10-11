"""所有数据源适配器（真实和假的）必须实现的契约。这是分工的接口边界，改动需团队确认。

不变量：
- 拿不到权限信息 ⇒ acl 返回空集合（即拒绝），绝不能默认放行。
- 适配器只负责“读”，不做任何权限判断；判断都在 acl/policy.py。
"""
from typing import Iterable, Protocol

from ..models import Doc


class Connector(Protocol):
    name: str          # slack | confluence | jira | drive
    data_source: str   # "real" | "fake"，界面必须展示

    def list_docs(self, since: float | None = None) -> Iterable[Doc]:
        """返回内容 + 已展开成“组/用户”集合的 ACL。since 用于增量对账。"""

    def fetch_acl(self, doc_id: str) -> frozenset[str]:
        """对单个对象实时重查 ACL（入选文档的实时复核用）。失败要抛异常，调用方按拒绝处理。"""

    def parse_event(self, payload: dict) -> list[str]:
        """把 webhook / Socket Mode 事件转成受影响的 doc_id 列表，交给同步队列。"""
