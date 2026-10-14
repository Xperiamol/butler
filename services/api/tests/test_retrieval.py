from butler.models import Doc, Identity
from butler.retrieval.store import Store

ME = Identity("u", "U", frozenset({"staff"}), "employee")


def doc(i, title, text, acl=("staff",)):
    return Doc(i, "upload", title, text, frozenset(acl))


def test_short_question_on_single_document_library():
    store = Store([doc("m", "报销手册", "差旅报销上限为 500 元，需要在 30 天内提交。")])
    assert [d.id for d in store.search(ME, "报销")] == ["m"]  # 审计复现：原先固定阈值 4 返回 0 条


def test_unrelated_question_gets_nothing():
    store = Store([doc("m", "报销手册", "差旅报销上限为 500 元。"), doc("k", "食堂", "食堂午餐 11 点开始。"),
                   doc("p", "计划", "年会筹备计划已经确定。")])
    assert store.search(ME, "火星殖民计划") == []


def test_long_document_returns_relevant_passage_not_whole_text():
    filler = "办公室绿植由行政统一浇水养护，周末也有人负责。" * 30
    target = "海外差旅住宿标准：欧洲一线城市每晚上限 180 欧元。"
    store = Store([doc("long", "行政手册", filler + target + filler), doc("o", "门禁", "门禁卡丢失需要补办。")])
    hit = store.search(ME, "欧洲差旅住宿上限是多少")[0]
    assert hit.id == "long" and "180 欧元" in hit.text and len(hit.text) < 700


def test_invisible_document_never_scored():
    store = Store([doc("s", "机密", "裁撤支付组的计划", acl=("hr",)), doc("p", "公开", "食堂菜单")])
    assert store.search(ME, "裁撤支付组") == []
