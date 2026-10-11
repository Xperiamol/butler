from ..acl.policy import can_read
from ..audit.chain import AuditLog
from ..models import Answer, Doc, Fact, Identity
from ..retrieval.store import Store
from .mosaic import Judge, check

DEGRADED_PREFIX = "以下只列出你有权查看的事实，不做进一步推断：\n"


def generate_naive(question: str, docs: list[Doc]) -> str:
    """占位生成器：把证据拼接并附带“推断”句。接入混元后替换；用来复现马赛克效应。"""
    facts = "\n".join(f"- [{d.source}] {d.text}" for d in docs)
    inference = ""
    blob = " ".join(d.text for d in docs)
    if "预算：0" in blob and "暂停续签" in blob:
        inference = "\n综合判断：Payments 团队可能被裁撤。"
    return facts + inference


def facts_only(docs: list[Doc]) -> str:
    return DEGRADED_PREFIX + "\n".join(f"- [{d.source}] {d.text}" for d in docs)


def answer_question(identity: Identity, question: str, store: Store, all_facts: list[Fact],
                    judge: Judge, audit: AuditLog, guard: bool = True) -> Answer:
    docs = store.search(identity, question)
    assert all(can_read(identity, d) for d in docs)  # 不变量：生成器永远看不到无权文档
    draft = generate_naive(question, docs)
    hits = check(identity, draft, all_facts, judge) if guard else []
    degraded = bool(hits)
    text = facts_only(docs) if degraded else draft
    audit.append({"user": identity.id, "question_hash": hash(question) & 0xFFFFFFFF,
                  "docs": [d.id for d in docs], "degraded": degraded,
                  "blocked_facts": [f.id for f in hits]})  # 只记 ID，不记内容
    return Answer(text=text, citations=[d.id for d in docs], degraded=degraded)
