"""结论级检查：答案是否推出了提问者无权知道的受限事实。"""
from typing import Protocol

from ..acl.policy import can_read
from ..models import Fact, Identity


class Judge(Protocol):
    def entails(self, answer: str, fact: Fact) -> bool: ...


class KeywordJudge:
    """开发期规则判官，便于离线测试；生产换成混元 LLM 判官（接口相同）。"""

    def entails(self, answer: str, fact: Fact) -> bool:
        return any(k in answer for k in fact.keywords)


def restricted_facts(identity: Identity, facts: list[Fact]) -> list[Fact]:
    return [f for f in facts if not can_read(identity, f)]


def check(identity: Identity, answer: str, facts: list[Fact], judge: Judge) -> list[Fact]:
    """返回被答案触及的受限事实（空 = 通过）。"""
    candidates = restricted_facts(identity, facts)
    if candidates and hasattr(judge, "entails_many"):
        return judge.entails_many(answer, candidates)
    return [f for f in candidates if judge.entails(answer, f)]
