from __future__ import annotations
import math
import re

from ..acl.policy import can_read
from ..models import Doc, Identity


_SPLIT = re.compile(r"[，,、；;。？?！!]|和|与|以及|又|还")
_STOP = set("的了是吗呢什么怎么为这那和与在有要又还就都把从给让被对说")


def _bigrams(s: str) -> set[str]:
    s = re.sub(r"[\s\W_]+", " ", s.lower())
    grams = set()
    for chunk in s.split():
        grams |= {chunk[i:i + 2] for i in range(len(chunk) - 1)}
    return {g for g in grams if not (g[0] in _STOP and g[1] in _STOP)}


class Store:
    """先按权限过滤再检索（生产环境用 pgvector + ACL 数组列 WHERE，不做事后过滤）。
    开发期用 IDF 加权的字符二元组打分代替向量检索，只保留相对高分文档。"""

    def __init__(self, docs: list[Doc]):
        self._docs = docs
        self._by_id = {d.id: d for d in docs}

    def get_many(self, ids: list[str]) -> list[Doc]:
        return [self._by_id[i] for i in ids if i in self._by_id]

    def visible(self, identity: Identity) -> list[Doc]:
        return [d for d in self._docs if can_read(identity, d)]

    def search(self, identity: Identity, query: str, k: int = 6) -> list[Doc]:
        allowed = [d for d in self._docs if can_read(identity, d)]  # 先过滤
        grams = {d.id: _bigrams(d.title + d.text) for d in allowed}
        # IDF 只在提问者可见的文档上统计：受限文档的词频也是信息，不能漏进打分
        df: dict[str, int] = {}
        for g in grams.values():
            for b in g:
                df[b] = df.get(b, 0) + 1
        idf = {b: math.log((len(allowed) + 1) / c) for b, c in df.items()}
        # 多方面的问题拆成子查询分别检索，再按出现顺序合并
        out: list[Doc] = []
        for sub in [query] + [p for p in _SPLIT.split(query) if len(p) >= 4]:
            q = _bigrams(sub)
            scored = sorted(((sum(idf[b] for b in q & grams[d.id]), d) for d in allowed), key=lambda x: -x[0])
            if not scored or scored[0][0] < 4.0:  # 至少约两个有区分度的词才算相关
                continue
            top = scored[0][0]
            out += [d for s, d in scored[:3] if s >= top * 0.45 and d not in out]
        return out[:k]
