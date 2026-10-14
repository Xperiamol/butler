"""前提发现 v2：词法 + 中文语义特征，只用评测集 dev 切分训练，按事件类型分组交叉验证。

    python -m butler.security.train_premises_dev [--write]

指标（样本外）：
- 自己的碎片被发现的比例（召回）、误报资料数
- 防护有效性：quorum=2（发现的前提里暴露任意 2 份就拦）与 all（发现的前提全部暴露才拦）两种语义下，
  攻击者拿到自己全部碎片时被拦住的比例
- 误拦：用户看了别条链（同类事件）的两份碎片，被这条链的前提规则误拦的比例
"""
from __future__ import annotations
import argparse
import itertools
import json
import math
import random
from collections import Counter

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold

from ..answer.semantic import ZhEncoder, cjk_ratio
from ..redteam import eval_set as E
from . import premises as P

ACLS = lambda chains: {**{f"s:{c['id']}": {"exec"} for c in chains}}


def collect(chains, background):
    enc = ZhEncoder()
    cdocs, _ = E.chain_world(chains)
    texts = {d.id: d.title + "\n" + d.text for d in cdocs + background}
    acls = {d.id: set(d.acl) for d in cdocs + background}
    corpus = P.Corpus.build(list(texts.items()))
    rows = []
    for c in chains:
        sid, stmt = f"s:{c['id']}", c["conclusion"]
        own = {f"f:{c['id']}:{i}" for i in range(len(c["fragments"]))}
        secret_tf = P.Counter(P.terms(stmt + "\n" + texts[sid]))
        stmt_tf = P.Counter(P.terms(stmt))
        semb = P._EMB.embed([(stmt + "\n" + texts[sid])[:2000]])[0]
        skip = {corpus.ids.index(sid)} | {i for i, d in enumerate(corpus.ids) if d not in P.eligible_premises(acls, sid)}
        cands = P.candidates(corpus, secret_tf, skip)
        seen = {i for i, _ in cands}
        cands += [(i, 40) for i in P.semantic_candidates(enc, corpus, texts, stmt, skip) if i not in seen]
        for i, rank in cands:
            did = corpus.ids[i]
            f = P.pair_features(corpus, secret_tf, stmt_tf, semb, i, texts[did], rank) + P.sem_features(enc, texts[did], stmt)
            rows.append({"chain": c["id"], "type": c["event_type"], "doc": did, "y": int(did in own), "x": f, "own": own})
    return rows


def policy(rows_by_chain, probs, thr, k=4):
    """每条链：取概率 ≥ thr 的前 k 个；不足 2 份就不启用。"""
    out = {}
    for cid, idx in rows_by_chain.items():
        top = sorted([i for i in idx if probs[i] >= thr], key=lambda i: -probs[i])[:k]
        out[cid] = [i for i in top]
    return out


def evaluate(rows, probs, thr):
    by = {}
    for i, r in enumerate(rows):
        by.setdefault(r["chain"], []).append(i)
    pol = policy(by, probs, thr)
    own_of = {r["chain"]: r["own"] for r in rows}
    stats = Counter()
    disc = {}
    for cid, idx in pol.items():
        D = {rows[i]["doc"] for i in idx}
        disc[cid] = D if len(D) >= 2 else set()
        own = own_of[cid]
        stats["chains"] += 1
        stats["enabled"] += len(disc[cid]) >= 2
        stats["found_own"] += len(D & own)
        stats["total_own"] += len(own)
        stats["false_found"] += len(D - own)
        stats["quorum2_blocks_attacker"] += len(disc[cid] & own) >= 2
        stats["all_blocks_attacker"] += bool(disc[cid]) and disc[cid] <= own
    rng = random.Random(3)
    frags = {c: sorted(o) for c, o in own_of.items()}
    fp = trials = 0
    for cid in pol:
        others = [f for c2, fs in frags.items() if c2 != cid for f in fs]
        for _ in range(40):
            a, b = rng.sample(others, 2)
            trials += 1
            fp += len(disc[cid] & {a, b}) >= 2
    n = stats["chains"]
    return {"enabled": round(stats["enabled"] / n, 3), "fragment_recall": round(stats["found_own"] / stats["total_own"], 3),
            "false_premises_per_chain": round(stats["false_found"] / n, 2),
            "attacker_blocked_quorum2": round(stats["quorum2_blocks_attacker"] / n, 3),
            "attacker_blocked_all": round(stats["all_blocks_attacker"] / n, 3),
            "benign_two_other_fragments_blocked_quorum2": round(fp / trials, 3)}


def run(write=False):
    from .train_premises import MODEL_OUT   # v1 路径；v2 另存
    chains = E.load_split("chains", "dev")
    rows = collect(chains, E.handbook_docs())
    X = np.array([r["x"] for r in rows]); y = np.array([r["y"] for r in rows]); g = np.array([r["type"] for r in rows])
    mean, std = X.mean(0), X.std(0) + 1e-6
    Z = (X - mean) / std
    best = None
    for C in (0.1, 0.3, 1.0, 3.0):
        oof = np.zeros(len(y))
        for tr, te in GroupKFold(3).split(Z, y, g):
            oof[te] = LogisticRegression(C=C, max_iter=3000, class_weight="balanced").fit(Z[tr], y[tr]).predict_proba(Z[te])[:, 1]
        m = {thr: evaluate(rows, oof, thr) for thr in (0.5, 0.6, 0.7, 0.8, 0.9)}
        score = max(v["attacker_blocked_quorum2"] - 0.5 * v["benign_two_other_fragments_blocked_quorum2"] for v in m.values())
        if best is None or score > best[0]:
            best = (score, C, oof, m)
    _, C, oof, m = best
    thr = max(m, key=lambda t: m[t]["attacker_blocked_quorum2"] - 0.5 * m[t]["benign_two_other_fragments_blocked_quorum2"] - 0.05 * m[t]["false_premises_per_chain"])
    report = {"candidates": len(rows), "positives": int(y.sum()), "C": C, "threshold": thr, "cv_by_event_type": m[thr], "all_thresholds": m}
    clf = LogisticRegression(C=C, max_iter=3000, class_weight="balanced").fit(Z, y)
    model = {"coef": clf.coef_[0].tolist(), "intercept": float(clf.intercept_[0]), "threshold": thr, "mean": mean.tolist(), "std": std.tolist(), "quorum": 2,
             "features": P.FEATURES + P.SEM_NAMES}
    if write:
        out = MODEL_OUT.with_name("premises-v2.json")
        out.write_text(json.dumps(model), encoding="utf-8")
        out.with_name("premises-v2.meta.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--write", action="store_true"); a = ap.parse_args()
    print(json.dumps(run(a.write), ensure_ascii=False, indent=2))
