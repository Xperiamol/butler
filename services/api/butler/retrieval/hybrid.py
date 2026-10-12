"""混合检索：词法（BM25 + 覆盖率闸门）与向量（精确余弦）两路召回，RRF 融合。

权限在召回之前生效：两路都只在“提问者可见文档”的块上打分，统计量（IDF、平均长度）也只来自可见文档，
受限文档的词频、向量都不会影响任何人的排序。不是先全局 top-k 再删。

pgvector 的 ANN 过滤会影响返回数量（见 docs/implementation-audit.md），所以这里先用精确向量搜索建立基准；
块数上万以后再评估 HNSW + 迭代扫描。
"""
from __future__ import annotations
import math
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
from .store import _GLUE, _SPLIT, terms

K1, B = 1.2, 0.75
MIN_COVERAGE = 0.5       # 词法闸门：命中提问信息量的比例，校准见 docs/retrieval-eval.md
UNSEEN_WEIGHT = 1.0
CJK_MIN_COVERAGE = 0.25  # 中文二元组覆盖率天然偏低（问法和文档用词不同），单独校准
CJK_UNSEEN_WEIGHT = 0.25
DENSE_MIN = 0.30         # 向量闸门：余弦下限，校准见 docs/retrieval-eval.md
POOL = 30
RRF_K = 60
MAX_DOCS = 6
MAX_CHUNKS = 10


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

    def view(self, doc_ids: frozenset) -> _View:
        if doc_ids not in self._views:
            rows = [i for d in sorted(doc_ids) if d in self.by_doc for i in self.by_doc[d][1]]
            if len(self._views) > 64:
                self._views.clear()
            self._views[doc_ids] = _View(self.chunks, rows)
        return self._views[doc_ids]


def load_index(tx, embedder: Embedder) -> ChunkIndex:
    epoch = tx.get("meta", "index_epoch", {"value": 0})["value"]
    rows = tx.connection.execute(select(
        D.chunks.c.id, D.chunks.c.doc_id, D.chunks.c.content_hash, D.chunks.c.start, D.chunks.c.end, D.chunks.c.heading,
        D.chunks.c.text, D.chunks.c.text_hash, D.documents.c.title
    ).join(D.documents, D.documents.c.id == D.chunks.c.doc_id).order_by(D.chunks.c.doc_id, D.chunks.c.seq)).all()
    vecs = {r.text_hash: r for r in tx.connection.execute(select(D.embeddings).where(D.embeddings.c.model == embedder.name))}
    dim = next((r.dim for r in vecs.values()), embedder.dim or 1)
    chunks, mat = [], np.zeros((len(rows), dim), dtype=np.float32)
    for i, (cid, did, ch, s, e, heading, text, th, title) in enumerate(rows):
        t = terms(f"{title} {heading} {text}")
        chunks.append(_Chunk(cid, did, ch, s, e, heading, text, title or "", Counter(t), max(len(t), 1)))
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
    last_debug: dict = field(default_factory=dict)

    def _doc(self, m: dict, text: str = "") -> Doc:
        return Doc(m["id"], m["source"], m["title"], text, frozenset(m["acl"]))

    def visible(self, identity: Identity) -> list[Doc]:
        return [self._doc(m) for m in self.metas if can_read(identity, self._doc(m))]

    def get_many(self, ids: list[str]) -> list[Doc]:
        by = {m["id"]: m for m in self.metas}
        return [self._doc(by[i], self.history.get(i, "")) for i in ids if i in by and i in self.history]

    # ---- 检索 ----
    def search(self, identity: Identity, query: str, k: int = MAX_DOCS) -> list[Doc]:
        by = {m["id"]: m for m in self.metas}
        vis = {m["id"]: m for m in self.metas if can_read(identity, self._doc(m))}      # 先过滤
        fresh = frozenset(d for d, m in vis.items() if self.index.has(d, m["content_hash"]))
        lag = [d for d in vis if d not in fresh]
        chunks, rows = self.index.chunks, self.index.view(fresh).rows
        vectors = self.index.vectors
        extra: list[_Chunk] = []
        for d in lag:
            doc = self.pending.get(d)
            if doc:
                for r in chunk_rows(doc):
                    t = terms(f"{doc['title']} {r['heading']} {r['text']}")
                    extra.append(_Chunk(r["id"], d, r["content_hash"], r["start"], r["end"], r["heading"], r["text"],
                                        doc["title"], Counter(t), max(len(t), 1)))
        pool = [chunks[i] for i in rows] + extra
        if not pool:
            return []
        view = self.index.view(fresh) if not extra else _View(pool, list(range(len(pool))))
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
    metas = [{"id": r.id, "source": r.source, "title": r.title, "acl": r.acl, "content_hash": r.content_hash}
             for r in tx.connection.execute(select(D.documents.c.id, D.documents.c.source, D.documents.c.content_hash,
                                                   D.documents.c.title, D.documents.c.acl))]
    for m in metas:
        if not m["content_hash"]:  # 旧数据没有哈希：用正文现算
            m["content_hash"] = doc_hash(tx.get("document", m["id"]))
    index = cache.get(tx, embedder)
    pending = {m["id"]: tx.get("document", m["id"]) for m in metas if not index.has(m["id"], m["content_hash"])}
    history = {i: tx.get("document", i)["text"] for i in history_ids if tx.get("document", i)}
    return HybridStore(metas, index, embedder, pending, history)
