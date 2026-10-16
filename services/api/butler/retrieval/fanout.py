"""跨平台扇出检索：对每个子查询 × 每个相关平台各检索一次，按 RRF 融合，再做平台配额、时间偏好和关联对象展开。

不变量：每一次 store.search 都在“提问者可读”的集合上做（权限在召回之前生效）；关联对象展开同样只取可读的。
"""
from __future__ import annotations
import time

from ..models import Doc, Identity

RRF_K = 60


def fan_out(store, identity: Identity, question: str, plan, k: int = 10, per_platform: int = 4, expand: int = 4, now: float | None = None) -> tuple[list[Doc], dict]:
    now = now or time.time()
    score: dict[str, float] = {}
    docs: dict[str, Doc] = {}
    by_platform: dict[str, set[str]] = {}
    queries = list(dict.fromkeys([question] + list(plan.queries)))
    for q in queries:
        for platform in plan.platforms:
            for rank, d in enumerate(store.search(identity, q, k=per_platform, platforms=frozenset({platform}))):
                score[d.id] = score.get(d.id, 0.0) + 1.0 / (RRF_K + rank)
                docs.setdefault(d.id, d)
                by_platform.setdefault(platform, set()).add(d.id)
    # 时间偏好：问题里有时间窗口，窗口内的加分；要“最新”的，更新的加分（同一标题的旧副本排在后面）
    for i in list(score):
        m = store.meta_of(i)
        up = (m or {}).get("updated")
        if not up:
            continue
        age_days = max(0.0, (now - up) / 86400.0)
        if plan.days:
            score[i] += 0.012 if age_days <= plan.days else -0.004
        if plan.recency:
            score[i] += 0.01 / (1.0 + age_days / 30.0)
    ranked = sorted(score, key=lambda i: -score[i])
    # 平台配额：每个相关平台先保证至少一个最高分，再按分数补满
    chosen: list[str] = []
    for platform in plan.platforms:
        first = next((i for i in ranked if i in by_platform.get(platform, ())), None)
        if first and first not in chosen:
            chosen.append(first)
    for i in ranked:
        if len(chosen) >= k:
            break
        if i not in chosen and sum(1 for c in chosen if docs[c].source == docs[i].source) < per_platform:
            chosen.append(i)
    out = sorted(chosen, key=lambda i: -score[i])[:k]
    # 关联对象展开：顶部文档引用的、或引用了它们的 Jira / Slack / Confluence 对象，只要可读就补进来
    linked: list[str] = []
    top = out[:3]
    for i in top:
        m = store.meta_of(i) or {}
        linked += [l for l in m.get("links", [])]
    back = store.backlinks(top)
    linked += back
    extra_ids = [l for l in dict.fromkeys(linked) if l not in out][:expand * 3]
    extra = store.passages(identity, extra_ids, " ".join(queries[:2]), per_doc=1)[:expand]
    result = [docs[i] for i in out] + extra
    # 短文档整篇给：片段可能漏掉文档末尾（比如刚追加的一步）
    budget = 16000
    for n, d in enumerate(result[:8]):
        full = store.full_doc(identity, d.id)
        if full and len(full.text) > len(d.text) and len(full.text) <= budget:
            result[n] = full
            budget -= len(full.text)
    trace = {"queries": len(queries), "platforms": {p: sum(1 for d in result if d.source == p) for p in plan.platforms if any(d.source == p for d in result)}, "expanded": len(extra), "plan_source": getattr(plan, "source", "rules")}
    return result, trace
