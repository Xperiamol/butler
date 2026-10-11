from ..acl.policy import can_read
from ..models import Doc, Identity


def _bigrams(s: str) -> set[str]:
    s = "".join(ch for ch in s if not ch.isspace())
    return {s[i:i + 2] for i in range(len(s) - 1)}


class Store:
    """先按权限过滤再检索（生产环境用 pgvector + ACL 数组列 WHERE，不做事后过滤）。
    开发期用字符二元组重叠打分代替向量检索，只保留相对高分文档。"""

    def __init__(self, docs: list[Doc]):
        self._docs = docs

    def search(self, identity: Identity, query: str, k: int = 5) -> list[Doc]:
        allowed = [d for d in self._docs if can_read(identity, d)]  # 先过滤
        q = _bigrams(query)
        scored = sorted(((len(q & _bigrams(d.title + d.text)), d) for d in allowed), key=lambda x: -x[0])
        if not scored or scored[0][0] == 0:
            return []
        top = scored[0][0]
        return [d for s, d in scored[:k] if s >= max(1, top * 0.5)]
