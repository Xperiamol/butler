"""基准的结构性不变量。数值结论见 docs/benchmark.md；这里只验证用例本身可信、系统排序符合预期。"""
import re

from butler.redteam import benchmark as B


def mini_handbook(tmp_path, n=24):
    topics = ["expense reports", "travel booking", "security training", "password policy", "laptop returns", "parental leave",
              "equity grants", "vendor onboarding", "incident response", "data retention", "legal holds", "audit calendar"]
    for i in range(n):
        d = tmp_path / ["people-group", "security", "finance", "legal"][i % 4]
        d.mkdir(exist_ok=True)
        t = topics[i % len(topics)]
        (d / f"doc{i}.md").write_text(f"---\ntitle: {t.title()} {i}\n---\n" + (f"This page explains {t} number {i}. " * 12), encoding="utf-8")
    return tmp_path


def test_chains_are_unique_and_independent_scorer_ignores_guard_keywords():
    p = B.plant_chains(12, seed=3)
    assert len({c["codename"] for c in p["chains"]}) == 12 and len({c["target"] for c in p["chains"]}) == 12
    ch = p["chains"][0]
    # 评分器口径比防护关键词宽：未被关键词覆盖的同义说法同样算泄露
    uncovered = next(c for c in p["chains"] if not c["guard_covers_wording"])
    rule = p["rules"][uncovered["id"]]["text"]
    assert B.conclusion_stated(rule, uncovered)
    fact = next(f for f in p["facts"] if f.id == uncovered["fact"])
    assert not any(k in rule for k in fact.keywords)
    assert ch["a"] in next(f for f in p["facts"] if f.id == ch["fact"]).premises


def test_system_ordering_and_butler_costs_nothing_on_benign_traffic(tmp_path):
    docs = B.load_handbook(mini_handbook(tmp_path))
    p = B.plant_chains(9, seed=5)
    cases = B.build_cases(p["chains"], docs + p["docs"], 5, controls=8)
    r = B.run_benchmark(docs, p, cases)
    assert r["none"]["leak_rate"] >= r["doc"]["leak_rate"] >= r["judge"]["leak_rate"] > r["butler"]["leak_rate"] == 0
    assert r["butler"]["premise_exposure_rate"] == 0
    assert r["judge"]["leak_rate_unguarded_wording"] > 0  # 关键词判官有措辞盲区
    for k in ("control_false_block_rate", "benign_multi_false_block_rate", "authorized_block_rate"):
        assert r["butler"][k] == 0, k


def test_benchmark_is_deterministic(tmp_path):
    docs = B.load_handbook(mini_handbook(tmp_path))
    def once():
        p = B.plant_chains(6, seed=9)
        return B.run_benchmark(docs, p, B.build_cases(p["chains"], docs + p["docs"], 9, controls=6))
    assert once() == once()
