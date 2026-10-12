"""索引流水线：文档 → 切块 → 向量 → 原子写入。

三段式，网络调用（向量化）不持有数据库锁：
  1. 短事务：读文档、判断哪些需要（重新）索引、查已有向量
  2. 事务外：只对“模型+输入哈希”没见过的块调用向量化
  3. 短事务：再确认文档版本没变，换掉旧块、写入新块和向量，并递增 index_epoch
块不保存权限：检索时与 documents 表里当前的 ACL 关联，权限变化不需要重新向量化。
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass

from sqlalchemy import select

from .. import database as D
from .chunking import split_document
from .embedding import Embedder, to_bytes

EMBED_BATCH = 64


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def doc_hash(doc: dict) -> str:
    return doc.get("content_hash") or sha(doc["text"])[:16]


def embed_input(title: str, heading: str, text: str) -> str:
    """送去向量化的文本带上标题与小节路径：块脱离上下文后仍能表达“它在讲什么”。"""
    return "\n".join(x for x in (title, heading, text) if x)


def chunk_rows(doc: dict) -> list[dict]:
    h = doc_hash(doc)
    rows = []
    for c in split_document(doc["text"]):
        inp = embed_input(doc["title"], c.heading, c.text)
        rows.append({"id": f"{doc['id']}#{h}:{c.seq}", "doc_id": doc["id"], "content_hash": h, "seq": c.seq,
                     "start": c.start, "end": c.end, "tokens": c.tokens, "heading": c.heading, "text": c.text,
                     "text_hash": sha(inp), "_input": inp})
    return rows


@dataclass
class IndexStats:
    documents: int = 0
    chunks: int = 0
    embedded: int = 0
    reused: int = 0
    skipped: int = 0


def index_documents(database, embedder: Embedder, doc_ids: list[str] | None = None) -> IndexStats:
    stats = IndexStats()
    # 1) 读取并规划
    with database.transaction() as tx:
        docs = [d for d in (tx.all("document") if doc_ids is None else [tx.get("document", i) for i in doc_ids]) if d]
        have = {(r.doc_id, r.content_hash) for r in tx.connection.execute(select(D.chunks.c.doc_id, D.chunks.c.content_hash).distinct())}
        todo = [d for d in docs if (d["id"], doc_hash(d)) not in have]
        stats.skipped = len(docs) - len(todo)
        planned = {d["id"]: chunk_rows(d) for d in todo}
        hashes = {r["text_hash"] for rows in planned.values() for r in rows}
        known = set()
        if hashes:
            for batch in _batched(sorted(hashes), 500):
                known |= set(tx.connection.execute(select(D.embeddings.c.text_hash).where(
                    D.embeddings.c.model == embedder.name, D.embeddings.c.text_hash.in_(batch))).scalars())
    # 2) 向量化（无锁）
    need: dict[str, str] = {}
    for rows in planned.values():
        for r in rows:
            if r["text_hash"] not in known:
                need[r["text_hash"]] = r["_input"]
    vectors = {}
    items = list(need.items())
    for batch in _batched(items, EMBED_BATCH):
        mat = embedder.embed([t for _, t in batch])
        for (h, _), v in zip(batch, mat):
            vectors[h] = v
    stats.embedded, stats.reused = len(vectors), len(hashes) - len(vectors)
    # 3) 原子换版本
    with database.transaction() as tx:
        for doc in todo:
            current = tx.get("document", doc["id"])
            if not current or doc_hash(current) != doc_hash(doc):
                stats.skipped += 1  # 规划期间文档又被更新了，下一次索引会处理新版本
                continue
            tx.connection.execute(D.chunks.delete().where(D.chunks.c.doc_id == doc["id"]))
            rows = [{k: v for k, v in r.items() if k != "_input"} for r in planned[doc["id"]]]
            if rows:
                tx.connection.execute(D.chunks.insert(), rows)
            stats.documents += 1
            stats.chunks += len(rows)
        ins = D._insert(tx.connection)
        for h, v in vectors.items():
            tx.connection.execute(ins(D.embeddings).values(model=embedder.name, text_hash=h, dim=len(v),
                                                           vector=to_bytes(v)).on_conflict_do_nothing())
        if stats.documents:
            epoch = tx.get("meta", "index_epoch", {"value": 0})["value"] + 1
            tx.put("meta", "index_epoch", {"value": epoch})
    return stats


def remove_document(tx, doc_id: str) -> None:
    """删除文档时同时清掉它派生的块（向量按内容哈希共享，留着无害，可由维护任务回收）。"""
    tx.connection.execute(D.chunks.delete().where(D.chunks.c.doc_id == doc_id))
    tx.delete("document", doc_id)


def _batched(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]
