"""结构化切块：按标题、段落、列表、表格切，保留原文位置，重叠用句子而不是固定字符数。

- chunk.text 永远是原文 [start, end) 的子串，所以引用能定位到原文位置。
- 表格被切开时，表头放进 heading（元数据），不改正文。
- token 数是估算：中文一字约一个 token，英文一词约 1.3 个。
"""
from __future__ import annotations
import re
from dataclasses import dataclass

TARGET_TOKENS = 450
MAX_TOKENS = 600
OVERLAP_TOKENS = 60
MIN_SECTION_TOKENS = 60   # 小节变了且块已有这么长，就在小节边界收口

_CJK = re.compile(r"[一-鿿]")
_WORD = re.compile(r"[A-Za-z0-9]+")
_SENT = re.compile(r"(?<=[。！？!?；;])|(?<=[.])(?=\s)|\n")


@dataclass(frozen=True)
class Chunk:
    seq: int
    start: int
    end: int
    heading: str
    text: str
    tokens: int


def estimate_tokens(text: str) -> int:
    return len(_CJK.findall(text)) + int(len(_WORD.findall(text)) * 1.3 + 0.999)


@dataclass
class _Unit:
    start: int
    end: int
    heading: str
    tokens: int
    table_header: str = ""


def _units(text: str) -> list[_Unit]:
    """把文档切成不可再分的小单元（一个标题下的段落/列表项/表格行/句子），并记录所在标题路径。"""
    units: list[_Unit] = []
    path: list[tuple[int, str]] = []
    header = ""
    pos = 0
    for line in text.splitlines(keepends=True):
        start, end = pos, pos + len(line)
        pos = end
        stripped = line.strip()
        if not stripped:
            header = ""
            continue
        m = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if m:
            level = len(m.group(1))
            path = [p for p in path if p[0] < level] + [(level, m.group(2).strip())]
            header = ""
            continue
        heading = " > ".join(p[1] for p in path)
        if stripped.startswith("|"):
            if not header:
                header = stripped                                  # 表的第一行是表头
            elif re.match(r"^\|[\s:|-]+\|?$", stripped):
                continue                                           # 分隔行不单独成块
            units.append(_Unit(start, end, heading, estimate_tokens(line), table_header=header))
            continue
        if estimate_tokens(line) > MAX_TOKENS // 2:
            # 很长的一行：按句子再切
            s = start
            for part in _SENT.split(line):
                if not part:
                    continue
                e = s + len(part)
                if part.strip():
                    units.append(_Unit(s, e, heading, estimate_tokens(part)))
                s = e
            continue
        units.append(_Unit(start, end, heading, estimate_tokens(line)))
    return units


def split_document(text: str, target: int = TARGET_TOKENS, overlap: int = OVERLAP_TOKENS) -> list[Chunk]:
    units = _units(text)
    chunks: list[Chunk] = []
    i = 0
    while i < len(units):
        j, total = i, 0
        while j < len(units) and (total + units[j].tokens <= target or j == i):
            total += units[j].tokens
            j += 1
            # 标题变了且已经有一定长度：在语义边界收口，不把两个主题硬拼一块
            if j < len(units) and units[j].heading != units[j - 1].heading and total >= MIN_SECTION_TOKENS:
                break
        first, last = units[i], units[j - 1]
        body = text[first.start:last.end].strip("\n")
        start = first.start + (len(text[first.start:last.end]) - len(text[first.start:last.end].lstrip("\n")))
        heading = first.heading
        if first.table_header and not text[first.start:first.end].strip() == first.table_header:
            heading = (heading + " | " if heading else "") + first.table_header
        chunks.append(Chunk(len(chunks), start, start + len(body), heading, body, estimate_tokens(body)))
        if j >= len(units):
            break
        # 下一块从尾部若干单元回退，凑到约 overlap 个 token
        back, acc = j, 0
        while back - 1 > i and acc + units[back - 1].tokens <= overlap and units[back - 1].heading == units[j].heading:
            back -= 1
            acc += units[back].tokens
        i = back if back > i else j
    return chunks
