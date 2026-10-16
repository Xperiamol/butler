"""混合检索：词法（BM25 + 覆盖率闸门）与向量（精确余弦）两路召回，RRF 融合。

权限在召回之前生效：两路都只在“提问者可见文档”的块上打分，统计量（IDF、平均长度）也只来自可见文档，
受限文档的词频、向量都不会影响任何人的排序。不是先全局 top-k 再删。

pgvector 的 ANN 过滤会影响返回数量（见 docs/implementation-audit.md），所以这里先用精确向量搜索建立基准；
块数上万以后再评估 HNSW + 迭代扫描。
"""
from __future__ import annotations
import math
import time
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy import select

from .. import database as D
from ..acl.policy import can_read
from ..ingest.chunking import split_document
from ..ingest.embedding import Embedder, from_bytes
from ..ingest.index import chunk_rows, doc_hash
from ..models import Doc, Identity
from . import clir
from .store import _GLUE, _SPLIT, terms

K1, B = 1.2, 0.75
MIN_COVERAGE = 0.5       # 词法闸门：命中提问信息量的比例，校准见 docs/retrieval-eval.md
UNSEEN_WEIGHT = 1.0
CJK_MIN_COVERAGE = 0.45  # 中文二元组覆盖率下限；0.25→0.45：不相关中文资料带回率 71%→32%，中文对照召回 30→28/30（开发集校准）
CJK_UNSEEN_WEIGHT = 0.25
CLIR_MIN_COVERAGE = 0.4   # 跨语言概念覆盖率下限，校准见 docs/independent-eval.md
DENSE_MIN = 0.30         # 向量闸门：余弦下限，校准见 docs/retrieval-eval.md
POOL = 30
RRF_K = 60
MAX_DOCS = 6
MAX_CHUNKS = 10
HISTORY_CHARS = 3000     # 历史文档没有记录段落位置时取开头多少字
INJECTION_BLOCK = 0.5   # 入库扫描风险分达到这个值（或规则命中）的块被隔离


@dataclass
class _Chunk:
    id: str
    doc_id: str
    content_hash: str
    start: int
    end: int
    heading: str
    text: str
    title: str
    terms: Counter
    length: int
    flagged: bool = False


class _View:
    """某一类可见集合上的词法统计：倒排表、df、平均长度。按可见集合缓存，可见集合变了才重建。"""

    def __init__(self, chunks: list[_Chunk], rows: list[int]):
        self.rows = rows
        self.postings: dict[str, list[tuple[int, int]]] = {}
        total = 0
        for pos, r in enumerate(rows):
            total += chunks[r].length
            for t, tf in chunks[r].terms.items():
                self.postings.setdefault(t, []).append((pos, tf))
        self.n = len(rows)
        self.avg = total / self.n if self.n else 1.0
        self.idf = {t: math.log(1 + self.n / len(p)) for t, p in self.postings.items()}
        self._deletes: dict[str, list[str]] | None = None
        self._vocab: list[str] | None = None

    def expand(self, word: str) -> list[str]:
        """英文候选词 → 本视图里实际出现的词形（词干前缀匹配：organize/organization/organizing 互通）。"""
        import bisect
        if self._vocab is None:
            self._vocab = sorted(t for t in self.postings if t.isascii() and t.isalpha())
        stem = word[:max(4, len(word) - 2)] if len(word) >= 5 else word
        i = bisect.bisect_left(self._vocab, stem)
        out = []
        while i < len(self._vocab) and self._vocab[i].startswith(stem) and len(out) < 12:
            out.append(self._vocab[i])
            i += 1
        return out

    def correct(self, term: str) -> str | None:
        """库里没有的词：找编辑距离 1 以内（含相邻换位）的已有词，容忍拼写错误。对称删除法，按需建表。"""
        if len(term) < 5 or not term.isascii():
            return None
        if self._deletes is None:
            self._deletes = {}
            for t in self.postings:
                if len(t) >= 5 and t.isascii():
                    for i in range(len(t)):
                        self._deletes.setdefault(t[:i] + t[i + 1:], []).append(t)
                    self._deletes.setdefault(t, []).append(t)
        found = {c for key in [term] + [term[:i] + term[i + 1:] for i in range(len(term))] for c in self._deletes.get(key, ())}
        found = [c for c in found if abs(len(c) - len(term)) <= 1]
        return max(found, key=lambda c: self.idf[c]) if found else None


class ChunkIndex:
    """从 chunks / embeddings 表加载到内存的只读快照，按 index_epoch 与嵌入模型缓存。"""

    def __init__(self, chunks: list[_Chunk], vectors: np.ndarray, epoch: int, model: str):
        self.chunks, self.vectors, self.epoch, self.model = chunks, vectors, epoch, model
        self.by_doc: dict[str, tuple[str, list[int]]] = {}
        for i, c in enumerate(chunks):
            h, idxs = self.by_doc.setdefault(c.doc_id, (c.content_hash, []))
            idxs.append(i)
        self._views: dict[frozenset, _View] = {}

    def has(self, doc_id: str, content_hash: str) -> bool:
        return doc_id in self.by_doc and self.by_doc[doc_id][0] == content_hash

    def view(self, doc_ids: frozenset, quarantine: bool = True) -> _View:
        key = (doc_ids, quarantine)
        if key not in self._views:
            rows = [i for d in sorted(doc_ids) if d in self.by_doc for i in self.by_doc[d][1] if not (quarantine and self.chunks[i].flagged)]
            if len(self._views) > 64:
                self._views.clear()
            self._views[key] = _View(self.chunks, rows)
        return self._views[key]


def load_index(tx, embedder: Embedder) -> ChunkIndex:
    epoch = tx.get("meta", "index_epoch", {"value": 0})["value"]
    rows = tx.connection.execute(select(
        D.chunks.c.id, D.chunks.c.doc_id, D.chunks.c.content_hash, D.chunks.c.start, D.chunks.c.end, D.chunks.c.heading,
        D.chunks.c.text, D.chunks.c.text_hash, D.documents.c.title, D.chunks.c.risk, D.chunks.c.flags
    ).join(D.documents, D.documents.c.id == D.chunks.c.doc_id).order_by(D.chunks.c.doc_id, D.chunks.c.seq)).all()
    vecs = {r.text_hash: r for r in tx.connection.execute(select(D.embeddings).where(D.embeddings.c.model == embedder.name))}
    dim = next((r.dim for r in vecs.values()), embedder.dim or 1)
    chunks, mat = [], np.zeros((len(rows), dim), dtype=np.float32)
    for i, (cid, did, ch, s, e, heading, text, th, title, risk, flags) in enumerate(rows):
        t = terms(f"{title} {heading} {text}")
        chunks.append(_Chunk(cid, did, ch, s, e, heading, text, title or "", Counter(t), max(len(t), 1), risk >= INJECTION_BLOCK or bool(flags)))
        if th in vecs and vecs[th].dim == dim:
            mat[i] = from_bytes(vecs[th].vector, dim)
    return ChunkIndex(chunks, mat, epoch, embedder.name)


class IndexCache:
    """进程内缓存：index_epoch 或嵌入模型变了才重新加载。"""

    def __init__(self):
        self._index: ChunkIndex | None = None

    def get(self, tx, embedder: Embedder) -> ChunkIndex:
        epoch = tx.get("meta", "index_epoch", {"value": 0})["value"]
        if self._index is None or self._index.epoch != epoch or self._index.model != embedder.name:
            self._index = load_index(tx, embedder)
        return self._index


@dataclass
class HybridStore:
    """与 Store 同接口（search / get_many / visible），可直接给 answer_question 使用。"""
    metas: list[dict]                 # id, source, title, acl, content_hash（不含正文）
    index: ChunkIndex
    embedder: Embedder
    pending: dict[str, dict] = field(default_factory=dict)   # 索引滞后的文档正文，现场切块、只走词法
    history: dict[str, str] = field(default_factory=dict)    # 会话历史引用过的文档正文
    as_of: float = 0.0                # 快照时间：同步来的文档权限复核过期后视为不可读（权限接口失败 ⇒ 拒绝）
    last_debug: dict = field(default_factory=dict)
    quarantine: bool = True   # 评测里用来关掉“入库隔离”做对照

    def _doc(self, m: dict, text: str = "") -> Doc:
        return Doc(m["id"], m["source"], m["title"], text, frozenset(m["acl"]))

    def _readable(self, identity: Identity, m: dict) -> bool:
        if m.get("fresh_until") is not None and m["fresh_until"] < self.as_of:
            return False
        return can_read(identity, self._doc(m))

    def visible(self, identity: Identity) -> list[Doc]:
        return [self._doc(m) for m in self.metas if self._readable(identity, m)]

    def get_many(self, ids: list[str], spans: dict | None = None) -> list[Doc]:
        """会话历史里引用过的文档：只带回当时引用的段落（按原文位置），没有位置的长文只取开头——不把整篇长文塞进下一轮。"""
        by = {m["id"]: m for m in self.metas}
        out = []
        for i in ids:
            if i not in by or i not in self.history:
                continue
            full, sp = self.history[i], (spans or {}).get(i)
            if sp:
                text, used = "\n…\n".join(full[a:b] for a, b in sp), tuple(tuple(x) for x in sp)
            else:
                text, used = full[:HISTORY_CHARS], ()
            out.append(Doc(i, by[i]["source"], by[i]["title"], text, frozenset(by[i]["acl"]), used))
        return out

    # ---- 检索 ----
    def search(self, identity: Identity, query: str, k: int = MAX_DOCS, platforms: frozenset[str] | None = None) -> list[Doc]:
        vis = {m["id"]: m for m in self.metas if self._readable(identity, m) and (platforms is None or m["source"] in platforms)}      # 先过滤
        return self._rank(vis, query, k)

    def shadow_candidates(self, query: str, k: int = 5) -> list[str]:
        """【只供审计】不看权限地搜一遍，返回最相关的文档 id。调用方拿它和提问者可读的集合做差，得到“被拒绝的候选”写进审计。
        结果绝不进入生成上下文，也不返回给提问者（否则就是存在性的旁路）。"""
        every = {m["id"]: m for m in self.metas if m.get("fresh_until") is None or m["fresh_until"] >= self.as_of}
        return [d.id for d in self._rank(every, query, k)]

    def readable_ids(self, identity: Identity) -> set[str]:
        return {m["id"] for m in self.metas if self._readable(identity, m)}

    def meta_of(self, doc_id: str) -> dict | None:
        if not hasattr(self, "_by_id"):
            self._by_id = {m["id"]: m for m in self.metas}
        return self._by_id.get(doc_id)

    def backlinks(self, ids: list[str]) -> list[str]:
        """引用了这些文档的其他文档（只返回 id，是否可读由调用方再过滤）。"""
        if not hasattr(self, "_back"):
            self._back: dict[str, list[str]] = {}
            for m in self.metas:
                for l in m.get("links") or ():
                    self._back.setdefault(l, []).append(m["id"])
        out: list[str] = []
        for i in ids:
            out += self._back.get(i, [])[:6]
        return out

    def passages(self, identity: Identity, ids: list[str], query: str, per_doc: int = 2) -> list[Doc]:
        """按 id 取文档里与查询最相关的块（关联对象展开用）。只返回提问者可读的。"""
        by = {m["id"]: m for m in self.metas}
        q = set(terms(_GLUE.sub(" ", query)))
        out = []
        for i in ids:
            m = by.get(i)
            if not m or not self._readable(identity, m) or i not in self.index.by_doc:
                continue
            idx = self.index.by_doc[i][1]
            best = sorted(idx, key=lambda j: -sum(1 for t in q if t in self.index.chunks[j].terms))[:per_doc]
            cs = sorted((self.index.chunks[j] for j in best), key=lambda c: c.start)
            out.append(Doc(i, m["source"], m["title"], "\n…\n".join(c.text for c in cs), frozenset(m["acl"]), tuple((c.start, c.end) for c in cs), cs[0].heading))
        return out

    def full_doc(self, identity: Identity, doc_id: str, max_chars: int = 5000) -> Doc | None:
        """短文档整篇交给生成器（“把每一步都列出来”这类问题只给几个片段会漏步骤）。超过 max_chars 的长文返回 None，仍用片段。"""
        m = self.meta_of(doc_id)
        if not m or not self._readable(identity, m) or doc_id not in self.index.by_doc:
            return None
        chunks = sorted((self.index.chunks[j] for j in self.index.by_doc[doc_id][1]), key=lambda c: c.start)
        text, end = "", 0
        for c in chunks:
            if c.start > end:   # 块之间被跳过的通常是标题行（标题存在 heading 里，不在块正文里）：补回来
                text += (f"\n\n## {c.heading.split(' > ')[-1]}\n" if c.heading else "\n")
            elif c.start < end:
                text += c.text[end - c.start:]
                end = max(end, c.end)
                continue
            text += c.text
            end = c.end
            if len(text) > max_chars:
                return None
        return Doc(doc_id, m["source"], m["title"], text, frozenset(m["acl"]), ((chunks[0].start, end),), chunks[0].heading)

    def _rank(self, vis: dict[str, dict], query: str, k: int) -> list[Doc]:
        by = {m["id"]: m for m in self.metas}
        fresh = frozenset(d for d, m in vis.items() if self.index.has(d, m["content_hash"]))
        lag = [d for d in vis if d not in fresh]
        chunks, rows = self.index.chunks, self.index.view(fresh, self.quarantine).rows
        vectors = self.index.vectors
        extra: list[_Chunk] = []
        for d in lag:
            doc = self.pending.get(d)
            if doc:
                for r in chunk_rows(doc):
                    if self.quarantine and (r["risk"] >= INJECTION_BLOCK or r["flags"]):
                        continue   # 滞后文档同样先扫描再用
                    t = terms(f"{doc['title']} {r['heading']} {r['text']}")
                    extra.append(_Chunk(r["id"], d, r["content_hash"], r["start"], r["end"], r["heading"], r["text"],
                                        doc["title"], Counter(t), max(len(t), 1)))
        pool = [chunks[i] for i in rows] + extra
        if not pool:
            return []
        view = self.index.view(fresh, self.quarantine) if not extra else _View(pool, list(range(len(pool))))
        mat = np.vstack([vectors[rows], np.zeros((len(extra), vectors.shape[1]), dtype=np.float32)]) if extra else vectors[rows]

        # 多方面的问题拆成子句分别做词法召回（每个子句各自过覆盖率闸门），再与向量召回一起融合
        rankings = []
        for clause in [query] + [p for p in _SPLIT.split(query) if len(terms(p)) >= 2]:
            qset = set()
            for t in terms(_GLUE.sub(" ", clause)):
                if t not in view.idf and (fix := view.correct(t)):
                    t = fix
                qset.add(t)
            rankings.append(self._lexical(view, pool, qset))
        if clir.available() and sum(1 for c in query if "\u4e00" <= c <= "\u9fff") >= max(4, len(query) // 3):
            rankings.append(self._clir(view, pool, query))   # 中文问题 → 英文文档：词典式跨语言检索
        lex = [i for r in rankings for i in r]
        dense = self._dense(mat, query)
        fused: dict[int, float] = {}
        for ranking in rankings + [dense]:
            for rank, i in enumerate(ranking):
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + rank)
        order = sorted(fused, key=lambda i: -fused[i])[:MAX_CHUNKS]
        self.last_debug = {"lexical": len(lex), "dense": len(dense), "pool": len(pool)}
        # 同一文档的块合并成一个带原文位置的“段落集合”，按文档最佳名次排序
        groups: dict[str, list[_Chunk]] = {}
        for i in order:
            groups.setdefault(pool[i].doc_id, []).append(pool[i])
        out = []
        for d, cs in list(groups.items())[:k]:
            cs.sort(key=lambda c: c.start)
            m = by[d]
            out.append(Doc(d, m["source"], m["title"], "\n…\n".join(c.text for c in cs), frozenset(m["acl"]),
                           tuple((c.start, c.end) for c in cs), cs[0].heading))
        return out

    def _lexical(self, view: _View, pool: list[_Chunk], qset: set[str]) -> list[int]:
        if not qset or not view.n:
            return []
        cjk = sum(1 for t in qset if t[0] >= "\u4e00") * 2 >= len(qset)
        min_cov, unseen_w = (CJK_MIN_COVERAGE, CJK_UNSEEN_WEIGHT) if cjk else (MIN_COVERAGE, UNSEEN_WEIGHT)
        unseen = [t for t in qset if t not in view.idf]
        mass = sum(view.idf.get(t, 0.0) for t in qset) + len(unseen) * math.log(1 + view.n) * unseen_w
        if not mass:
            return []
        need = 1 if len(qset) <= 4 else 2
        scores: dict[int, float] = {}
        matched: dict[int, set[str]] = {}
        for t in qset:
            for pos, tf in view.postings.get(t, ()):
                c = pool[pos]
                s = view.idf[t] * tf * (K1 + 1) / (tf + K1 * (1 - B + B * c.length / view.avg))
                scores[pos] = scores.get(pos, 0.0) + s
                matched.setdefault(pos, set()).add(t)
        gated = [p for p in scores if len(matched[p]) >= need and sum(view.idf[t] for t in matched[p]) / mass >= min_cov]
        return sorted(gated, key=lambda p: -scores[p])[:POOL]

    def _clir(self, view: _View, pool: list[_Chunk], query: str) -> list[int]:
        """每个中文词是一个"概念"（它的英文候选互为同义）；块命中概念的区分度之和 / 全部概念的区分度之和 = 覆盖率。"""
        weights, hits = [], []
        for _, cands in clir.concepts(query):
            terms_ = {t for w in cands for t in view.expand(w)}
            terms_ = {t for t in terms_ if t in view.idf}
            if not terms_:
                continue
            weights.append(max(view.idf[t] for t in terms_))
            hits.append(terms_)
        if len(weights) < 2:
            return []
        scores: dict[int, float] = {}
        matched: dict[int, int] = {}
        for w, ts in zip(weights, hits):
            seen = {pos for t in ts for pos, _ in view.postings.get(t, ())}
            for pos in seen:
                scores[pos] = scores.get(pos, 0.0) + w
                matched[pos] = matched.get(pos, 0) + 1
        total = sum(weights)
        gated = [p for p in scores if matched[p] >= 2 and scores[p] / total >= CLIR_MIN_COVERAGE]
        return sorted(gated, key=lambda p: -scores[p])[:POOL]

    def _dense(self, mat: np.ndarray, query: str) -> list[int]:
        if not mat.shape[0] or not mat.any():
            return []
        q = self.embedder.embed([query])[0]
        if q.shape[0] != mat.shape[1]:
            return []
        sims = mat @ q
        top = np.argsort(-sims)[:POOL]
        return [int(i) for i in top if sims[i] >= DENSE_MIN]


def build_store(tx, embedder: Embedder, cache: IndexCache, history_ids: list[str] = ()) -> HybridStore:
    """在读事务内取一份快照：元数据（不含正文）、块索引，以及滞后文档/会话历史需要的正文。"""
    metas = [{"id": r.id, "source": r.source, "title": r.title, "acl": r.acl or [], "content_hash": r.content_hash,
              "fresh_until": r.fresh_until, "updated": r.updated, "links": r.links or []}
             for r in tx.connection.execute(select(D.documents.c.id, D.documents.c.source, D.documents.c.content_hash,
                                                   D.documents.c.title, D.documents.c.acl, D.documents.c.fresh_until, D.documents.c.updated, D.documents.c.links))]
    for m in metas:
        if not m["content_hash"]:  # 旧数据没有哈希：用正文现算
            m["content_hash"] = doc_hash(tx.get("document", m["id"]))
    index = cache.get(tx, embedder)
    pending = {m["id"]: tx.get("document", m["id"]) for m in metas if not index.has(m["id"], m["content_hash"])}
    history = {i: tx.get("document", i)["text"] for i in history_ids if tx.get("document", i)}
    return HybridStore(metas, index, embedder, pending, history, as_of=time.time())
