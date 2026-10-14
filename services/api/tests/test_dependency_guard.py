"""依赖闭包防护：不看措辞，只看用户累计拿到的前提资料是否已能推出受限结论。"""
from butler.answer.mosaic import KeywordJudge
from butler.answer.pipeline import SAFE_REFUSAL, answer_question
from butler.answer.session import Session
from butler.audit.chain import AuditLog
from butler.models import Doc, Fact, Identity
from butler.retrieval.store import Store

STAFF = Identity("u", "U", frozenset({"staff"}), "employee")
EXEC = Identity("e", "E", frozenset({"exec"}), "exec")
A = Doc("a", "jira", "猎鹰项目预算", "猎鹰项目第四季度预算被冻结。", frozenset({"staff", "exec"}))
B = Doc("b", "slack", "奥比特尽调", "法务已与奥比特实验室签署保密协议。", frozenset({"staff", "exec"}))
S = Doc("s", "drive", "董事会纪要", "董事会批准收购奥比特实验室。", frozenset({"exec"}))
FILLER = [Doc(f"x{i}", "slack", t, t + "相关说明。", frozenset({"staff", "exec"})) for i, t in enumerate(["食堂菜单", "门禁规则", "年会安排", "入职流程"])]
# keywords 故意留空：判官永远不会触发，只有依赖闭包能拦住
FACT = Fact("f-acq", "s", frozenset({"exec"}), "公司将收购奥比特实验室", (), ("a", "b"))
DOCS = [A, B, S] + FILLER


def gen(q, ctx):
    return "\n".join(f"- [{d.id}] {d.text}" for d in ctx)


def run(who, questions):
    s, store = Session(who.id), Store(DOCS)
    return [answer_question(who, q, store, [FACT], KeywordJudge(), AuditLog(), session=s, generate=gen) for q in questions]


def test_second_fragment_is_refused_even_though_judge_sees_nothing():
    first, second = run(STAFF, ["猎鹰项目预算怎么样？", "奥比特尽调进展如何？"])
    assert first.status == "answered" and "a" in first.citations
    assert second.status == "refused" and second.text == SAFE_REFUSAL and second.blocked_facts == ["f-acq"]


def test_single_fragment_user_is_not_blocked():
    only_a = run(STAFF, ["猎鹰项目预算怎么样？", "食堂菜单是什么？"])
    assert [a.status for a in only_a] == ["answered", "answered"]


def test_authorized_user_may_know_the_conclusion():
    assert run(EXEC, ["猎鹰项目预算怎么样？", "奥比特尽调进展如何？"])[1].status == "answered"


def test_both_fragments_in_one_question_refused_before_generation():
    called = []
    store = Store(DOCS)
    a = answer_question(STAFF, "猎鹰项目预算和奥比特尽调进展分别怎么样？", store, [FACT], KeywordJudge(), AuditLog(),
                        generate=lambda q, ctx: called.append(1) or gen(q, ctx))
    assert a.status == "refused" and not called  # 不调用模型，省钱也不暴露
