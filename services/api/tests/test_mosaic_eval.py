"""马赛克评测：对比 无防护 RAG vs 文档级完美权限 RAG vs Butler。
泄露率 = 攻击组中答案触及受限事实的比例；误拦率 = 对照组被降级的比例。"""
import json
from pathlib import Path

from butler.answer.mosaic import KeywordJudge
from butler.answer.pipeline import answer_question
from butler.audit.chain import AuditLog
from butler.connectors.fake import load_world
from butler.identity import registry
from butler.retrieval.store import Store

CASES = json.loads((Path(__file__).resolve().parents[3] / "seed/tidepool/mosaic_cases.json").read_text(encoding="utf-8"))
judge = KeywordJudge()


def run(guard: bool):
    ids, docs, facts = load_world()
    registry.load(ids)
    store, audit = Store(docs), AuditLog()
    by_id = {f.id: f for f in facts}
    leaks = sum(
        judge.entails(answer_question(registry.get(c["identity"]), c["question"], store, facts, judge, audit, guard).text,
                      by_id[c["leaks_fact"]])
        for c in CASES["attacks"] if not registry_can(c, by_id))
    blocked = sum(answer_question(registry.get(c["identity"]), c["question"], store, facts, judge, audit, guard).degraded
                  for c in CASES["controls"])
    return leaks, blocked


def registry_can(c, by_id):
    """若提问者本来就有权知道该事实，不计入攻击组。"""
    from butler.acl.policy import can_read
    return can_read(registry.get(c["identity"]), by_id[c["leaks_fact"]])


def test_document_level_only_leaks():
    leaks, _ = run(guard=False)
    assert leaks > 0  # 复现马赛克效应：每份引用都有权限，结论仍泄露


def test_butler_zero_leak_and_no_false_block():
    leaks, blocked = run(guard=True)
    assert leaks == 0
    assert blocked == 0


def test_controls_answer_content():
    ids, docs, facts = load_world()
    registry.load(ids)
    for c in CASES["controls"]:
        a = answer_question(registry.get(c["identity"]), c["question"], Store(docs), facts, judge, AuditLog())
        assert all(s in a.text for s in c["must_contain"])
