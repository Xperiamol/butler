"""检索评测：召回率@6（目标文档是否在前 6 篇里）与无关问题误召回率。

    python -m butler.retrieval.eval --handbook <手册目录> --n 150 --seed 3

查询类型：title（按标题问）、excerpt（取正文中间一句的实词）、noisy（excerpt 丢掉三成词并制造拼写错误）。
对比：legacy（旧的整篇二元组词法检索）/ lexical（块 + BM25）/ dense（块 + 向量）/ hybrid（RRF 融合）。
"""
from __future__ import annotations
import argparse
import json
import random
import re
from pathlib import Path

from .. import database as D
from ..database import Database
from ..ingest.embedding import HashingEmbedder
from ..ingest.index import index_documents
from ..models import Identity
from ..redteam.benchmark import load_handbook
from . import hybrid
from .store import Store

OFFTOPIC = ["recipe for lasagna with béchamel", "who won the football world cup", "quantum chromodynamics lattice gauge theory",
            "best hiking trails near Denver", "how to repair a bicycle derailleur", "symptoms of seasonal influenza",
            "火星殖民计划的时间表", "红烧肉怎么做", "今天天气怎么样", "bitcoin price prediction next week",
            "translate this poem into French", "how many moons does Jupiter have", "knitting patterns for beginners",
            "guitar chords for wonderwall", "volcano eruption in iceland", "origami crane instructions",
            "marathon training plan twelve weeks", "sourdough starter feeding schedule", "chess opening for white",
            "tectonic plates and earthquakes"]
USER = Identity("u", "U", frozenset({"all"}), "employee")


def _words(s: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z]{4,}", s)]


def make_queries(docs, n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    pool = [d for d in docs if "all" in d.acl and len(_words(d.text)) > 80]
    out = []
    for d in rng.sample(pool, min(n, len(pool))):
        sents = [s for s in re.split(r"(?<=[.!?])\s+", d.text) if len(_words(s)) >= 8]
        if not sents:
            continue
        ws = _words(rng.choice(sents[len(sents) // 4:] or sents))[:12]
        noisy = [w for w in ws if rng.random() > 0.3] or ws[:4]
        noisy = [w[:i] + w[i + 1] + w[i] + w[i + 2:] if len(w) > 5 and rng.random() < 0.5 and (i := rng.randrange(1, len(w) - 2)) else w for w in noisy]
        out += [{"doc": d.id, "kind": "title", "q": f"Tell me about {d.title}"},
                {"doc": d.id, "kind": "excerpt", "q": " ".join(ws)},
                {"doc": d.id, "kind": "noisy", "q": " ".join(noisy)}]
    return out


def hybrid_store(docs, quarantine: bool = True):
    """把文档放进内存库、建索引，返回混合检索 store（评测与基准共用）。"""
    db = Database("sqlite:///:memory:")
    with db.transaction() as tx:
        for d in docs:
            tx.put("document", d.id, {"id": d.id, "source": d.source, "title": d.title, "text": d.text, "acl": sorted(d.acl)})
    emb = HashingEmbedder()
    stats = index_documents(db, emb)
    with db.transaction() as tx:
        store = hybrid.build_store(tx, emb, hybrid.IndexCache(), [d.id for d in docs])  # 会话历史可取回任意文档的正文
    store.quarantine = quarantine
    return store, stats


def evaluate(docs, n=150, seed=3, k=6) -> dict:
    hs, stats = hybrid_store(docs)
    emb = hs.embedder
    legacy = Store(docs)
    queries = make_queries(docs, n, seed)
    saved = hybrid.DENSE_MIN, hybrid.MIN_COVERAGE

    def run(mode, q):
        if mode == "legacy":
            return [d.id for d in legacy.search(USER, q, k)]
        hybrid.DENSE_MIN, hybrid.MIN_COVERAGE = saved
        if mode == "lexical":
            hybrid.DENSE_MIN = 9.0
        if mode == "dense":
            hybrid.MIN_COVERAGE = 9.0
        try:
            return [d.id for d in hs.search(USER, q, k)]
        finally:
            hybrid.DENSE_MIN, hybrid.MIN_COVERAGE = saved

    result = {"_meta": {"docs": len(docs), "chunks": stats.chunks, "queries": len(queries), "embedder": emb.name}}
    for mode in ("legacy", "lexical", "dense", "hybrid"):
        row = {}
        for kind in ("title", "excerpt", "noisy"):
            qs = [x for x in queries if x["kind"] == kind]
            row[f"recall@{k}_{kind}"] = round(sum(x["doc"] in run(mode, x["q"]) for x in qs) / len(qs), 3)
        row["offtopic_false_positive"] = round(sum(bool(run(mode, q)) for q in OFFTOPIC) / len(OFFTOPIC), 3)
        result[mode] = row
    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--handbook", required=True, type=Path)
    p.add_argument("--n", type=int, default=150)
    p.add_argument("--seed", type=int, default=3)
    a = p.parse_args(argv)
    r = evaluate(load_handbook(a.handbook), a.n, a.seed)
    print(json.dumps(r["_meta"]))
    cols = ["recall@6_title", "recall@6_excerpt", "recall@6_noisy", "offtopic_false_positive"]
    print(f"{'mode':8}" + "".join(f"{c:>26}" for c in cols))
    for m in ("legacy", "lexical", "dense", "hybrid"):
        print(f"{m:8}" + "".join(f"{r[m][c]:>26.1%}" for c in cols))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
