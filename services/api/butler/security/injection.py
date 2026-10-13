"""提示注入检测：高精度规则 + 训练出的线性分类器（字符 n-gram TF-IDF + 逻辑回归），长文本按窗口扫描。

分类器权重存成 JSON（`models/injection-v1.json.gz`），推理不依赖 sklearn、不使用 pickle。
训练与评估见 `train_injection.py`；指标写在 `models/injection-v1.meta.json`。
"""
from __future__ import annotations
import gzip
import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

MODEL_PATH = Path(__file__).parent / "models" / "injection-v1.json.gz"
WINDOW, STRIDE = 500, 250
_ZW = re.compile("[​-‏⁠﻿‪-‮]")
_LEET = str.maketrans("013457@$", "oieastas")
_SPACED = re.compile(r"\b(?:[a-z] ){3,}[a-z]\b")
_WORDS = re.compile(r"[a-z0-9]+|[一-鿿]+|[^\sa-z0-9一-鿿]")
_URL = re.compile(r"https?://|www\.", re.I)
_SPECIAL = re.compile(r"</?\w+>|<\||\|>|\[/?(INST|SYS|END)[^\]]*\]|#{3,}|^\s*(system|assistant|user)\s*:", re.I | re.M)

# 高精度规则：只收几乎不会出现在正常企业文档里的说法
RULES: dict[str, re.Pattern] = {
    "override": re.compile(r"\b(ignore|disregard|forget|override)\b[^.\n]{0,30}\b(previous|prior|above|earlier|all|any)\b[^.\n]{0,30}\b(instructions?|rules?|guidelines?|prompts?|directions?)\b", re.I),
    "override_zh": re.compile(r"(忽略|无视|忘记|无视掉)[^。\n]{0,10}(以上|之前|先前|上述|所有|全部)[^。\n]{0,6}(指令|规则|提示|设定|要求)"),
    "reveal_prompt": re.compile(r"\b(reveal|print|show|output|repeat|leak)\b[^.\n]{0,30}\b(system prompt|hidden instructions?|your instructions|your prompt)\b", re.I),
    "reveal_prompt_zh": re.compile(r"(输出|泄露|显示|打印|重复)[^。\n]{0,8}(系统提示|系统提示词|隐藏指令|你的指令)"),
    "role_hijack": re.compile(r"\b(you are now|from now on,? you (are|must|will)|act as if you have no|developer mode|DAN)\b[^.\n]{0,60}\b(no rules|without (any )?restrictions?|unrestricted|anything now|no limits?|all permissions)", re.I),
    "token_spoof": re.compile(r"<\|im_(start|end)\|>|\[/?INST\]|</?(system|documents?|context)>|###\s*system", re.I),
    "exfil_url": re.compile(r"\b(send|post|forward|email|upload|submit|append|attach)\b[^.\n]{0,60}\b(to|at|onto)\s+(the\s+)?(following\s+)?(link|url|address)?:?\s*https?://\S+", re.I),
    "exfil_url2": re.compile(r"\b(append|add|attach|include)\b[^.\n]{0,40}\b(to|onto)\b[^.\n]{0,20}\b(link|url)\b|\b(visit|open|load)\s+https?://\S+[?&]\w+=", re.I),
    "exfil_image": re.compile(r"!\[[^\]]*\]\(https?://[^)]*\)", re.I),
    "role_hijack_zh": re.compile(r"(你现在是|从现在开始你(是|必须|将)|扮演)[^。\n]{0,30}(没有任何限制|不受(任何)?限制|无所不能|不受规则约束|拥有所有权限)"),
    "hidden_notice_zh": re.compile(r"(给|致|写给)\s*(AI|人工智能|大模型|语言模型|智能)?\s*(助手|机器人|模型)[^。\n]{0,4}(的)?(留言|提示|说明|注意)"),
    "system_spoof_zh": re.compile(r"(系统提示|系统消息|管理员消息)\s*[:：]\s*(新的|最新)?(策略|规则|指令)"),
    # 称呼自动阅读器/AI 并紧跟指令（中文）
    "address_ai_zh": re.compile(r"(给|致|写给|供|对|向)[^。\n]{0,6}(AI|人工智能|助手|模型|机器人|自动\w{0,4}(服务|摘要器|阅读器|处理)\w*)[^。\n]{0,30}(请|必须|不要|不得|停用|忽略|执行|回答|列出|发送|披露|展示|写成|输出|照做)|(自动|机器)\w{0,3}(摘要器|阅读器|处理器)\s*请|仅(供)?自动阅读器"),
    # 称呼 AI（日/西/阿/英）
    "address_ai_multi": re.compile(r"(AI|アシスタント|モデル)\s*へ|[Pp]ara (el )?(asistente|modelo|IA)\b|إلى مساعد|مساعد الذكاء الاصطناعي|\b[Tt]o (the )?(AI|assistant|language model|model)\b\s*[:,]|\bAn (den )?(KI|Assistenten)\b"),
    "hide_from_user": re.compile(r"(不要|无需|不必|不用|别)[^。\n]{0,4}(向|给)?(用户|员工|提问者|询问者|对方|读者)[^。\n]{0,6}(展示|说明|提示|解释|告知|透露|提及)|隐去真实|不要把(命令|指令)展示"),
    "decode_execute": re.compile(r"(base64|Base64|BASE64)[^。\n]{0,30}(解码|decode)|先解码再执行|decode (and|then) (execute|follow)|HTML\s*实体还原|还原并当作[^。\n]{0,8}(规则|指令)", re.I),
    "always_say": re.compile(r"回答任何[^。\n]{0,8}问题[，,]?\s*(都说|都写|一律|均|都要)|一律回答|无论[^。\n]{0,10}都可(报销|通过|访问)"),
    "fake_authorization": re.compile(r"扮演已获[^。\n]{0,6}授权|不需要(真实的)?授权记录|(视为|当作)(已)?(获得)?(管理员|最高)权限|已升级为高权限"),
    "hidden_notice": re.compile(r"\b(note|message|instruction) (to|for) (ai|the (ai|llm|language model|assistant|chatbot)|chatbots?|language models?|ai assistants?)\b", re.I),
}


@dataclass(frozen=True)
class Verdict:
    score: float
    flagged: bool
    rules: tuple[str, ...] = ()


def normalize(text: str) -> tuple[str, int]:
    text = unicodedata.normalize("NFKC", text)
    zw = len(_ZW.findall(text))
    return re.sub(r"\s+", " ", _ZW.sub("", text).lower()), zw


def grams(text: str) -> Counter:
    """三个视图合并：原文、去 leet 写法、合并被空格拆开的字母；另加少量结构特征。"""
    norm, zw = normalize(text)
    views = {norm, norm.translate(_LEET), _SPACED.sub(lambda m: m.group(0).replace(" ", ""), norm)}
    c: Counter = Counter()
    for v in views:
        for w in _WORDS.findall(v):
            if w[0].isascii() and w[0].isalnum():
                p = f" {w} "
                for n in (2, 3, 4, 5):
                    for i in range(len(p) - n + 1):
                        c[p[i:i + n]] += 1
            elif "一" <= w[0] <= "鿿":
                for n in (1, 2, 3):
                    for i in range(len(w) - n + 1):
                        c["z:" + w[i:i + n]] += 1
            else:
                c["p:" + w] += 1
    if zw:
        c["§zw"] += 1
    if _URL.search(norm):
        c["§url"] += 1
    if _SPECIAL.search(text):
        c["§special"] += 1
    return c


_SENT = re.compile(r"(?<=[.!?。！？;；])\s+|\n+")
MAX_UNIT = 400


def windows(text: str) -> list[str]:
    """检测单元：每个句子，加上相邻两句的组合。按句子打分，载荷不会被前后大段正常文字稀释。"""
    parts = [p.strip() for p in _SENT.split(text) if p and p.strip()]
    merged: list[str] = []
    for p in parts:          # 过短的碎片并入下一句；过长的句子再按长度切开
        while len(p) > MAX_UNIT:
            merged.append(p[:MAX_UNIT])
            p = p[MAX_UNIT - 100:]
        if merged and len(merged[-1]) < 25:
            merged[-1] = merged[-1] + " " + p
        else:
            merged.append(p)
    out = list(merged) + [merged[i] + " " + merged[i + 1] for i in range(len(merged) - 1)]
    return out or [text]


class Model:
    def __init__(self, vocab: dict[str, int], idf: list[float], coef: list[float], intercept: float, threshold: float):
        self.vocab, self.idf, self.coef, self.intercept, self.threshold = vocab, idf, coef, intercept, threshold

    def prob(self, text: str) -> float:
        counts = grams(text)
        vec = {self.vocab[g]: (1 + math.log(tf)) * self.idf[self.vocab[g]] for g, tf in counts.items() if g in self.vocab}
        if not vec:
            return 0.0
        norm = math.sqrt(sum(v * v for v in vec.values()))
        z = self.intercept + sum(self.coef[i] * v / norm for i, v in vec.items())
        return 1 / (1 + math.exp(-max(min(z, 30), -30)))


@lru_cache(maxsize=1)
def load_model(path: Path = MODEL_PATH) -> Model | None:
    if not Path(path).exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as f:
        d = json.load(f)
    return Model({g: i for i, g in enumerate(d["terms"])}, d["idf"], d["coef"], d["intercept"], d["threshold"])


def rule_hits(text: str) -> tuple[str, ...]:
    norm = unicodedata.normalize("NFKC", _ZW.sub("", text))
    return tuple(name for name, rx in RULES.items() if rx.search(norm) or rx.search(norm.lower().translate(_LEET)))


def scan(text: str, model: Model | None = None, use_model: bool = True) -> Verdict:
    """级联：规则命中直接判定；否则对各窗口取分类器最高分。"""
    hits = rule_hits(text)
    if hits:
        return Verdict(1.0, True, hits)
    m = model or (load_model() if use_model else None)
    if m is None:
        return Verdict(0.0, False)
    score = max(m.prob(w) for w in windows(text))
    return Verdict(round(score, 4), score >= m.threshold)


def neutralize(text: str) -> str:
    """送进生成上下文前拆掉结构伪装：定界符、角色标记、零宽字符。不改变正常文本的含义。"""
    text = _ZW.sub("", text)
    text = re.sub(r"<\|[^|>]*\|>", " ", text)
    text = re.sub(r"</?(system|documents?|context|assistant|user)>", " ", text, flags=re.I)
    return re.sub(r"(?im)^\s*(system|assistant)\s*:", "[quoted] \\1:", text)
