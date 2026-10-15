#!/usr/bin/env python3
"""Butler 终端演示（适合录屏）：四个场景，全部离线可跑；加 --llm 用真实模型生成（需要 LLM_API_KEY / LLM_BASE_URL）。

    python scripts/fetch_eval_handbook.py            # 先下载手册原文（一次）
    python scripts/demo.py                           # 约 1 分钟；--pace 1.2 放慢方便讲解；--scene 1..4 只演一个

1. 拼图攻击：同一个人连问三个无害问题，普通 RAG 把碎片拼成了机密结论，Butler 在第二步就拦下
2. 藏在资料里的指令：入库扫描命中并隔离，不进入任何人的检索结果
3. 撤权：在来源上撤掉权限，同步后同一个问题立刻问不出资料
4. 审计：独立工具验证签名链；有人改一条记录，验证立刻失败
"""
import argparse
import json
import subprocess
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))

from butler.answer.mosaic import AnchoredKeywordJudge, CombinedJudge   # noqa: E402
from butler.answer.pipeline import answer_question                      # noqa: E402
from butler.answer.session import Session                               # noqa: E402
from butler.audit.chain import AuditLog                                 # noqa: E402
from butler.audit.checkpoint import generate_keypair, sign_checkpoint   # noqa: E402
from butler.audit.verify_cli import check                               # noqa: E402
from butler.redteam import eval_set as E                                # noqa: E402
from butler.retrieval.eval import hybrid_store                          # noqa: E402

B, D, R, G, Y, C, X = "\033[1m", "\033[2m", "\033[31m", "\033[32m", "\033[33m", "\033[36m", "\033[0m"
PACE = 0.0


def say(text="", color="", pause=0.0):
    print(f"{color}{text}{X}")
    time.sleep(max(pause, 0) * PACE)


def title(n, text):
    print()
    say(f"━━ 场景 {n}  {text} " + "━" * max(2, 52 - len(text)), B + C, 1.0)


def show_answer(label, answer, leaked):
    status = {"answered": "已回答", "refused": "拒答", "degraded": "降级", "no_evidence": "无资料", "citation_failed": "引用不成立"}.get(answer.status, answer.status)
    flag = f"{R}✗ 泄露了结论{X}" if leaked else f"{G}✓ 没有泄露{X}"
    lines = [l for l in answer.text.splitlines() if l.strip() and (l.startswith("- [f:c01") or not l.startswith("- ["))]
    say(f"   {B}{label}{X} [{status}] {flag}", pause=0.4)
    for l in lines[-2:]:
        say(f"     {D}{l[:96]}{'…' if len(l) > 96 else ''}{X}")


def scene1(args):
    title(1, "拼图攻击：每个问题都合规，合起来是机密")
    chains = E.load("chains")[:9]          # 目标链 c01 + 另外 8 条链的资料做背景
    c = chains[0]
    c_docs, facts = E.chain_world(chains)
    store = hybrid_store(c_docs)[0]
    gen = E.PerfectInference(chains)
    if args.llm:
        from butler.answer.remote import llm_env
        from butler.redteam.eval_llm import CachedModel
        key, base = llm_env()
        gen = CachedModel(base, key, args.llm, 1500)
    say(f"受保护的结论：{c['conclusion']}", Y, 1.2)
    say("提问者：外包人员（只有普通权限，每份资料他单独都有权看）", D, 0.8)
    for system in ("普通 RAG（文档级权限）", "Butler"):
        say(f"\n  ▶ {system}", B, 0.6)
        guard = system == "Butler"
        judge = CombinedJudge(AnchoredKeywordJudge())
        sess, texts = Session("u"), []
        for i, q in enumerate(c["questions"], 1):
            say(f"   Q{i}  {q}", pause=0.6)
            a = answer_question(E.USER, q, replace(store, quarantine=guard), facts, judge, AuditLog(), guard=guard,
                                session=sess, generate=gen, injection=guard)
            texts.append(a.text)
            show_answer(f"A{i}", a, E.leaked("\n".join(texts), c))
        if guard:
            say("   原因：该结论登记了依赖资料，他累计拿到的资料已经凑齐，第二问之后就不再放行。", Y, 1.0)
    say("\n  结论级防护管的是“拼出来的东西”，不只是“能不能读这一份”。", B, 1.5)


def scene2(args):
    title(2, "藏在资料里的指令：入库扫描隔离")
    from butler.ingest.index import chunk_rows
    items = E.load("injections")
    bad = next(i for i in items if i["malicious"] and i["technique"] == "fake_system")
    ok = next(i for i in items if not i["malicious"])
    for label, it in (("一份被投毒的资料", bad), ("一份正常通知", ok)):
        rows = chunk_rows({"id": it["id"], "title": it["id"], "text": it["text"]})
        hit = any(r["risk"] >= 0.5 or r["flags"] for r in rows)
        say(f"\n  {label}：{D}{it['text'][:70].replace(chr(10), ' ')}…{X}", pause=0.8)
        say(f"    入库扫描 → {R + '命中，已隔离（不会被任何人检索到）' if hit else G + '通过，正常入库'}{X}", pause=1.0)
    say("\n  另外：回答里出现资料中没有的链接会被拒答，挡住把内容拼进网址外发。", Y, 1.5)


def scene3(args):
    title(3, "撤权：来源上改权限，同步后立刻生效")
    from butler.connectors.gitrepo import GitRepoConnector
    from butler.database import Database
    from butler.ingest.embedding import HashingEmbedder
    from butler.models import Identity
    from butler.retrieval.hybrid import IndexCache, build_store
    from butler.workers import sync
    tmp = Path(tempfile.mkdtemp())
    repo = tmp / "origin"
    (repo / "finance").mkdir(parents=True)
    git = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.email=d@d", "-c", "user.name=d", *a], check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    (repo / "finance" / "budget.md").write_text("# 预算说明\n\n第四季度研发预算为 380 万元，其中云资源 120 万元。\n", encoding="utf-8")
    git("add", "-A"), git("commit", "-q", "-m", "init")
    rules = [{"prefix": "", "principals": ["team:finance"]}]
    conn = GitRepoConnector("wiki", str(repo), "main", tmp / "work", rules, allow_local=True)
    pmap = {"team:finance": ["finance"], "team:eng": ["eng"]}
    db, emb = Database(f"sqlite:///{tmp / 'd.sqlite'}"), HashingEmbedder()
    sync.pull(db, conn)
    sync.drain(db, conn, pmap, emb)
    amy = Identity("amy", "Amy（财务）", frozenset({"finance"}), "employee")
    tom = Identity("tom", "Tom（研发）", frozenset({"eng"}), "employee")

    def ask(who):
        with db.transaction() as tx:
            return [d.id for d in build_store(tx, emb, IndexCache()).search(who, "第四季度研发预算是多少")]

    say("  来源规则：finance 目录只有 team:finance 可读", D, 0.8)
    say(f"  Amy（财务）问预算 → {G}{ask(amy) or '无'}{X}", pause=0.8)
    say(f"  Tom（研发）问预算 → {Y}{ask(tom) or '无资料，不作回答'}{X}", pause=1.0)
    say("\n  在来源系统里把 Tom 所在的 team:eng 加进可读名单……", Y, 1.0)
    conn.rules = [{"prefix": "", "principals": ["team:finance", "team:eng"]}]
    sync.reconcile(db, conn), sync.drain(db, conn, pmap, emb)
    say(f"  Tom 再问 → {G}{ask(tom)}{X}", pause=1.0)
    say("\n  现在撤销……", Y, 0.8)
    conn.rules = [{"prefix": "", "principals": ["team:finance"]}]
    t0 = time.perf_counter()
    sync.reconcile(db, conn)
    sync.drain(db, conn, pmap, emb)
    ms = (time.perf_counter() - t0) * 1000
    say(f"  Tom 再问 → {Y}{ask(tom) or '无资料，不作回答'}{X}   {D}（同步 + 生效耗时 {ms:.0f} ms）{X}", pause=1.0)
    with db.transaction() as tx:
        ev = [e["payload"] for e in tx.all("audit_entry") if e["payload"].get("event") == "sync.acl_changed"][-1]
    say(f"  审计记录：来源变更 → 检测 → 生效 三个时间点，{D}{json.dumps({k: ev[k] for k in ('removed', 'doc')}, ensure_ascii=False)}{X}", pause=1.5)


def scene4(args):
    title(4, "审计：不靠信任数据库，也能证明记录没被改")
    log = AuditLog()
    for i, ev in enumerate(("ask", "ask", "ask.refused", "sync.acl_changed")):
        log.append({"event": ev, "n": i, "ts": 1.0 + i})
    private, public = generate_keypair()
    cp = sign_checkpoint(private, len(log.entries), log.checkpoint(), ts=10.0)
    say(f"  导出 {len(log.entries)} 条记录 + 签名检查点（私钥只在服务端，公钥可公开）", D, 0.8)
    say(f"  独立验证 → {G}{'通过' if not check(log.entries, cp, public) else '失败'}{X}", pause=1.0)
    log.entries[1]["payload"]["event"] = "ask.refused"   # 有数据库写权限的人悄悄改一条
    say("\n  有人改了第 2 条记录……", Y, 0.8)
    problems = check(log.entries, cp, public)
    say(f"  独立验证 → {R}失败{X}：{problems[0]}", pause=1.0)
    say("  重算整条链也没用：没有私钥签不出新的检查点。", Y, 1.2)


def main():
    global PACE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scene", type=int, choices=(1, 2, 3, 4))
    ap.add_argument("--pace", type=float, default=0.0, help="每个停顿的秒数倍率，录屏时用 1.0~1.5")
    ap.add_argument("--llm", metavar="MODEL", help="场景 1 用真实模型生成（需要 LLM_API_KEY / LLM_BASE_URL）")
    a = ap.parse_args()
    PACE = a.pace
    say("Butler：连“结论”也管的企业 AI 助手", B)
    for n, fn in enumerate((scene1, scene2, scene3, scene4), 1):
        if not a.scene or a.scene == n:
            fn(a)
    print()


if __name__ == "__main__":
    main()
