"""词典式跨语言检索（CLIR）：中文问题 → 英文文档。

做法（Pirkola 结构化查询）：中文问题分词，每个中文词用 CC-CEDICT 查出若干英文释义词，合成一个"概念"
（同一个中文词的所有英文候选互为同义）。文档命中某个概念 = 命中其中任一英文候选。
按概念的区分度加权后算覆盖率，既利用词典，又避免一个多义词把噪声带进来。
依赖 jieba 和 pycccedict（可选）；缺依赖时不产生任何概念，检索退回原样。
"""
from __future__ import annotations
import re
from functools import lru_cache

_EN_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "be", "is", "are", "one", "something", "someone",
            "somebody", "sb", "sth", "etc", "e.g", "i.e", "also", "used", "see", "variant", "old", "classifier", "abbr",
            "surname", "cl", "lit", "fig", "with", "from", "by", "at", "as", "it", "that", "this", "what", "how", "which", "who"}
_ZH_STOP = set("的了是在和与及也都就把被对从给让向而且或但并还又很更最这那其之以于有为将会能要可么吗呢吧啊着过我你他她它们该所")
_QUESTION = set("什么 怎么 怎样 如何 多少 哪个 哪些 谁 为什么 是否 能否 应该 可以 需要 一般 通常 最好 之前 之后 现在 已经 目前 还是 或者 如果".split())


@lru_cache(maxsize=1)
def _dict():
    try:
        import jieba   # noqa: F401
        from pycccedict.cccedict import CcCedict
        return CcCedict()
    except Exception:   # noqa: BLE001
        return None


def available() -> bool:
    return _dict() is not None


def _gloss_words(definition: str) -> list[str]:
    d = re.sub(r"\(.*?\)|\[.*?\]|CL:\S+|\bto\b", " ", definition)
    return [w for w in re.findall(r"[a-z]{3,}", d.lower()) if w not in _EN_STOP]


@lru_cache(maxsize=4096)
def concept(token: str) -> tuple[str, ...]:
    """一个中文词的英文候选（前 3 个释义里的实词，去掉套话）。"""
    cd = _dict()
    if cd is None:
        return ()
    try:
        defs = cd.get_definitions(token) or []
    except Exception:   # noqa: BLE001
        return ()
    out: list[str] = []
    for d in defs[:3]:
        for w in _gloss_words(d):
            if w not in out:
                out.append(w)
    return tuple(out[:8])


def concepts(query: str) -> list[tuple[str, tuple[str, ...]]]:
    """[(中文词, 英文候选)]；只保留有释义的实词。"""
    cd = _dict()
    if cd is None:
        return []
    import jieba
    out = []
    for t in jieba.cut(query):
        t = t.strip()
        if not t or not re.search(r"[一-鿿]", t) or t in _QUESTION or (len(t) == 1 and t in _ZH_STOP):
            continue
        c = concept(t)
        if not c and len(t) > 2:   # 长词查不到：拆成更短的词再查
            for sub in jieba.cut_for_search(t):
                if sub != t and len(sub) >= 2 and concept(sub):
                    out.append((sub, concept(sub)))
            continue
        if c:
            out.append((t, c))
    return out
