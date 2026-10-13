"""用独立评测集的 dev 切分增强注入分类器，并做按条目分组的交叉验证。

    python -m butler.security.train_injection_dev --handbook <手册目录> [--write]

增强数据（全部来自 dev 切分，test 一条都不碰）：
- 负例：dev 拼图链里的中文业务文本（碎片、机密）和 dev 无害注入文本的全部句子
- 正例：dev 恶意文档里的**载荷句**。文档只有整体标签、不知道哪一句是载荷，所以用多实例学习：
  选当前模型分数最高的检测单元（没有明显高分时选指令线索最多的），其余单句当负例（正常上下文）
评估：对 dev 恶意/无害条目做 5 折分组交叉验证，每折不用被留出的条目训练；阈值定在留出无害条目误报 ≤ 5%。
"""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

import numpy as np

from ..redteam import eval_set as E
from ..redteam.benchmark import load_handbook
from . import injection as inj
from . import train_injection as T

FPR_ITEM = 0.05   # 无害条目误报率目标；阈值取留出无害条目分数的对应分位
CUES = re.compile(r"请|必须|不得|不要|忽略|无视|优先|助手|模型|读取|回答|列出|发送|输出|附上|链接|http|ignore|assistant|system")


def units(text):
    return [u for u in inj.windows(text) if len(u) > 8]


def pick_payload(text, model0):
    us = units(text)
    probs = [model0.prob(u) if model0 else 0.0 for u in us]
    hit = [i for i, u in enumerate(us) if inj.rule_hits(u)]
    if hit:
        return us[hit[0]]
    if probs and max(probs) >= 0.3:
        return us[int(np.argmax(probs))]
    return max(us, key=lambda u: len(CUES.findall(u))) if us else text


def extras(items, chains, model0):
    pos, neg = [], []
    for it in items:
        sents = [u for u in units(it["text"]) if "。" not in u[:-1] or len(u) < 80]
        if it["malicious"]:
            chosen = pick_payload(it["text"], model0)
            pos.append({"text": chosen, "label": 1, "family": "dev_pos"})
            neg += [{"text": u, "label": 0, "family": "dev_context"} for u in sents if u not in chosen and chosen not in u]
        else:
            neg += [{"text": u, "label": 0, "family": "dev_benign"} for u in units(it["text"])]
    for c in chains:
        for t in [f["text"] for f in c["fragments"]] + [c["secret"]["text"]]:
            neg += [{"text": u, "label": 0, "family": "dev_chain"} for u in units(t)]
    return pos, neg


def item_score(model, text):
    return max(model.prob(u) for u in inj.windows(text))


def run(handbook, seed=11, folds=5, write=False):
    docs = load_handbook(handbook)
    data = T.make_data(docs, seed)
    base = data["train"]["neg"] + data["train"]["hn"] + data["train"]["pos"]
    items = E.load_split("injections", "dev")
    chains = E.load_split("chains", "dev")
    model0 = inj.load_model()
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(items))
    fold_of = {items[i]["id"]: k % folds for k, i in enumerate(order)}
    oof = {}
    for f in range(folds):
        tr = [it for it in items if fold_of[it["id"]] != f]
        te = [it for it in items if fold_of[it["id"]] == f]
        pos, neg = extras(tr, chains, model0)
        clf, vocab, idf = T.fit(base + pos + neg)
        m = inj.Model(vocab, idf.tolist(), clf.coef_[0].tolist(), float(clf.intercept_[0]), 0.5)
        for it in te:
            oof[it["id"]] = (item_score(m, it["text"]), bool(inj.rule_hits(it["text"])))
    benign = np.array([oof[i["id"]][0] for i in items if not i["malicious"]])
    srt = np.sort(benign)
    roc = {}
    for target in (0.0, 0.05, 0.10):   # 无害条目允许的误报比例 → 对应阈值与该阈值下的恶意召回
        t = float(srt[min(int(np.ceil(len(srt) * (1 - target))), len(srt) - 1)] + (1e-6 if target == 0 else 0))
        roc[str(target)] = t
    thr = roc["0.05"]
    rep = {"folds": folds, "threshold": round(thr, 4), "per_technique": {}, "recall_at_benign_fpr": {}}
    for k, t in roc.items():
        rep["recall_at_benign_fpr"][k] = round(float(np.mean([(oof[i["id"]][0] >= t) or oof[i["id"]][1] for i in items if i["malicious"]])), 3)
    for tech in sorted({i["technique"] for i in items if i["malicious"]}):
        rows = [oof[i["id"]] for i in items if i["malicious"] and i["technique"] == tech]
        rep["per_technique"][tech] = {"n": len(rows), "model": round(float(np.mean([s >= thr for s, _ in rows])), 2),
                                      "rules": round(float(np.mean([r for _, r in rows])), 2),
                                      "cascade": round(float(np.mean([(s >= thr) or r for s, r in rows])), 2)}
    ben = [oof[i["id"]] for i in items if not i["malicious"]]
    rep["benign_fpr_cascade"] = round(float(np.mean([(s >= thr) or r for s, r in ben])), 3)
    rep["malicious_recall_cascade"] = round(float(np.mean([(oof[i["id"]][0] >= thr) or oof[i["id"]][1] for i in items if i["malicious"]])), 3)
    if write:
        pos, neg = extras(items, chains, model0)
        clf, vocab, idf = T.fit(base + pos + neg)
        T.export((clf, vocab, idf, thr), inj.MODEL_PATH)
        meta = json.loads(T.META_OUT.read_text()) if T.META_OUT.exists() else {}
        meta["dev_augmented"] = {"note": "加入 dev 切分的中文无害文本做负例、载荷句（多实例选取）做正例；测试集未使用", **rep}
        T.META_OUT.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--handbook", required=True, type=Path)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    print(json.dumps(run(a.handbook, write=a.write), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
