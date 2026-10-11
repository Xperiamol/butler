from __future__ import annotations
import hashlib
import time
from typing import Callable, Optional

from ..acl.policy import can_read
from ..audit.chain import AuditLog
from ..models import Answer, Doc, Fact, Identity
from ..retrieval.store import Store
from .mosaic import Judge, check
from .session import Session

DEGRADED_PREFIX = "以下只列出你有权查看的事实，不做进一步推断：\n"
NO_EVIDENCE = "没有找到你有权查看的相关资料，所以不作回答。"

Generator = Callable[[str, list], str]


class SimulatedGenerator:
    """离线占位生成器：列出证据，并在碎片凑齐时写出推断句，用来复现马赛克效应。接入混元后替换。"""

    def __init__(self, rules: list[dict]):
        self.rules = rules

    def __call__(self, question: str, docs: list[Doc]) -> str:
        facts = "\n".join(f"- [{d.source}] {d.text}" for d in docs)
        blob = " ".join(d.text for d in docs)
        inferences = [r["text"] for r in self.rules if all(s in blob for s in r["requires"])]
        return facts + "".join("\n" + t for t in inferences)


_default_generator: Optional[SimulatedGenerator] = None


def default_generator() -> SimulatedGenerator:
    global _default_generator
    if _default_generator is None:
        from ..connectors.fake import load_inferences
        _default_generator = SimulatedGenerator(load_inferences())
    return _default_generator


def facts_only(docs: list[Doc]) -> str:
    return DEGRADED_PREFIX + "\n".join(f"- [{d.source}] {d.text}" for d in docs)


def question_hash(question: str) -> str:
    return hashlib.sha256(question.encode()).hexdigest()[:16]


def answer_question(identity: Identity, question: str, store: Store, all_facts: list[Fact],
                    judge: Judge, audit: AuditLog, guard: bool = True,
                    session: Optional[Session] = None, generate: Optional[Generator] = None) -> Answer:
    t0 = time.perf_counter()
    generate = generate or default_generator()
    docs = store.search(identity, question)
    # 会话里引用过的文档也进入上下文（多轮对话），但每轮都实时复核权限：撤权后旧对话也拿不到
    history = [d for d in store.get_many(session.doc_ids if session else []) if can_read(identity, d)]
    context = history + [d for d in docs if d.id not in {h.id for h in history}]
    assert all(can_read(identity, d) for d in context)  # 不变量：生成器永远看不到无权文档

    if not docs and not history:
        text, hits, guard_ms = NO_EVIDENCE, [], 0.0
    else:
        draft = generate(question, context)
        g0 = time.perf_counter()
        # 把本会话已放行的回答和新草稿一起检查，防止分多轮拼出结论
        ledger = "\n".join((session.claims if session else []) + [draft])
        hits = check(identity, ledger, all_facts, judge) if guard else []
        guard_ms = (time.perf_counter() - g0) * 1000
        text = facts_only(context) if hits else draft

    cited = [d.id for d in context] if text != NO_EVIDENCE else []
    if session is not None:
        session.remember(cited, text)
    audit.append({"user": identity.id, "question_hash": question_hash(question), "guard": guard,
                  "docs": cited, "degraded": bool(hits),
                  "blocked_facts": [f.id for f in hits]})  # 只记 ID，不记内容
    return Answer(text=text, citations=cited, degraded=bool(hits), blocked_facts=[f.id for f in hits],
                  latency_ms=round((time.perf_counter() - t0) * 1000, 2), guard_ms=round(guard_ms, 2))
