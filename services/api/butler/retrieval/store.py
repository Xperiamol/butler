from __future__ import annotations
import math
import re

from ..acl.policy import can_read
from dataclasses import replace

from ..models import Doc, Identity


MIN_COVERAGE = 0.25
UNSEEN_WEIGHT = 0.25  # 库里从没出现过的词也说明“问的不是库里这些”，按半个最大 IDF 计入分母
PASSAGE_CHARS = 600
_SPLIT = re.compile(r"[，,、；;。？?！!]|和|与|以及|又|还")
_GLUE = re.compile(r"是不是|有没有|是否|能不能|会不会|可不可以|怎么样|怎么|什么|为什么|多少|如何|请问|帮我|告诉我|吗|呢|吧")
_STOP = set("的了是吗呢什么怎么为这那和与在有要又还就都把从给让被对说")


_EN_STOP = {"the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "and", "or", "in", "on", "for", "with", "at",
            "by", "from", "as", "it", "this", "that", "what", "which", "who", "how", "do", "does", "me", "my", "about",
            "tell", "latest", "can", "i", "we", "our", "your", "you", "please", "there", "any", "has", "have"}
_TOKEN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]+")


def _bigrams(s: str) -> set[str]:
    """中文用字符二元组；英文/数字按词（去常见虚词），中英混合的问题两边都能命中。"""
    grams: set[str] = set()
    for tok in _TOKEN.findall(s.lower()):
        if tok[0] < "\u4e00":
            if len(tok) > 1 and tok not in _EN_STOP:
                grams.add(tok)
        else:
            grams |= {tok[i:i + 2] for i in range(len(tok) - 1) if not (tok[i] in _STOP and tok[i + 1] in _STOP)}
    return grams


class Store:
    """先按权限过滤再检索（生产环境用 pgvector + ACL 数组列 WHERE，不做事后过滤）。
    开发期用 IDF 加权的字符二元组打分代替向量检索，只保留相对高分文档。"""

    def __init__(self, docs: list[Doc]):
        self._docs = docs
        self._by_id = {d.id: d for d in docs}
        self._grams = {d.id: _bigrams(d.title + d.text) for d in docs}
        self._index: dict[frozenset, tuple] = {}  # 按权限组缓存：同一组用户共享可见集合与 IDF（只含其可见文档的统计）

    def get_many(self, ids: list[str]) -> list[Doc]:
        return [self._by_id[i] for i in ids if i in self._by_id]

    def visible(self, identity: Identity) -> list[Doc]:
        return [d for d in self._docs if can_read(identity, d)]

    def _visible_index(self, identity: Identity):
        key = identity.groups
        if key not in self._index:
            allowed = [d for d in self._docs if can_read(identity, d)]  # 先过滤
            grams = {d.id: self._grams[d.id] for d in allowed}
            # IDF 只在提问者可见的文档上统计：受限文档的词频也是信息，不能漏进打分
            df: dict[str, int] = {}
            for g in grams.values():
                for b in g:
                    df[b] = df.get(b, 0) + 1
            # 平滑 IDF 恒为正，小库和单文档库也不会把所有词的权重压到接近 0
            self._index[key] = (allowed, grams, {b: math.log(1 + len(allowed) / c) for b, c in df.items()})
        return self._index[key]

    def search(self, identity: Identity, query: str, k: int = 6) -> list[Doc]:
        allowed, grams, idf = self._visible_index(identity)
        # 多方面的问题拆成子查询分别检索，再按出现顺序合并
        out: list[Doc] = []
        for sub in [query] + [p for p in _SPLIT.split(query) if len(p) >= 2]:
            q = _bigrams(_GLUE.sub(" ", sub))  # 去掉提问套话，免得它们稀释真正的关键词
            mass = sum(idf.get(b, 0.0) for b in q)  # 提问中“库里出现过的词”不计入分母外的惩罚：未出现词权重按最大 IDF 计
            unseen = [b for b in q if b not in idf]
            mass += len(unseen) * math.log(1 + len(allowed)) * UNSEEN_WEIGHT
            if not mass:
                continue
            need = 1 if len(q) <= 4 else 2  # 长问题只撞上一个词不算相关（“火星殖民计划”只因“计划”命中）；词法检索的权宜规则，向量召回接入后去掉
            scored = sorted(((sum(idf[b] for b in q & grams[d.id]) / mass if len(q & grams[d.id]) >= need else 0.0, d)
                             for d in allowed), key=lambda x: -x[0])
            top = scored[0][0]
            if top < MIN_COVERAGE:  # 相对阈值：命中了多少比例的提问信息量，与库大小和问题长短无关
                continue
            out += [d for s, d in scored[:3] if s >= top * 0.45 and s >= MIN_COVERAGE and d not in out]
        return [self._passage(d, query) for d in out[:k]]

    def _passage(self, doc: Doc, query: str) -> Doc:
        """长文只给生成器与问题最相关的段落，引用就能落到具体位置；短文原样返回。"""
        if len(doc.text) <= PASSAGE_CHARS:
            return doc
        parts = [p.strip() for p in re.split(r"\n+|(?<=[。！？])", doc.text) if p.strip()]
        q = _bigrams(query)
        windows, cur = [], ""
        for p in parts:
            if cur and len(cur) + len(p) > PASSAGE_CHARS:
                windows.append(cur)
                cur = ""
            cur += p
        if cur:
            windows.append(cur)
        best = max(windows, key=lambda w: len(q & _bigrams(w)))
        return replace(doc, text=best)
