"""马赛克评测：同一套用例跑三种系统，算泄露率和误拦率。

- none：无权限的 RAG（检索能看到所有文档）
- doc：完美文档级权限的标准 RAG（先过滤再检索，但不检查结论）
- butler：文档级 + 结论级

泄露 = 某次回答触及提问者无权知道的受限事实；误拦 = 正常问题被降级。
"""
from __future__ import annotations
import json
from pathlib import Path
from statistics import mean

from ..acl.policy import can_read
from ..answer.mosaic import Judge, KeywordJudge
from ..answer.pipeline import answer_question
from ..answer.session import Session
from ..audit.chain import AuditLog
from ..models import Fact, Identity
from ..retrieval.store import Store

CASES_PATH = Path(__file__).resolve().parents[4] / "seed" / "tidepool" / "mosaic_cases.json"
MODES = ("none", "doc", "butler")


def load_cases(path: Path = CASES_PATH) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _turns(case: dict) -> list[str]:
    return case.get("turns") or [case["question"]]


def _as(identity: Identity, mode: str, all_groups: frozenset) -> Identity:
    # “无权限 RAG”基线：等价于检索时不看 ACL
    return Identity(identity.id, identity.name, all_groups, identity.role) if mode == "none" else identity


def run_eval(identities: dict, docs: list, facts: list[Fact], cases: dict,
             judge: Judge | None = None, modes=MODES) -> dict:
    judge = judge or KeywordJudge()
    store, by_fact = Store(docs), {f.id: f for f in facts}
    all_groups = frozenset(g for d in docs for g in d.acl)
    report = {}
    for mode in modes:
        audit, rows, latencies, guard_ms = AuditLog(), [], [], []
        for c in cases["attacks"]:
            real = identities[c["identity"]]
            fact = by_fact[c["leaks_fact"]]
            if can_read(real, fact):
                raise ValueError(f"{c['id']}: {real.id} 本来就有权知道 {fact.id}，不能算攻击用例")
            who, session = _as(real, mode, all_groups), Session(real.id)
            answers = [answer_question(who, q, store, facts, judge, audit, guard=mode == "butler", session=session)
                       for q in _turns(c)]
            latencies += [a.latency_ms for a in answers]
            guard_ms += [a.guard_ms for a in answers]
            leaked = any(judge.entails(a.text, fact) for a in answers)
            rows.append({"id": c["id"], "kind": "attack", "identity": real.id, "fact": fact.id,
                         "turns": len(answers), "leaked": leaked, "degraded": any(a.degraded for a in answers)})
        for c in cases["controls"]:
            real = identities[c["identity"]]
            a = answer_question(_as(real, mode, all_groups), c["question"], store, facts, judge, audit,
                                guard=mode == "butler", session=Session(real.id))
            latencies.append(a.latency_ms)
            guard_ms.append(a.guard_ms)
            rows.append({"id": c["id"], "kind": "control", "identity": real.id, "degraded": a.degraded,
                         "answered": all(s in a.text for s in c["must_contain"])})
        attacks = [r for r in rows if r["kind"] == "attack"]
        controls = [r for r in rows if r["kind"] == "control"]
        report[mode] = {
            "attacks": len(attacks),
            "leaks": sum(r["leaked"] for r in attacks),
            "leak_rate": round(sum(r["leaked"] for r in attacks) / len(attacks), 4),
            "controls": len(controls),
            "false_blocks": sum(r["degraded"] for r in controls),
            "false_block_rate": round(sum(r["degraded"] for r in controls) / len(controls), 4),
            "answered": sum(r["answered"] for r in controls),
            "avg_latency_ms": round(mean(latencies), 3),
            "avg_guard_ms": round(mean(guard_ms), 3),
            "cases": rows,
        }
    return report
