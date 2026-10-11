"""会话论断账本：记录本会话已经给出的内容，防止用户分多轮问、自己拼出结论。"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Session:
    identity_id: str
    doc_ids: list[str] = field(default_factory=list)   # 本会话已引用过的文档
    claims: list[str] = field(default_factory=list)    # 本会话已放行的回答

    def remember(self, doc_ids: list[str], text: str) -> None:
        self.doc_ids += [d for d in doc_ids if d not in self.doc_ids]
        self.claims.append(text)


class SessionStore:
    def __init__(self) -> None:
        self._s: dict[str, Session] = {}

    def get(self, session_id: str, identity_id: str) -> Session:
        s = self._s.get(session_id)
        if s is None or s.identity_id != identity_id:  # 换身份 = 新会话，不继承别人的上下文
            s = self._s[session_id] = Session(identity_id)
        return s

    def reset(self, session_id: str) -> None:
        self._s.pop(session_id, None)
