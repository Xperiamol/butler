from butler.ingest.chunking import MAX_TOKENS, estimate_tokens, split_document


def test_chunk_text_is_exact_substring_with_positions():
    text = "# 报销\n\n差旅报销上限为 500 元。\n\n## 流程\n\n先提交申请，再由经理审批。\n" * 3
    chunks = split_document(text, target=40, overlap=10)
    assert len(chunks) > 1
    for c in chunks:
        assert text[c.start:c.end] == c.text


def test_long_document_is_split_by_budget_and_nothing_is_lost():
    para = "The travel policy states that employees must book through the portal. " * 6
    text = "\n\n".join(f"## Section {i}\n\n{para}" for i in range(12))
    chunks = split_document(text)
    assert len(chunks) > 3 and all(c.tokens <= MAX_TOKENS + 80 for c in chunks)
    covered = set()
    for c in chunks:
        covered |= set(range(c.start, c.end))
    heading_chars = {i for m in __import__("re").finditer(r"^#+ .*$", text, __import__("re").M) for i in range(m.start(), m.end())}
    assert all(i in covered or i in heading_chars or text[i].isspace() for i in range(len(text)))  # 标题进元数据，其余一字不丢


def test_overlap_repeats_trailing_units():
    text = "\n".join(f"Sentence number {i} about expenses." for i in range(60))
    chunks = split_document(text, target=50, overlap=20)
    assert chunks[1].start < chunks[0].end  # 相邻块有重叠


def test_heading_path_is_recorded_and_topics_not_merged_when_large():
    text = "# A\n\n## B\n\n" + ("alpha beta gamma delta. " * 20) + "\n\n## C\n\n" + ("epsilon zeta eta theta. " * 20)
    chunks = split_document(text, target=60, overlap=0)
    assert any(c.heading == "A > B" for c in chunks) and any(c.heading == "A > C" for c in chunks)
    assert not any("alpha" in c.text and "epsilon" in c.text for c in chunks)


def test_table_header_travels_in_heading_not_text():
    rows = "\n".join(f"| item{i} | {i * 10} |" for i in range(80))
    text = "# Prices\n\n| name | price |\n| --- | --- |\n" + rows
    chunks = split_document(text, target=60, overlap=0)
    assert len(chunks) > 1
    later = chunks[-1]
    assert "| name | price |" in later.heading and text[later.start:later.end] == later.text


def test_short_and_empty_documents():
    assert split_document("") == []
    one = split_document("只有一句话。")
    assert len(one) == 1 and one[0].text == "只有一句话。"
    assert estimate_tokens("中文四字") == 4
