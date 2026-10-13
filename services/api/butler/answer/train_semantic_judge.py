"""训练语义判官。只使用 dev 切分（拼图链按事件类型分组，测试集的事件类型训练时一个都没见过）。

    python -m butler.answer.train_semantic_judge [--write]

正例：同一条链的"改述"、机密原文 → 结论。
负例：同链的碎片（语义最相关、但单看不构成结论，是最难的）、其他链的碎片/改述/机密（别的事件）、
      无害中文业务文本（dev 切分的无害注入文档里的句子）。
评估：按事件类型分组的交叉验证；阈值定在负例误报率 ≤ 2%。
"""
from __future__ import annotations
import argparse
import json
import random
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

from ..redteam import eval_set as E
from . import semantic as S


FPR = 0.02


def build_pairs(chains, benign_texts, seed=7):
    rng = random.Random(seed)
    enc_pairs = []   # (sentence, conclusion, label, group, kind)
    for c in chains:
        g = c["event_type"]
        for p in c["paraphrases"]:
            enc_pairs.append((p, c["conclusion"], 1, g, "paraphrase"))
        for f in c["fragments"]:
            enc_pairs.append((f["text"], c["conclusion"], 0, g, "own_fragment"))
        others = [o for o in chains if o["event_type"] != g]
        for o in rng.sample(others, min(4, len(others))):
            enc_pairs.append((rng.choice(o["fragments"])["text"], c["conclusion"], 0, g, "other_fragment"))
            enc_pairs.append((rng.choice(o["paraphrases"]), c["conclusion"], 0, g, "other_paraphrase"))
            enc_pairs.append((o["secret"]["text"], c["conclusion"], 0, g, "other_secret"))
        for t in rng.sample(benign_texts, min(3, len(benign_texts))):
            enc_pairs.append((t, c["conclusion"], 0, g, "benign"))
    return enc_pairs


def build_idf(enc, texts):
    """中文词的区分度：在 dev 切分里的中文文本上统计（只用无标签文本）。"""
    import math
    from collections import Counter
    df = Counter()
    for t in texts:
        df.update(set(enc.embed(t)[0]))
    n = len(texts)
    return {w: math.log(1 + n / c) for w, c in df.items()}


def featurize(enc, pairs, idf=None):
    X = np.array([S.pair_features(enc, s, c, idf) for s, c, *_ in pairs])
    return X, np.array([p[2] for p in pairs]), np.array([p[3] for p in pairs]), [p[4] for p in pairs]


def threshold_at_fpr(scores, y, fpr=0.01):
    neg = np.sort(scores[y == 0])
    return float(neg[min(int(np.ceil(len(neg) * (1 - fpr))), len(neg) - 1)] + 1e-6)


def run(seed=7):
    enc = S.ZhEncoder()
    chains = E.load_split("chains", "dev")
    benign = [s for i in E.load_split("injections", "dev") if not i["malicious"] for s in S.sentences(i["text"])]
    pairs = build_pairs(chains, benign, seed)
    corpus_texts = [f["text"] for c in chains for f in c["fragments"]] + [c["secret"]["text"] for c in chains] + benign
    idf = build_idf(enc, corpus_texts)
    X, y, groups, kinds = featurize(enc, pairs, idf)
    mean, std = X.mean(0), X.std(0) + 1e-6
    Z = (X - mean) / std
    best = None
    for C in (0.1, 0.3, 1.0, 3.0):
        oof = np.zeros(len(y))
        for tr, te in GroupKFold(n_splits=3).split(Z, y, groups):
            oof[te] = LogisticRegression(C=C, max_iter=2000, class_weight="balanced").fit(Z[tr], y[tr]).predict_proba(Z[te])[:, 1]
        auc = roc_auc_score(y, oof)
        if best is None or auc > best[0]:
            best = (auc, C, oof)
    auc, C, oof = best
    thr = threshold_at_fpr(oof, y, FPR)
    by_kind = {k: round(float(np.mean(oof[[i for i, kk in enumerate(kinds) if kk == k]] >= thr)), 3) for k in sorted(set(kinds))}
    clf = LogisticRegression(C=C, max_iter=2000, class_weight="balanced").fit(Z, y)
    model = {"features": S.FEATURES, "mean": mean.tolist(), "std": std.tolist(), "coef": clf.coef_[0].tolist(),
             "intercept": float(clf.intercept_[0]), "threshold": round(thr, 4),
             "idf": {k: round(v, 3) for k, v in idf.items()}}
    report = {"train_pairs": len(y), "positives": int(y.sum()), "C": C, "cv_auc_grouped_by_event_type": round(float(auc), 4),
              "threshold": round(thr, 4), "cv_rate_above_threshold_by_kind": by_kind,
              "coef": dict(zip(S.FEATURES, np.round(clf.coef_[0], 3).tolist()))}
    return model, report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    model, report = run()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if a.write:
        S.MODEL_PATH.write_text(json.dumps(model), encoding="utf-8")
        S.MODEL_PATH.with_suffix(".meta.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("已写出", S.MODEL_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
