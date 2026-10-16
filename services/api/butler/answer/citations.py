"""引用核验：草稿里的每个 [资料编号] 必须真实存在于本次上下文，且被引用行里的数字要在被引资料里出现。

这只能证明“出处存在、数字有据”，不能证明整句论断被资料支持；论断级核验需要结构化输出（见 docs/implementation-audit.md）。
"""
from __future__ import annotations
import re

from ..models import Doc

CITE = re.compile(r"\[([A-Za-z0-9_.:/\-]+)\]")
NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?")   # Q4、H2 这类带字母前缀的标识不是数值论断


URL = re.compile(r"https?://[^\s)\]>\"']+", re.I)


def verify_citations(draft: str, context: list[Doc], urls: bool = True) -> tuple[list[str], list[str]]:
    """返回 (有效引用 ID, 问题列表)；问题列表为空才算通过。"""
    by_id = {d.id: d for d in context}
    # 资料原文里本来就有的方括号词（[TOC]、[warning]、链接引用名）是正文，不是引用；编造的编号不会出现在资料里
    literal = {t for d in context for t in CITE.findall(d.title + " " + d.text)}
    valid: list[str] = []
    problems: list[str] = []
    for line in draft.splitlines():
        ids = CITE.findall(line)
        for i in ids:
            if i not in by_id:
                if i not in literal:
                    problems.append(f"unknown:{i}")
            elif i not in valid:
                valid.append(i)
        known = [i for i in ids if i in by_id]
        if known:
            support = " ".join(by_id[i].title + " " + by_id[i].text for i in known)
            bare = re.sub(r"^\s*(?:[-*•]|#{1,4}|\d+[.)、])\s*", "", CITE.sub("", line))   # 行首的列表序号、标题符号不算论断里的数字
            for n in NUMBER.findall(bare):
                if n not in support:
                    problems.append(f"unsupported-number:{n}")
    if urls:
        # 输出里的链接必须出现在被引资料里：挡住“把内容拼进链接/图片地址外发”这类注入外泄
        support = " ".join(d.text for d in context)
        problems += [f"unlisted-url:{u[:40]}" for u in URL.findall(draft) if u not in support]
    if not valid and not problems:
        problems.append("no-citation")
    return valid, problems
