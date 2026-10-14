"""前提自动发现：给一条受限结论，找出"合在一起能推出它"的其他资料，填进 Fact.premises。

没有它，依赖闭包防护要靠导入方手工登记前提。这里用一个训练出的线性打分器（权重存 JSON）给
（受限结论, 候选资料）对打分：共享的稀有词（代号、公司名、编号……）越多、越集中，越可能是前提。

只在管理侧离线运行（用全库的词频），输出的是前提资料编号，不暴露给提问者。
限制：只能发现与结论共享稀有词的资料；完全不提实体的碎片（"某供应商签了保密协议"）发现不了，仍需人工登记。
"""
from __future__ import annotations
import json
import math
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..ingest.embedding import HashingEmbedder
from ..retrieval.store import terms

MODEL_PATH = Path(__file__).parent / "models" / "premises-v1.json"
RARE_DF = 0.03          # 出现在不超过 3% 文档里的词算"稀有"
MAX_PREMISES = 4
FEATURES = ["cover_mass", "shared_log", "max_idf", "specificity", "tfidf_cos", "embed_cos", "stmt_overlap", "top3_share", "top1_in"]
_EMB = HashingEmbedder(256)


@dataclass
class Corpus:
    """全库统计：df / idf / 每篇的词频，用于给候选打特征。"""
    ids: list[str]
    tf: list[Counter]
    idf: dict[str, float]
    n: int

    @classmethod
    def build(cls, docs: list[tuple[str, str]]) -> "Corpus":
        tf = [Counter(terms(t)) for _, t in docs]
        df: Counter = Counter()
        for c in tf:
            df.update(c.keys())
        n = len(docs)
        return cls([i for i, _ in docs], tf, {t: math.log(1 + n / c) for t, c in df.items()}, n)

    def rare(self, c: Counter) -> dict[str, float]:
        cut = max(2, RARE_DF * self.n)
        return {t: self.idf[t] for t in c if t in self.idf and math.exp(self.idf[t]) - 1 >= self.n / cut}


def sem_features(enc, cand_text: str, statement: str, idf: dict | None = None) -> list[float]:
    from ..answer.semantic import pair_features as sem_pair
    f = sem_pair(enc, cand_text[:300], statement, idf)
    return [f[i] for i in SEM_IDX]


def pair_features(corpus: Corpus, secret_tf: Counter, stmt_tf: Counter, secret_emb: np.ndarray, cand_idx: int,
                  cand_text: str, rank: int) -> list[float]:
    cand = corpus.tf[cand_idx]
    rs, rc = corpus.rare(secret_tf), corpus.rare(cand)
    shared = set(rs) & set(rc)
    mass = sum(rs[t] for t in shared)
    s_total, c_total = sum(rs.values()) or 1.0, sum(rc.values()) or 1.0
    dot = sum(corpus.idf.get(t, 0) ** 2 * secret_tf[t] * cand[t] for t in set(secret_tf) & set(cand))
    ns = math.sqrt(sum((corpus.idf.get(t, 0) * v) ** 2 for t, v in secret_tf.items())) or 1.0
    nc = math.sqrt(sum((corpus.idf.get(t, 0) * v) ** 2 for t, v in cand.items())) or 1.0
    emb = float(_EMB.embed([cand_text[:2000]])[0] @ secret_emb)
    stmt_shared = len(set(rs) & set(stmt_tf) & set(rc))
    # 结论自己最稀有的几个词（通常就是代号/公司名）有多少出现在候选里：比"共享了多少稀有词"更抗模板套话
    rarest = sorted(rs, key=lambda t: -rs[t])[:3]
    top3 = sum(rs[t] for t in rarest if t in rc) / (sum(rs[t] for t in rarest) or 1.0)
    return [mass / s_total, math.log1p(len(shared)), max((rs[t] for t in shared), default=0.0) / 8.0, mass / c_total,
            dot / (ns * nc), emb, math.log1p(stmt_shared), top3, float(bool(rarest) and rarest[0] in rc)]


SEM_IDX = [0, 1, 2, 3, 14, 16, 12]      # semantic.pair_features 里取哪几个：均值余弦、软覆盖、调和、加权覆盖、SIF 余弦、对齐比例
SEM_NAMES = ["sem_mean_cos", "sem_c2a", "sem_a2c", "sem_h", "sem_cover_w", "sem_sif", "sem_align50"]


@dataclass
class Model:
    coef: list[float]
    intercept: float
    threshold: float
    mean: list[float] | None = None     # 有 mean/std 的是带语义特征的 v2
    std: list[float] | None = None
    quorum: int = 0                     # >0：自动发现的前提不要求"全部"暴露，只要求暴露其中的 quorum 份

    @property
    def semantic(self) -> bool:
        return self.mean is not None

    def prob(self, f: list[float]) -> float:
        if self.mean is not None:
            f = [(x - m) / sd for x, m, sd in zip(f, self.mean, self.std)]
        z = self.intercept + sum(c * x for c, x in zip(self.coef, f))
        return 1 / (1 + math.exp(-max(min(z, 30), -30)))


@lru_cache(maxsize=1)
def load_model(path: Path | None = None) -> Model | None:
    """带语义特征的 v2（需要中文词向量）优先；词向量不可用时退回 v1（只用词法特征）。"""
    if path is None:
        v2 = MODEL_PATH.with_name("premises-v2.json")
        if v2.exists():
            from ..answer.semantic import shared_encoder
            if shared_encoder().available():
                path = v2
        path = path or MODEL_PATH
    if not Path(path).exists():
        return None
    d = json.loads(Path(path).read_text())
    return Model(d["coef"], d["intercept"], d["threshold"], d.get("mean"), d.get("std"), d.get("quorum", 0))


def candidates(corpus: Corpus, secret_tf: Counter, exclude: set[int], k: int = 40) -> list[tuple[int, int]]:
    """按共享稀有词信息量预筛前 k 个候选，返回 (文档下标, 名次)。"""
    rs = corpus.rare(secret_tf)
    scored = []
    for i, c in enumerate(corpus.tf):
        if i in exclude:
            continue
        m = sum(w for t, w in rs.items() if t in c)
        if m > 0:
            scored.append((m, i))
    scored.sort(reverse=True)
    return [(i, r) for r, (_, i) in enumerate(scored[:k])]


def eligible_premises(acls: dict[str, set[str]], source_doc: str) -> set[str]:
    """前提必须是“有人读得到、而这个人读不到该机密”的资料：ACL 不被来源文档的 ACL 包含。
    其他同级别的机密文档不可能构成前提（读得到它们的人本来就能读机密）。"""
    secret = acls[source_doc]
    return {d for d, a in acls.items() if d != source_doc and a and not a <= secret}


def semantic_candidates(enc, corpus: Corpus, texts: dict[str, str], statement: str, skip: set[int], k: int = 30) -> list[int]:
    """语义预筛：与结论的均值向量余弦最高的 k 篇（词法预筛看不到只用代称的碎片）。"""
    from ..answer.semantic import cjk_ratio
    q = enc.embed(statement)[1]
    if not len(q):
        return []
    qv = q.mean(0) / (np.linalg.norm(q.mean(0)) + 1e-9)
    scored = []
    for i, did in enumerate(corpus.ids):
        if i in skip or cjk_ratio(texts[did][:300]) < 0.25:
            continue
        m = enc.embed(texts[did][:300])[1]
        if len(m):
            scored.append((float((m.mean(0) / (np.linalg.norm(m.mean(0)) + 1e-9)) @ qv), i))
    return [i for _, i in sorted(scored, reverse=True)[:k]]


def discover(corpus: Corpus, texts: dict[str, str], statement: str, source_doc: str, model: Model | None = None,
             max_premises: int = MAX_PREMISES, eligible: set[str] | None = None, enc=None) -> list[tuple[str, float]]:
    """返回 [(资料编号, 概率)]，按概率降序；不含来源文档本身。eligible 给出时只在其中找。"""
    model = model or load_model()
    if model is None or source_doc not in corpus.ids:
        return []
    src = corpus.ids.index(source_doc)
    secret_text = statement + "\n" + texts[source_doc]
    secret_tf, stmt_tf = Counter(terms(secret_text)), Counter(terms(statement))
    semb = _EMB.embed([secret_text[:2000]])[0]
    out = []
    skip = {src} | ({i for i, d in enumerate(corpus.ids) if d not in eligible} if eligible is not None else set())
    cands = candidates(corpus, secret_tf, skip)
    if model.semantic:
        if enc is None:
            from ..answer.semantic import shared_encoder
            enc = shared_encoder()
        seen = {i for i, _ in cands}
        cands += [(i, 40) for i in semantic_candidates(enc, corpus, texts, statement, skip) if i not in seen]
    for i, rank in cands:
        did = corpus.ids[i]
        feats = pair_features(corpus, secret_tf, stmt_tf, semb, i, texts[did], rank)
        if model.semantic:
            feats = feats + sem_features(enc, texts[did], statement)
        p = model.prob(feats)
        if p >= model.threshold:
            out.append((did, round(p, 4)))
    return sorted(out, key=lambda x: -x[1])[:max_premises]
