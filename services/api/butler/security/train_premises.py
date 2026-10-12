"""训练并评估前提发现模型。

    python -m butler.security.train_premises --handbook <手册目录> [--write]

训练：premise_data.KINDS 里的 8 种事件类型 × 3 种关联方式，真实手册文档当背景（按文档划分训练/验证/测试）。
评估：用 redteam.benchmark.KINDS 的三种**没训练过的**事件类型（收购/裁员/泄露），含"孤儿碎片"（不提任何实体）。
指标：前提召回、每条结论的误报资料数（把无关资料当前提会造成误拦）。
"""
from __future__ import annotations
import argparse
import hashlib
import json
import random
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression

from ..redteam import benchmark as B
from ..redteam.benchmark import CODENAMES, TARGETS, load_handbook
from . import premise_data as PD
from . import premises as P

MODEL_OUT = P.MODEL_PATH
META_OUT = MODEL_OUT.with_name("premises-v1.meta.json")


def build_world(background, chains, extra_docs=()):
    """chains: [{secret, statement, a, b, ...}] → (docs[(id,text)], truth{chain_id: {a_id,b_id,secret_id}})"""
    docs = [(d.id, d.title + "\n" + d.text) for d in background]
    truth = {}
    for c in chains:
        sid, aid, bid = f"s{c['id']}", f"a{c['id']}", f"b{c['id']}"
        docs += [(sid, c["secret"]), (aid, f"Update {c['id']}\n" + c["a"]), (bid, f"Notes {c['id']}\n" + c["b"])]
        truth[c["id"]] = {"secret": sid, "a": aid, "b": bid}
    docs += list(extra_docs)
    return docs, truth


def acls_for(docs):
    """合成世界的权限：机密（s 开头）只有 exec；其余（背景文档、碎片）人人可读。"""
    return {i: ({"exec"} if i.startswith("s") and i[1:].isdigit() else {"all", "exec"}) for i, _ in docs}


def featurize(chains, truth, docs):
    corpus = P.Corpus.build(docs)
    texts = dict(docs)
    acls = acls_for(docs)
    X, y, meta = [], [], []
    for c in chains:
        t = truth[c["id"]]
        secret_text = c["statement"] + "\n" + texts[t["secret"]]
        stf, mtf = P.Counter(P.terms(secret_text)), P.Counter(P.terms(c["statement"]))
        semb = P._EMB.embed([secret_text[:2000]])[0]
        src = corpus.ids.index(t["secret"])
        ok = P.eligible_premises(acls, t["secret"])
        for i, rank in P.candidates(corpus, stf, {src} | {j for j, d in enumerate(corpus.ids) if d not in ok}):
            did = corpus.ids[i]
            X.append(P.pair_features(corpus, stf, mtf, semb, i, texts[did], rank))
            y.append(int(did in (t["a"], t["b"])))
            meta.append((c["id"], did))
    return np.array(X), np.array(y), meta, corpus


def split_docs(docs, seed):
    order = sorted(docs, key=lambda d: hashlib.sha256((str(seed) + d.id).encode()).hexdigest())
    n = len(order)
    return order[: int(n * 0.6)], order[int(n * 0.6): int(n * 0.8)], order[int(n * 0.8):]


def orphan_chains(n, seed):
    """评测用：基准里的三种未训练事件类型；其中一部分让碎片 B 完全不提实体（孤儿）。"""
    rng = random.Random(seed)
    cs, ts = rng.sample(CODENAMES, n), rng.sample(TARGETS, n)
    out = []
    for i in range(n):
        k = B.KINDS[i % len(B.KINDS)]
        orphan = i % 5 == 4
        b = k["b"].format(c=cs[i], t=ts[i])
        if orphan:
            b = {"acquisition": "A mutual NDA was signed with a counterparty and a data room was opened for due diligence.",
                 "layoff": "The integration team was told to move its roadmap documents to an archive folder.",
                 "breach": "Outbound traffic from the integration database spiked to ten times normal volume."}[k["kind"]]
        out.append({"id": i, "secret": k["secret"].format(c=cs[i], t=ts[i]), "statement": k["statement"].format(c=cs[i], t=ts[i]),
                    "a": k["a"].format(c=cs[i], t=ts[i]), "b": b, "orphan": orphan, "kind": k["kind"]})
    return out


def evaluate(model, chains, truth, docs, corpus):
    texts, acls = dict(docs), acls_for(docs)
    rows = []
    for c in chains:
        t = truth[c["id"]]
        found = {d for d, _ in P.discover(corpus, texts, c["statement"], t["secret"], model, eligible=P.eligible_premises(acls, t["secret"]))}
        rows.append({"a": t["a"] in found, "b": t["b"] in found, "false": len(found - {t["a"], t["b"]}), "orphan": c.get("orphan", False),
                     "both": {t["a"], t["b"]} <= found, "n": len(found)})
    pick = lambda f, rs: [f(r) for r in rs]
    normal = [r for r in rows if not r["orphan"]]
    return {"chains": len(rows), "orphans": sum(r["orphan"] for r in rows),
            "recall_both_non_orphan": round(float(np.mean([r["both"] for r in normal])), 3),
            "recall_fragment_a": round(float(np.mean(pick(lambda r: r["a"], rows))), 3),
            "recall_fragment_b_orphan": round(float(np.mean([r["b"] for r in rows if r["orphan"]] or [0])), 3),
            "avg_false_premises_per_fact": round(float(np.mean(pick(lambda r: r["false"], rows))), 3),
            "facts_with_any_false_premise": round(float(np.mean(pick(lambda r: r["false"] > 0, rows))), 3)}


def run(handbook_docs, seed=5):
    tr, va, te = split_docs(handbook_docs, seed)
    codes, targets = CODENAMES[:30], TARGETS[:40]
    train_chains = PD.make_chains(PD.KINDS, 48, seed, CODENAMES, TARGETS)
    docs, truth = build_world(tr, train_chains)
    X, y, _, _ = featurize(train_chains, truth, docs)
    clf = LogisticRegression(C=4.0, max_iter=2000, class_weight="balanced").fit(X, y)
    model = P.Model([float(x) for x in clf.coef_[0]], float(clf.intercept_[0]), 0.5)
    # 阈值：验证集（新的背景文档 + 新链）上，在保持召回的同时让每条结论的平均误报尽量低
    val_chains = PD.make_chains(PD.KINDS, 24, seed + 1, CODENAMES, TARGETS)
    vdocs, vtruth = build_world(va, val_chains)
    best = None
    for thr in np.arange(0.3, 0.96, 0.05):
        m = P.Model(model.coef, model.intercept, float(thr))
        r = evaluate(m, val_chains, vtruth, vdocs, P.Corpus.build(vdocs))
        score = r["recall_both_non_orphan"] - 0.5 * r["avg_false_premises_per_fact"]
        if best is None or score > best[0]:
            best = (score, float(thr), r)
    model.threshold = round(best[1], 2)
    test_chains = orphan_chains(30, seed + 2)
    tdocs, ttruth = build_world(te, test_chains)
    corpus = P.Corpus.build(tdocs)
    report = {"seed": seed, "features": P.FEATURES, "coef": [round(c, 3) for c in model.coef], "threshold": model.threshold,
              "validation": best[2], "test_unseen_kinds": evaluate(model, test_chains, ttruth, tdocs, corpus),
              "train_chains": len(train_chains), "train_pairs": int(len(y)), "positives": int(y.sum())}
    return report, model


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--handbook", required=True, type=Path)
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    report, model = run(load_handbook(a.handbook), a.seed)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if a.write:
        MODEL_OUT.write_text(json.dumps({"coef": [round(c, 5) for c in model.coef], "intercept": round(model.intercept, 5),
                                         "threshold": model.threshold}), encoding="utf-8")
        META_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写出 {MODEL_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
