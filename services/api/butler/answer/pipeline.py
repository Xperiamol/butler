from __future__ import annotations
import hashlib
import re
import time
from dataclasses import replace
from typing import Callable, Optional

from ..acl.policy import can_read
from ..audit.chain import AuditLog
from ..models import Answer, Doc, Fact, Identity
from ..retrieval.store import Store
from ..security.injection import neutralize, scan
from .citations import verify_citations
from .remote import NO_INFO
from .mosaic import GuardBudgetExceeded, Judge, check, premise_hits
from .session import Session

DEGRADED_PREFIX = "以下只列出你有权查看的事实，不做进一步推断：\n"
NO_EVIDENCE = "没有找到你有权查看的相关资料，所以不作回答。"
UNVERIFIED = "生成的回答无法对应到你有权查看的资料，所以不作回答。"
SMALL_TALK = re.compile(r"^\s*(你好|您好|嗨|哈喽|hi|hello|hey|在吗|谢谢|多谢|感谢|辛苦了|再见|拜拜)[\s!！。,.，~～？?]*$", re.I)
GREETING = "你好，我是 Butler。可以直接问工作上的问题，比如“支付 API 限流是多少？”。我会按你的权限查资料，并告诉你答案出自哪份资料。"
SAFE_REFUSAL = "这个问题的完整回答可能涉及你无权知道的结论，所以不作回答。"
NEEDS_APPROVAL = ("这个问题的回答，加上之前已经给你的资料，会得出一项需要授权才能知道的结论，所以暂不放行。"
                  "如果工作确有需要，可以申请授权；批准后在有效期内可以继续提问。")

Generator = Callable[[str, list], str]


class SimulatedGenerator:
    """离线占位生成器：列出证据，并在碎片凑齐时写出推断句，用来复现马赛克效应。接入混元后替换。"""

    def __init__(self, rules: list[dict]):
        self.rules = rules

    def __call__(self, question: str, docs: list[Doc]) -> str:
        facts = "\n".join(f"- [{d.id}] {d.text}" for d in docs)
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


MAX_CONTEXT_CHARS = 24000


def fit_context(context: list[Doc], limit: int) -> list[Doc]:
    """上下文总长度预算：超出时先丢最靠后的资料（历史排在前面，检索到的新资料排在后面，所以从后往前丢是错的——
    这里从最长的开始截断，保证每份资料都还在、引用不失效）。"""
    total = sum(len(d.text) for d in context)
    if total <= limit:
        return context
    share = max(limit // max(len(context), 1), 400)
    return [d if len(d.text) <= share else replace(d, text=d.text[:share]) for d in context]


def facts_only(docs: list[Doc]) -> str:
    return DEGRADED_PREFIX + "\n".join(f"- [{d.id}] {d.text}" for d in docs)


def question_hash(question: str) -> str:
    return hashlib.sha256(question.encode()).hexdigest()[:16]


def answer_question(identity: Identity, question: str, store: Store, all_facts: list[Fact],
                    judge: Judge, audit: AuditLog, guard: bool = True,
                    session: Optional[Session] = None, generate: Optional[Generator] = None,
                    request_id: str = "", injection: bool = True, approved: frozenset = frozenset()) -> Answer:
    """approved：该用户已获预授权的受限结论编号。只对这些结论放行；其余照常拦截，拦截时给出“需要授权”而不是死拒答。"""
    t0 = time.perf_counter()
    all_facts = [f for f in all_facts if f.id not in approved]
    generate = generate or default_generator()
    docs = store.search(identity, question)
    # 会话里引用过的文档也进入上下文（多轮对话），但每轮都实时复核权限：撤权后旧对话也拿不到
    history = [d for d in store.get_many(session.doc_ids if session else [], session.doc_spans if session else None) if can_read(identity, d)]
    context = history + [d for d in docs if d.id not in {h.id for h in history}]
    assert all(can_read(identity, d) for d in context)  # 不变量：生成器永远看不到无权文档
    context = fit_context(context, MAX_CONTEXT_CHARS)
    quarantined: list[str] = []
    if guard and injection:
        # 最后一道提示注入防线（入库时已扫过一次）：命中的资料不进生成上下文；其余资料拆掉定界符/角色伪装
        kept = []
        for d in context:
            if scan(d.text).flagged:
                quarantined.append(d.id)
            else:
                kept.append(replace(d, text=neutralize(d.text)))
        context = kept

    status, hits, guard_ms, cited = "answered", [], 0.0, [d.id for d in context]
    if not context and SMALL_TALK.match(question):
        text, cited = GREETING, []   # 纯寒暄：不检索、不调用模型
    elif not context:
        text, status, cited = NO_EVIDENCE, "no_evidence", []
    elif guard and (chain := premise_hits(identity, all_facts, {d.id for d in context} | set(session.doc_ids if session else []))):
        # 结论的全部前提都将交到用户手里：不管模型怎么措辞，这一步都不放行，也不调用模型
        hits, text, status, cited = chain, NEEDS_APPROVAL, "needs_approval", []
    else:
        draft = generate(question, context)
        g0 = time.perf_counter()
        # 寒暄、含糊提问、资料里没有答案：模型用【无资料】开头、不带引用。仍然过结论检查，只是不要求引用。
        no_info = draft.lstrip().startswith(NO_INFO)
        if no_info:
            draft = draft.lstrip()[len(NO_INFO):].strip()
        text = draft
        if no_info:
            context, cited = [], []
        if guard:
            valid, problems = ([], []) if no_info else verify_citations(draft, context, urls=injection)
            if problems:
                text, status, cited = UNVERIFIED, "citation_failed", []
            else:
                cited = valid
        if guard and status == "answered":
            # 把本会话已放行的回答和新草稿一起检查，防止分多轮拼出结论
            prior = session.claims if session else []
            if hasattr(judge, "bind"):
                judge = judge.bind([d.text for d in context])   # 语义判官只看合成的新句子，不看资料原句
            try:
                hits = check(identity, "\n".join(prior + [draft]), all_facts, judge)
                if hits:
                    degraded = facts_only(context)
                    # 降级文本同样是“要发出的答案”，必须重新检查；仍触及则统一拒答
                    if check(identity, "\n".join(prior + [degraded]), all_facts, judge):
                        text, status, cited = NEEDS_APPROVAL, "needs_approval", []
                    else:
                        text, status, cited = degraded, "degraded", [d.id for d in context]
            except GuardBudgetExceeded:
                # 检查范围超出预算：不能当作“没问题”放行
                text, status, cited, hits = SAFE_REFUSAL, "refused", [], []
        guard_ms = (time.perf_counter() - g0) * 1000

    if session is not None:
        session.remember(cited, text, {d.id: [list(x) for x in d.spans] for d in context if d.id in set(cited) and d.spans})
    audit.append({"user": identity.id, "question_hash": question_hash(question), "guard": guard,
                  "docs": cited, "degraded": status == "degraded", "status": status, "request_id": request_id,
                  "quarantined": quarantined, "question_flagged": bool(guard and injection and scan(question).flagged),
                  "answer_digest": hashlib.sha256(text.encode()).hexdigest()[:16], "event": "ask",
                  "blocked_facts": [f.id for f in hits]})  # 只记 ID，不记内容
    return Answer(text=text, citations=cited, sources=[d for d in context if d.id in set(cited)], degraded=status in ("degraded", "refused", "needs_approval"), status=status, blocked_facts=[f.id for f in hits],
                  latency_ms=round((time.perf_counter() - t0) * 1000, 2), guard_ms=round(guard_ms, 2))
