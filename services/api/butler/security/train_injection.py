"""训练并评估提示注入分类器。

    python -m butler.security.train_injection --handbook <手册目录> [--write]

评估口径：
- leave-one-family-out：留出一个攻击族，训练时完全没见过，测它的召回（泛化能力）
- 负例按“文档”划分训练/验证/测试；困难负例按“模板”划分
- 阈值在验证集上定到“真实负例误报率 ≤ 0.3%”，测试集上报告最终数字
- 基线：只用规则 / 只用旧式关键词
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import random
import re
from pathlib import Path

import numpy as np
from scipy import sparse
from sklearn.linear_model import LogisticRegression

from ..redteam.benchmark import load_handbook
from . import injection as inj
from .injection_data import FAMILIES, HARD_NEGATIVES, HN_TEMPLATES, hard_negatives, positives

FPR_TARGET = 0.003
MODEL_OUT = inj.MODEL_PATH
META_OUT = MODEL_OUT.with_name("injection-v1.meta.json")


def sentences(docs) -> list[str]:
    out = []
    for d in docs:
        for s in re.split(r"(?<=[.!?。！？])\s+", d.text):
            if 40 <= len(s) <= 220 and "http" not in s:
                out.append(s.strip())
    return out


def windows_from_docs(docs, rng, per_doc=4) -> list[str]:
    """负例：真实文档里的检测单元（句子或相邻两句），与线上 scan 看到的东西一致。"""
    out = []
    for d in docs:
        units = [u for u in inj.windows(d.text) if len(u) > 20]
        out += rng.sample(units, min(len(units), per_doc * 6))
    return out


def build_matrix(texts, vocab=None, idf=None):
    counts = [inj.grams(t) for t in texts]
    if vocab is None:
        df = {}
        for c in counts:
            for g in c:
                df[g] = df.get(g, 0) + 1
        terms = sorted(g for g, n in df.items() if n >= 3)
        vocab = {g: i for i, g in enumerate(terms)}
        idf = np.array([np.log((1 + len(texts)) / (1 + df[g])) + 1 for g in terms])
    rows, cols, vals = [], [], []
    for r, c in enumerate(counts):
        row = {vocab[g]: (1 + np.log(tf)) * idf[vocab[g]] for g, tf in c.items() if g in vocab}
        n = np.sqrt(sum(v * v for v in row.values())) or 1.0
        for j, v in row.items():
            rows.append(r), cols.append(j), vals.append(v / n)
    return sparse.csr_matrix((vals, (rows, cols)), shape=(len(texts), len(vocab))), vocab, idf


def fit(train, C=8.0):
    X, vocab, idf = build_matrix([x["text"] for x in train])
    y = np.array([x["label"] for x in train])
    clf = LogisticRegression(C=C, max_iter=2000, class_weight="balanced")
    clf.fit(X, y)
    return clf, vocab, idf


def scores(clf, vocab, idf, texts):
    X, _, _ = build_matrix(texts, vocab, idf)
    return clf.predict_proba(X)[:, 1]


def pick_threshold(neg_scores, target=FPR_TARGET):
    s = np.sort(neg_scores)
    k = int(np.ceil(len(s) * (1 - target)))
    return float(min(0.999, max(0.5, s[min(k, len(s) - 1)] + 1e-6)))


def make_data(docs, seed):
    rng = random.Random(seed)
    order = sorted(docs, key=lambda d: hashlib.sha256((str(seed) + d.id).encode()).hexdigest())
    n = len(order)
    split = {"train": order[: int(n * 0.6)], "val": order[int(n * 0.6): int(n * 0.8)], "test": order[int(n * 0.8):]}
    ctx = {k: sentences(v) or ["The team meets weekly to review progress."] for k, v in split.items()}
    tmpl = list(HN_TEMPLATES)
    rng.shuffle(tmpl)
    hn_split = {"train": tmpl[:9], "val": tmpl[9:12], "test": tmpl[12:]}
    data = {}
    for k in split:
        neg = [{"text": t, "label": 0, "family": "handbook"} for t in windows_from_docs(split[k], rng, 4 if k == "train" else 3)]
        hn = hard_negatives(rng, hn_split[k], 250 if k == "train" else 120, ctx[k])
        if k == "train":
            hn += [{"text": t, "label": 0, "family": "hard_negative"} for t in HARD_NEGATIVES]
        pos = positives(rng, list(FAMILIES), 160 if k == "train" else 100, ctx[k])
        data[k] = {"neg": neg, "hn": hn, "pos": pos, "chunks": chunk_texts(split[k])}
    return data


def chunk_scores(clf, vocab, idf, texts):
    """整块文本的分数 = 各推理窗口分数的最大值（与线上 scan 一致）；阈值与误报率都按块来算。"""
    wins = [inj.windows(t) for t in texts]
    flat = [w for ws in wins for w in ws]
    sc = scores(clf, vocab, idf, flat) if flat else np.array([])
    out, i = [], 0
    for ws in wins:
        out.append(float(np.max(sc[i:i + len(ws)])))
        i += len(ws)
    return np.array(out)


def chunk_texts(docs, size=2000):
    out = []
    for d in docs:
        t = d.text
        out += [t[i:i + size] for i in range(0, max(len(t) - 400, 1), size) if len(t[i:i + size]) > 300]
    return out


def rates(clf_scores_pos, clf_scores_neg, thr):
    return float(np.mean(clf_scores_pos >= thr)), float(np.mean(clf_scores_neg >= thr))


def run(docs, seed=11, quick=False):
    data = make_data(docs, seed)
    train = data["train"]["neg"] + data["train"]["hn"] + data["train"]["pos"]
    report = {"seed": seed, "sizes": {k: {t: len(v) for t, v in d.items()} for k, d in data.items()}, "lofo": {}, "unit": "chunk (max over inference windows)"}
    for fam in ([] if quick else FAMILIES):  # leave-one-family-out
        tr = [x for x in train if x["family"] != fam]
        clf, vocab, idf = fit(tr)
        val_neg = chunk_scores(clf, vocab, idf, data["val"]["chunks"])
        thr = pick_threshold(val_neg)
        pos = chunk_scores(clf, vocab, idf, [x["text"] for x in data["test"]["pos"] if x["family"] == fam])
        neg = chunk_scores(clf, vocab, idf, data["test"]["chunks"])
        hn = chunk_scores(clf, vocab, idf, [x["text"] for x in data["test"]["hn"]])
        rule_recall = float(np.mean([bool(inj.rule_hits(x["text"])) for x in data["test"]["pos"] if x["family"] == fam]))
        report["lofo"][fam] = {"recall_model_only": round(float(np.mean(pos >= thr)), 3),
                               "recall_rules_only": round(rule_recall, 3),
                               "recall_cascade": round(float(np.mean([(s >= thr) or bool(inj.rule_hits(x["text"])) for s, x in zip(
                                   pos, [x for x in data["test"]["pos"] if x["family"] == fam])])), 3),
                               "fpr_handbook": round(float(np.mean(neg >= thr)), 4), "fpr_hard_negative": round(float(np.mean(hn >= thr)), 4)}
    clf, vocab, idf = fit(train)
    val_neg = chunk_scores(clf, vocab, idf, data["val"]["chunks"])
    thr = pick_threshold(val_neg)
    te = data["test"]
    pos_s = chunk_scores(clf, vocab, idf, [x["text"] for x in te["pos"]])
    neg_s = chunk_scores(clf, vocab, idf, te["chunks"])
    hn_s = chunk_scores(clf, vocab, idf, [x["text"] for x in te["hn"]])
    casc = lambda scs, xs: np.mean([(s >= thr) or bool(inj.rule_hits(x["text"] if isinstance(x, dict) else x)) for s, x in zip(scs, xs)])
    report["final"] = {"threshold": round(thr, 4),
                       "recall_in_distribution": round(float(np.mean(pos_s >= thr)), 3),
                       "recall_cascade": round(float(casc(pos_s, te["pos"])), 3),
                       "recall_rules_only": round(float(np.mean([bool(inj.rule_hits(x["text"])) for x in te["pos"]])), 3),
                       "fpr_handbook": round(float(np.mean(neg_s >= thr)), 4),
                       "fpr_handbook_cascade": round(float(casc(neg_s, te["chunks"])), 4),
                       "fpr_hard_negative": round(float(np.mean(hn_s >= thr)), 4),
                       "fpr_hard_negative_cascade": round(float(casc(hn_s, te["hn"])), 4),
                       "fpr_hard_negative_rules_only": round(float(np.mean([bool(inj.rule_hits(x["text"])) for x in te["hn"]])), 4)}
    if report["lofo"]:
        report["lofo_mean_recall_cascade"] = round(float(np.mean([v["recall_cascade"] for v in report["lofo"].values()])), 3)
        report["lofo_mean_recall_model_only"] = round(float(np.mean([v["recall_model_only"] for v in report["lofo"].values()])), 3)
    return report, (clf, vocab, idf, thr)


def export(fitted, path: Path):
    clf, vocab, idf, thr = fitted
    terms = [None] * len(vocab)
    for g, i in vocab.items():
        terms[i] = g
    payload = {"terms": terms, "idf": [round(float(x), 5) for x in idf], "coef": [round(float(x), 5) for x in clf.coef_[0]],
               "intercept": round(float(clf.intercept_[0]), 5), "threshold": thr}
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--handbook", required=True, type=Path)
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--write", action="store_true", help="写出模型与指标")
    p.add_argument("--quick", action="store_true", help="跳过 leave-one-family-out，只训练并评估最终模型")
    a = p.parse_args(argv)
    docs = load_handbook(a.handbook)
    report, fitted = run(docs, a.seed, a.quick)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if a.write:
        export(fitted, MODEL_OUT)
        report["training_data"] = {"negatives": "GitLab handbook (CC BY-SA 4.0) windows + templated hard negatives",
                                   "positives": "templated attack families embedded in handbook sentences", "handbook_docs": len(docs)}
        META_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已写出 {MODEL_OUT} ({MODEL_OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
