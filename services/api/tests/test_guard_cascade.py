from butler.answer.mosaic import FULL_SCAN_LIMIT, MAX_CANDIDATES, KeywordJudge, check, shortlist
from butler.answer.pipeline import SAFE_REFUSAL, answer_question
from butler.audit.chain import AuditLog
from butler.models import Doc, Fact, Identity
from butler.retrieval.store import Store

ME = Identity("u", "U", frozenset({"staff"}), "employee")


def facts(n):
    return [Fact(f"f{i}", "s", frozenset({"hr"}), f"项目{i:04d}代号蓝鲸{i:04d}将被终止", (f"终止蓝鲸{i:04d}",)) for i in range(n)]


class Counting(KeywordJudge):
    def __init__(self):
        self.seen = 0

    def entails_many(self, answer, fs):
        self.seen += len(fs)
        return [f for f in fs if self.entails(answer, f)]


def test_small_fact_sets_are_fully_scanned():
    j = Counting()
    check(ME, "无关内容", facts(FULL_SCAN_LIMIT), j)
    assert j.seen == FULL_SCAN_LIMIT


def test_large_fact_sets_are_shortlisted_without_losing_the_real_hit():
    fs = facts(2000)
    j = Counting()
    hits = check(ME, "团队计划终止蓝鲸0777的相关工作", fs, j)
    assert [f.id for f in hits] == ["f777"]
    assert j.seen < 200  # 不再把 2000 条全部送给判官


def test_unrelated_answer_skips_judge_entirely():
    j = Counting()
    assert check(ME, "食堂今天供应红烧肉", facts(2000), j) == [] and j.seen == 0


def test_over_budget_is_refused_not_silently_passed():
    fs = [Fact(f"g{i}", "s", frozenset({"hr"}), "支付组 团队 预算 合同 供应商 调整", ("调整",)) for i in range(MAX_CANDIDATES + 5)]
    doc = Doc("d", "slack", "预算", "支付组团队预算合同供应商调整说明。", frozenset({"staff"}))
    a = answer_question(ME, "支付组团队预算合同供应商调整", Store([doc]), fs, KeywordJudge(), AuditLog(),
                        generate=lambda q, ctx: "- [d] 支付组团队预算合同供应商调整说明。")
    assert a.status == "refused" and a.text == SAFE_REFUSAL


def test_shortlist_ranks_by_overlap():
    fs = facts(30)
    assert shortlist("终止蓝鲸0005", fs)[0].id == "f5"


def test_anchored_judge_ignores_keyword_in_unrelated_context_but_still_catches_the_leak():
    from butler.answer.mosaic import AnchoredKeywordJudge, anchors_of
    f = Fact("f", "s", frozenset({"hr"}), "The company will acquire Orbit Labs", ("acquire", "acquisition"))
    assert anchors_of(f) == ("Orbit", "Labs")
    j, plain = AnchoredKeywordJudge(), KeywordJudge()
    unrelated = "Our onboarding covers the acquisition of new skills and how to acquire access."
    leak = "Taken together, the company is preparing to acquire Orbit Labs."
    assert plain.entails(unrelated, f) and not j.entails(unrelated, f)       # 关键词判官误报，锚定后不再误报
    assert j.entails(leak, f)
    no_names = Fact("g", "s", frozenset({"hr"}), "layoffs next quarter", ("layoffs",))
    assert j.entails("layoffs are coming", no_names)                          # 没有专有名词时退回关键词行为


def test_combined_judge_batches_llm_judges_instead_of_one_call_per_fact():
    from butler.answer.mosaic import AnchoredKeywordJudge, CombinedJudge

    class Batch:
        calls = 0
        scan_limit = 100
        def entails_many(self, answer, facts):
            Batch.calls += 1
            return [f for f in facts if "秘密" in answer]
    facts = [Fact(f"f{i}", "s", frozenset({"hr"}), f"事实{i}", (f"独特词{i}",)) for i in range(40)]
    judge = CombinedJudge(AnchoredKeywordJudge(), Batch())
    assert len(check(ME, "这里提到了秘密", facts, judge)) == 40 and Batch.calls == 1
    assert judge.scan_limit >= 25
