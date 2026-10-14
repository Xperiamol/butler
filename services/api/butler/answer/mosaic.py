"""结论级检查：答案是否推出了提问者无权知道的受限事实。

级联：受限事实不多时全量检查；事实很多时先用廉价的词面重叠做高召回候选筛选，再分批交给判官。
候选数超过预算时不静默跳过，而是抛出 GuardBudgetExceeded，由调用方统一拒答（宁可拒答，不放过未检查的事实）。
"""
from __future__ import annotations
import math
import re
from typing import Protocol

from ..acl.policy import can_read
from ..models import Fact, Identity

FULL_SCAN_LIMIT = 25      # 受限事实不超过这个数：不筛选，全部交给判官
MAX_CANDIDATES = 200      # 筛选后超过这个数：判定为超出检查预算
BATCH_CHARS = 30000       # 单批送给判官的事实文本上限（远低于模型输入限制）


class GuardBudgetExceeded(Exception):
    pass


class Judge(Protocol):
    def entails(self, answer: str, fact: Fact) -> bool: ...


class KeywordJudge:
    """开发期规则判官，便于离线测试；生产换成混元 LLM 判官（接口相同）。"""

    def entails(self, answer: str, fact: Fact) -> bool:
        return any(k in answer for k in fact.keywords)


_CAP = re.compile(r"\b[A-Z][A-Za-z0-9]{2,}\b")
_FUNCTION_WORDS = {"The", "This", "That", "These", "Those", "Our", "Their", "Company", "Team", "Board", "Group", "Project"}


def anchors_of(fact: Fact) -> tuple[str, ...]:
    """结论里的专有名词（句中大写开头的词）：关键词出现在别的上下文里不算数，必须和它们同时出现。"""
    words = fact.statement.split(maxsplit=1)
    body = words[1] if len(words) > 1 else ""
    return tuple(dict.fromkeys(w for w in _CAP.findall(body) if w not in _FUNCTION_WORDS))


class AnchoredKeywordJudge(KeywordJudge):
    """关键词 + 实体锚定：真实文档里恰好出现 "acquisition" 不会再触发"收购 Orbit Labs"这条事实。
    结论里没有可识别的专有名词时，行为和 KeywordJudge 一样。代价：把专有名词换成代称（"那家公司"）的泄露会漏掉。"""

    def entails(self, answer: str, fact: Fact) -> bool:
        if not super().entails(answer, fact):
            return False
        anchors = anchors_of(fact)
        return not anchors or any(a in answer for a in anchors)


class CombinedJudge:
    """任一判官认为触及就算触及（宁可多拦）。候选筛选取各判官筛选结果的并集。"""

    def __init__(self, *judges):
        self.judges = judges

    def entails(self, answer: str, fact: Fact) -> bool:
        return any(j.entails(answer, fact) for j in self.judges)

    def bind(self, context_texts: list[str]) -> "CombinedJudge":
        return CombinedJudge(*[j.bind(context_texts) if hasattr(j, "bind") else j for j in self.judges])

    def shortlist(self, answer: str, facts: list[Fact]) -> list[Fact]:
        seen, out = set(), []
        for j in self.judges:
            for f in (j.shortlist(answer, facts) if hasattr(j, "shortlist") else shortlist(answer, facts)):
                if f.id not in seen:
                    seen.add(f.id)
                    out.append(f)
        return out


def restricted_facts(identity: Identity, facts: list[Fact]) -> list[Fact]:
    return [f for f in facts if not can_read(identity, f)]


def premise_hits(identity: Identity, facts: list[Fact], exposed_docs: set[str]) -> list[Fact]:
    """依赖闭包检查：某条受限结论的全部前提资料都已（或即将）交到提问者手里。"""
    hits = []
    for f in restricted_facts(identity, facts):
        if not f.premises:
            continue
        got = len(set(f.premises) & exposed_docs)
        if (f.quorum and got >= f.quorum) or (not f.quorum and got == len(set(f.premises))):
            hits.append(f)
    return hits


def _grams(text: str) -> set[str]:
    out: set[str] = set()
    for chunk in re.sub(r"[\s\W_]+", " ", text.lower()).split():
        out |= {chunk[i:i + 2] for i in range(len(chunk) - 1)} if len(chunk) > 1 else set()
    return out


MIN_SHARE = 0.2   # 候选必须命中事实自身“信息量”的这一比例，只撞上人人都有的常用词不算


def shortlist(answer: str, facts: list[Fact]) -> list[Fact]:
    """高召回候选筛选：按 IDF 加权的词面重叠；关键词原样出现在答案里的事实一律保留。"""
    ans = _grams(answer)
    terms = {f.id: _grams(f.statement) | {g for k in f.keywords for g in _grams(k)} for f in facts}
    df: dict[str, int] = {}
    for t in terms.values():
        for g in t:
            df[g] = df.get(g, 0) + 1
    idf = {g: math.log(1 + len(facts) / c) for g, c in df.items()}
    scored = []
    for f in facts:
        t = terms[f.id]
        mass = sum(idf[g] for g in t) or 1.0
        share = sum(idf[g] for g in t & ans) / mass
        if share >= MIN_SHARE or any(k and k in answer for k in f.keywords):
            scored.append((share, f))
    return [f for _, f in sorted(scored, key=lambda x: -x[0])]


def _batches(facts: list[Fact]) -> list[list[Fact]]:
    out, cur, size = [], [], 0
    for f in facts:
        if cur and size + len(f.statement) > BATCH_CHARS:
            out.append(cur)
            cur, size = [], 0
        cur.append(f)
        size += len(f.statement) + 40
    return out + ([cur] if cur else [])


def check(identity: Identity, answer: str, facts: list[Fact], judge: Judge) -> list[Fact]:
    """返回被答案触及的受限事实（空 = 通过）。"""
    candidates = restricted_facts(identity, facts)
    if len(candidates) > FULL_SCAN_LIMIT:
        candidates = judge.shortlist(answer, candidates) if hasattr(judge, "shortlist") else shortlist(answer, candidates)
        if len(candidates) > MAX_CANDIDATES:
            raise GuardBudgetExceeded(f"{len(candidates)} candidates")
    if not candidates:
        return []
    if hasattr(judge, "entails_many"):
        hits: list[Fact] = []
        for batch in _batches(candidates):
            hits += judge.entails_many(answer, batch)
        return hits
    return [f for f in candidates if judge.entails(answer, f)]
