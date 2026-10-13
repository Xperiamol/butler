"""语义判官：判断一段回答是否在"说出"某条受限结论，不依赖关键词。

做法：中文词向量（spaCy zh_core_web_lg，可选依赖）上的软对齐特征 + 训练出的逻辑回归（权重存 JSON）。
对回答逐句打分，取最高分。关键词判官的盲区（换了说法就漏）正是这里要补的。

特征（对一对 (回答句, 结论)）：均值向量余弦、结论→句子的软覆盖、句子→结论的软覆盖及其调和平均、
字面覆盖、否定不一致、推测/疑问语气、长度比、数字缺失、拉丁专名重叠。
依赖缺失时 `available()` 为 False，调用方应退回关键词判官。
"""
from __future__ import annotations
import json
import math
import re
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..models import Fact

MODEL_PATH = Path(__file__).parent / "models" / "semantic-judge-v1.json"
FEATURES = ["mean_cos", "cover_c2a", "cover_a2c", "cover_h", "lexical", "neg_mismatch", "hedge", "len_ratio",
            "num_missing", "latin_overlap", "cover_c2a_strict", "best_pair", "align50", "align70", "cover_w", "cover_w_strict", "sif_cos"]
_STOP = set("的了是在和与及也都就把被对从给让向而且或但并还又很更最这那其之以于有为将会能要可么吗呢吧啊着过")
_NEG = ("不", "没", "未", "无", "非", "别", "勿", "否")
_HEDGE = ("可能", "或许", "也许", "大概", "据说", "传闻", "如果", "假如", "是否", "有没有", "能否", "吗", "？", "?", "不确定", "尚未确定")
_SENT = re.compile(r"[。！？!?；;\n]+")


class ZhEncoder:
    """jieba 分词 + spaCy 词向量查表。懒加载；缺依赖时 available() 为 False。"""

    def __init__(self, model: str = "zh_core_web_lg"):
        self.model, self._nlp, self._cache = model, None, {}

    def available(self) -> bool:
        try:
            self._load()
            return True
        except Exception:   # noqa: BLE001 — 任何导入/加载失败都按"不可用"处理
            return False

    def _load(self):
        if self._nlp is None:
            import jieba   # noqa: F401
            import spacy
            self._nlp = spacy.load(self.model, exclude=["parser", "ner", "tagger", "attribute_ruler", "lemmatizer", "senter", "morphologizer"])
        return self._nlp

    def tokens(self, text: str) -> list[str]:
        import jieba
        out = []
        for t in jieba.cut(text):
            t = t.strip().lower()
            if not t or re.fullmatch(r"[\W_]+", t) or (len(t) == 1 and t in _STOP):
                continue
            out.append(t)
        return out

    def vector(self, token: str) -> np.ndarray | None:
        if token in self._cache:
            return self._cache[token]
        nlp = self._load()
        vocab = nlp.vocab
        v = None
        if token in vocab.strings and vocab.has_vector(token):
            v = vocab.get_vector(token)
        elif len(token) > 1:   # 词表外：用字向量平均兜底
            cs = [vocab.get_vector(c) for c in token if c in vocab.strings and vocab.has_vector(c)]
            if cs:
                v = np.mean(cs, axis=0)
        if v is not None:
            n = float(np.linalg.norm(v))
            v = v / n if n > 1e-6 else None
        self._cache[token] = v
        return v

    def embed(self, text: str) -> tuple[list[str], np.ndarray]:
        toks = [t for t in self.tokens(text) if self.vector(t) is not None]
        return toks, (np.stack([self.vector(t) for t in toks]) if toks else np.zeros((0, 300), dtype=np.float32))


_SHARED: dict[str, ZhEncoder] = {}


def shared_encoder() -> ZhEncoder:
    """进程内唯一的编码器：词向量模型加载约 7 秒，不能每次调用都重新加载。"""
    if "e" not in _SHARED:
        _SHARED["e"] = ZhEncoder()
    return _SHARED["e"]


def cjk_ratio(text: str) -> float:
    n = len(re.sub(r"\s", "", text))
    return len(re.findall(r"[\u4e00-\u9fff]", text)) / n if n else 0.0


def sentences(text: str, min_len: int = 6) -> list[str]:
    parts = [re.sub(r"^\s*-\s*\[[^\]]+\]\s*", "", p).strip() for p in _SENT.split(text)]   # 去掉 "- [doc-id]" 前缀
    return [p for p in parts if len(p) >= min_len]


def pair_features(enc: ZhEncoder, sent: str, concl: str, idf: dict | None = None) -> list[float]:
    st, sv = enc.embed(sent)
    ct, cv = enc.embed(concl)
    if not len(st) or not len(ct):
        return [0.0] * len(FEATURES)
    sm = cv @ sv.T                                  # 结论词 × 句子词 的余弦矩阵
    mean_cos = float(np.mean(sv, axis=0) @ np.mean(cv, axis=0) / (np.linalg.norm(np.mean(sv, axis=0)) * np.linalg.norm(np.mean(cv, axis=0)) + 1e-9))
    c2a = float(np.mean(sm.max(axis=1)))
    a2c = float(np.mean(sm.max(axis=0)))
    h = 2 * c2a * a2c / (c2a + a2c + 1e-9)
    strict = float(np.mean(sm.max(axis=1) > 0.6))   # 结论词里有多大比例在句子里能找到很近的词
    lex = len(set(ct) & set(st)) / len(set(ct))
    neg = abs(sum(sent.count(n) for n in _NEG) % 2 - sum(concl.count(n) for n in _NEG) % 2)
    hedge = float(any(w in sent for w in _HEDGE) and not any(w in concl for w in _HEDGE))
    ratio = min(len(sent), len(concl)) / max(len(sent), len(concl))
    nums = set(re.findall(r"\d+", concl))
    miss = len(nums - set(re.findall(r"\d+", sent))) / len(nums) if nums else 0.0
    lat_c = set(re.findall(r"[A-Za-z]{2,}", concl.lower()))
    lat = len(lat_c & set(re.findall(r"[A-Za-z]{2,}", sent.lower()))) / len(lat_c) if lat_c else 0.0
    row = sm.max(axis=1)
    # 按词的区分度加权（常见词权重小）：idf 来自训练文本；没见过的词按最大权重算
    top = max(idf.values()) if idf else 1.0
    w = np.array([idf.get(t, top) if idf else 1.0 for t in ct])
    w = w / (w.sum() + 1e-9)
    cover_w = float(w @ row)
    cover_w_strict = float(w @ (row > 0.6))
    ws = np.array([idf.get(t, top) if idf else 1.0 for t in st])
    sif = float((ws @ sv / (ws.sum() + 1e-9)) @ (w @ cv) / ((np.linalg.norm(ws @ sv / (ws.sum() + 1e-9)) * np.linalg.norm(w @ cv)) + 1e-9))
    return [mean_cos, c2a, a2c, h, lex, float(neg), hedge, ratio, miss, lat, strict, float(sm.max()),
            float(np.mean(row >= 0.5)), float(np.mean(row >= 0.7)), cover_w, cover_w_strict, sif]


class SemanticJudge:
    """Judge 接口：entails(answer, fact)。词向量不可用或模型文件缺失时构造会失败，用 `try_load()` 取得可选实例。"""

    def __init__(self, enc: ZhEncoder, mean, std, coef, intercept, threshold, idf=None):
        self.enc, self.mean, self.std, self.idf = enc, np.array(mean), np.array(std), idf or {}
        self.coef, self.intercept, self.threshold = np.array(coef), intercept, threshold
        self._concl: dict[str, tuple] = {}
        self.sources_norm: str | None = None   # 本次上下文资料原文（去空白）；绑定后，逐字摘自资料的句子不再打分

    def prob_pair(self, sent: str, concl: str) -> float:
        f = (np.array(pair_features(self.enc, sent, concl, self.idf)) - self.mean) / self.std
        return 1 / (1 + math.exp(-max(min(float(f @ self.coef + self.intercept), 30), -30)))

    def bind(self, context_texts: list[str]) -> "SemanticJudge":
        """绑定本次回答的上下文：逐字摘自用户有权读的资料的句子本身不可能构成结论级泄露，
        泄露来自模型"合成"出来的新句子，所以只给新句子打分。返回副本，不改共享实例。"""
        import copy
        b = copy.copy(self)
        b.sources_norm = re.sub(r"\s+", "", "\n".join(context_texts))
        return b

    def _novel(self, sents: list[str]) -> list[str]:
        if self.sources_norm is None:
            return sents
        return [s for s in sents if re.sub(r"\s+", "", s) not in self.sources_norm]

    def score(self, answer: str, fact: Fact) -> float:
        # 中文词向量对英文没有意义：结论是中文时只给中文为主的句子打分（英文资料原文不会被它误判）
        sents = sentences(answer)
        if cjk_ratio(fact.statement) >= 0.25:
            sents = self._novel([s for s in sents if cjk_ratio(s) >= 0.25 and len(s) <= 300])
        else:
            return 0.0
        return max((self.prob_pair(s, fact.statement) for s in sents), default=0.0)

    def entails(self, answer: str, fact: Fact) -> bool:
        return self.score(answer, fact) >= self.threshold

    def shortlist(self, answer: str, facts: list[Fact], k: int = 20) -> list[Fact]:
        """候选筛选用语义相似度（词面筛选看不到改述）：回答任一句与结论的均值余弦排前 k。"""
        sv = [np.mean(self.enc.embed(s)[1], axis=0) for s in self._novel([s for s in sentences(answer) if cjk_ratio(s) >= 0.25 and len(s) <= 300]) if len(self.enc.embed(s)[0])]
        if not sv:
            return []
        sv = [v / (np.linalg.norm(v) + 1e-9) for v in sv]
        scored = []
        for f in facts:
            if f.id not in self._concl:
                m = self.enc.embed(f.statement)[1]
                self._concl[f.id] = (np.mean(m, axis=0) / (np.linalg.norm(np.mean(m, axis=0)) + 1e-9)) if len(m) else None
            cv = self._concl[f.id]
            if cv is not None:
                scored.append((max(float(v @ cv) for v in sv), f))
        return [f for _, f in sorted(scored, key=lambda x: -x[0])[:k]]


def try_load(path: Path = MODEL_PATH, enc: ZhEncoder | None = None) -> SemanticJudge | None:
    enc = enc or shared_encoder()
    if not Path(path).exists() or not enc.available():
        return None
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return SemanticJudge(enc, d["mean"], d["std"], d["coef"], d["intercept"], d["threshold"], d.get("idf"))
