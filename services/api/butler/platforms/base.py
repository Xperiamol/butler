"""四个平台模拟器共用的小件：错误、限流、变更日志、附件（多模态）。

每个平台都实现两条权限路径，并有测试保证二者一致：
  can_access(person, obj)            平台原生语义的“实时判定”（查询时复核用）
  user_tokens(person) ∩ obj_tokens(obj)  编译成令牌的“快照判定”（入库时写进 ACL，检索时先过滤用）
令牌命名：user:<id>  org:all  grp:<team>  cf:space:<key>  jira:browse:<key>  slack:ws:<id>  slack:ch:<id>  drive:sd:<id>  pub:link
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field


class PlatformError(Exception):
    pass


class NotFound(PlatformError):
    pass


class RateLimited(PlatformError):
    def __init__(self, retry_after: float = 0.05):
        super().__init__(f"rate limited, retry after {retry_after}s")
        self.retry_after = retry_after


@dataclass
class Attachment:
    """多模态附件：原文件（图片/PDF/音频…）+ 入库时抽取出的文本（OCR / 图像描述 / 语音转写）。"""
    id: str
    name: str
    mime: str
    media: str = ""            # 媒体文件在媒体库里的键，空 = 没有实体文件
    derived: str = ""          # 识别结果：图片的描述和文字、PDF 扫描页的 OCR、录音的转写
    how: str = ""              # 怎么得到 derived：vision | ocr | asr | extract

    @property
    def modality(self) -> str:
        m = self.mime
        return "image" if m.startswith("image/") else "audio" if m.startswith("audio/") else "video" if m.startswith("video/") else "pdf" if m == "application/pdf" else "text"


@dataclass(frozen=True)
class Change:
    external_id: str
    kind: str          # upsert | delete
    version: float
    ts: float


class ChangeLog:
    """每个平台一份：单调递增的版本号 + 变更列表。游标 = 已读到的版本号。"""

    def __init__(self, start: float = 1.0):
        self.version = start
        self.items: list[Change] = []

    def bump(self, external_id: str, kind: str = "upsert", ts: float | None = None) -> float:
        self.version += 1.0
        self.items.append(Change(external_id, kind, self.version, ts if ts is not None else time.time()))
        return self.version

    def since(self, cursor: float) -> list[Change]:
        return [c for c in self.items if c.version > cursor]


class Throttle:
    """模拟平台 API 限流：每 `every` 次调用返回一次 429，调用方按 retry_after 退避重试。every=0 关闭。"""

    def __init__(self, every: int = 0):
        self.every, self.n = every, 0

    def hit(self) -> None:
        if not self.every:
            return
        self.n += 1
        if self.n % self.every == 0:
            raise RateLimited(0.01)


def paginate(items: list, start: int, limit: int) -> tuple[list, int | None]:
    chunk = items[start:start + limit]
    nxt = start + limit
    return chunk, (nxt if nxt < len(items) else None)
