"""引用核验：草稿里的每个 [资料编号] 必须真实存在于本次上下文，且被引用行里的数字要在被引资料里出现。

这只能证明“出处存在、数字有据”，不能证明整句论断被资料支持；论断级核验需要结构化输出（见 docs/implementation-audit.md）。
"""
from __future__ import annotations
import re

from ..models import Doc

CITE = re.compile(r"\[([A-Za-z0-9_.:/\-]+)\]")
NUMBER = re.compile(r"\d+(?:\.\d+)?")


def verify_citations(draft: str, context: list[Doc]) -> tuple[list[str], list[str]]:
    """返回 (有效引用 ID, 问题列表)；问题列表为空才算通过。"""
    by_id = {d.id: d for d in context}
    valid: list[str] = []
    problems: list[str] = []
    for line in draft.splitlines():
        ids = CITE.findall(line)
        for i in ids:
            if i not in by_id:
                problems.append(f"unknown:{i}")
            elif i not in valid:
                valid.append(i)
        known = [i for i in ids if i in by_id]
        if known:
            support = " ".join(by_id[i].title + " " + by_id[i].text for i in known)
            bare = CITE.sub("", line)
            for n in NUMBER.findall(bare):
                if n not in support:
                    problems.append(f"unsupported-number:{n}")
    if not valid and not problems:
        problems.append("no-citation")
    return valid, problems
