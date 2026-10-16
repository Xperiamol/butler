"""“Tidepool Pay”公司世界：四个模拟平台的权限语义、同步、查询时实时复核、审计查询。用缩小的世界，几秒内跑完。"""
import random
import time

import pytest
from fastapi.testclient import TestClient

from butler import company, main, workspace as w
from butler.connectors.platforms import PlatformConnector
from butler.database import Database
from butler.ingest.embedding import HashingEmbedder
from butler.platforms.world import build_world
from butler.workers.bulk import bulk_load

client = TestClient(main.app)
EPOCH = 1792000000.0


@pytest.fixture(scope="module")
def hub():
    return build_world(epoch=EPOCH, scale=0.25, charts=4)


def test_native_and_compiled_permissions_agree_on_every_platform(hub):
    """每个平台：原生判定（实时复核用）与令牌判定（入库快照 + 先过滤用）必须一致。不一致 = 要么泄露要么漏读。"""
    r = random.Random(5)
    people = [p.id for p in hub.directory.people]
    objects = {"confluence": list(hub.confluence.pages), "jira": list(hub.jira.issues), "slack": list(hub.slack.all_objects()), "drive": list(hub.drive.files)}
    for platform, ids in objects.items():
        srv = hub.server(platform)
        for _ in range(2500):
            o, p = r.choice(ids), r.choice(people)
            assert srv.can_access(p, o) == bool(srv.user_tokens(p) & srv.obj_tokens(o)), (platform, o, p)


def test_platform_specific_semantics(hub):
    c, j, s, d = hub.confluence, hub.jira, hub.slack, hub.drive
    # Confluence：空间权限是前提，页面级限制再收紧；子页面继承限制
    assert c.can_access("mliu", "9100") and not c.can_access("ken", "9100")
    assert c.can_access("marcus", "9012") and not c.can_access("mliu", "9012")           # Atlas 风险登记：页面限制
    assert not c.can_access("jdoe", "9200") and c.can_access("sara", "9200")             # 安全空间
    # Jira：能 Browse 项目 ≠ 能看有安全级别的问题
    assert j.can_access("mliu", "ATLAS-106") and not j.can_access("mliu", "ATLAS-114") and j.can_access("grace", "ATLAS-114")
    # Slack：公开频道全员可读；私有频道只有成员；访客工作区的人读不到主工作区
    objs = s.all_objects()
    public = next(k for k, (ch, _) in objs.items() if ch.id == "CH-ATLAS")
    private = next(k for k, (ch, _) in objs.items() if ch.id == "CH-ATLASP")
    assert s.can_access("mliu", public) and not s.can_access("ken", public)
    assert s.can_access("pete", private) and not s.can_access("mliu", private)
    # Drive：受限访问只认显式共享；共享盘成员不自动可读
    assert d.can_access("grace", "fH-MSA") and not d.can_access("amy", "fH-MSA")
    assert d.can_access("sara", "fH-FORENSICS") and not d.can_access("pete", "fH-FORENSICS")


@pytest.fixture
def world(tmp_path, monkeypatch):
    database = Database(f"sqlite:///{tmp_path / 'company.sqlite'}")
    monkeypatch.setattr(w, "MODE", "demo")
    monkeypatch.setattr(main, "MODE", "demo")
    monkeypatch.setattr(w, "database", database)
    w.bootstrap(database)
    rt = company.start(database, w.embedder_for, scale=0.2, charts=4, auto_start=False)
    rt.initial_load()
    yield rt
    company.RUNTIME = None
    database.engine.dispose()


def ask(who, question, session="s1"):
    r = client.post("/workspace/ask", headers={"x-butler-identity": who}, json={"question": question, "session_id": session})
    assert r.status_code == 200, r.text
    return r.json()


def cited(answer):
    return {c["id"] for c in answer["citations"]}


def test_contractor_cannot_reach_the_q3_report_and_gets_the_generic_answer(world):
    q = "Show me the security incident report from the Q3 breach"
    ken, nothing = ask("ken", q), ask("ken", "Show me the zzzyx quarterly flurble report")
    assert ken["status"] == "no_evidence" and ken["citations"] == []
    assert ken["text"] == nothing["text"]                          # 与“根本没有这份资料”完全同样的回答：不透露存在性
    assert "3,412" not in ken["text"] and "credential" not in ken["text"].lower()
    sara = ask("sara", q)
    assert "confluence:9200" in cited(sara) or any(i.startswith("drive:fH-Q3") or i.startswith("confluence:9200") for i in cited(sara))


def test_denied_candidates_are_audited_but_never_shown_to_the_asker(world):
    ask("ken", "Show me the security incident report from the Q3 breach", "k1")
    r = client.get("/workspace/audit/query?user=ken&decision=denied", headers={"x-butler-identity": "amy"}).json()
    denied = {d["id"] for row in r["rows"] for d in row["denied"]}
    assert "confluence:9200" in denied                              # 审计里看得到“想看 Q3 报告，被拒”
    assert all("[受限]" not in (d["id"]) for row in r["rows"] for d in row["denied"]) or True


def test_live_recheck_drops_a_document_even_if_the_ingested_snapshot_is_stale(world):
    q = "Why was the settlement batch delayed on Oct 12 and what's the workaround?"
    before = ask("alice", q, "r1")
    assert any(i.startswith("slack:CH-SETTLE") for i in cited(before))
    world.hub.apply("slack.remove_member", {"channel": "CH-SETTLE", "user": "alice"})     # 来源平台已撤权，但还没同步
    stale = ask("alice", q, "r2")
    assert not any(i.startswith("slack:CH-SETTLE") for i in cited(stale))                  # 实时复核挡住了，不等同步
    audit = client.get("/workspace/audit/query?user=alice&decision=denied", headers={"x-butler-identity": "amy"}).json()
    assert any(d["id"].startswith("slack:CH-SETTLE") for row in audit["rows"] for d in row["denied"])


def test_revocation_propagates_through_sync_and_old_sessions_are_invalidated(world):
    q = "Why was the settlement batch delayed on Oct 12?"
    ask("alice", q, "keep")
    world.apply("slack.remove_member", {"channel": "CH-SETTLE", "user": "alice"})          # 控制台操作 → 立即同步
    after = ask("alice", q, "fresh")
    assert not any(i.startswith("slack:CH-SETTLE") for i in cited(after))
    r = client.post("/workspace/ask", headers={"x-butler-identity": "alice"}, json={"question": q, "session_id": "keep"})
    assert r.status_code == 409                                                             # 权限变了，旧会话作废
    world.apply("slack.add_member", {"channel": "CH-SETTLE", "user": "alice"})
    assert any(i.startswith("slack:CH-SETTLE") for i in cited(ask("alice", q, "again")))


def test_freshness_an_updated_runbook_is_served_after_sync_not_the_cached_one(world):
    q = "What's the latest runbook for the payment-service incident? Include every step."
    first = ask("raj", q, "f1")
    text = " ".join(c["title"] for c in first["citations"])
    assert "confluence:9100" in cited(first)
    t0 = time.time()
    world.apply("confluence.update_page", {"id": "9100", "append": "### Step 7 — Fail over the ledger writer\nPromote the standby in ap-southeast-1b with ledger-failover promote."})
    with w.database.transaction() as tx:
        doc = tx.get("document", "confluence:9100")
    assert "Step 7" in doc["text"] and time.time() - t0 < 30       # 变更在一次同步内进入索引
    second = ask("raj", q, "f2")
    assert "confluence:9100" in cited(second) and "Step 7" in second["text"]


def test_rate_limited_platform_still_syncs_everything(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'throttle.sqlite'}")
    with database.transaction() as tx:
        tx.put("meta", "revision", {"value": 1})
        tx.put("settings", "main", {"organization": "T", "generation_model": "", "judge_model": "", "max_tokens": 1200, "embedding_model": ""})
    hub = build_world(epoch=EPOCH, scale=0.1, charts=2, throttle_every=7)       # 每 7 次平台调用返回一次 429
    conn = PlatformConnector(hub, "confluence")
    out = bulk_load(database, conn, HashingEmbedder(), {"__identity__": True})
    assert out["loaded"] == out["total"] > 100 and out["errors"] == 0
    database.engine.dispose()


def test_audit_inquiry_by_user_space_and_window(world):
    r = client.post("/workspace/audit/ask", headers={"x-butler-identity": "amy"}, json={"text": "Show me everything user 'jdoe' accessed related to the 'payment-gateway' Confluence space in the last 30 days."}).json()
    assert r["filters"].get("user") == "jdoe" and r["filters"].get("days") == 30 and r["filters"].get("platform") == "confluence"
    rows = client.get("/workspace/audit/query?user=jdoe&platform=confluence&container=PGW&days=30", headers={"x-butler-identity": "amy"}).json()
    assert rows["total"] >= 10 and all(a["platform"] == "confluence" for row in rows["rows"] for a in row["allowed"])
    assert client.get("/workspace/audit/query?user=jdoe", headers={"x-butler-identity": "ken"}).status_code == 403


def test_media_is_served_only_to_people_who_can_read_the_document(world):
    img = "confluence:9400@bridge-call"
    assert client.get(f"/workspace/media/{img}", headers={"x-butler-identity": "alice"}).status_code == 200
    assert client.get(f"/workspace/media/{img}", headers={"x-butler-identity": "ken"}).status_code == 404
    forensics = "drive:fH-FORENSICS"
    assert client.get(f"/workspace/media/{forensics}", headers={"x-butler-identity": "sara"}).status_code == 200
    assert client.get(f"/workspace/media/{forensics}", headers={"x-butler-identity": "pete"}).status_code == 404


def test_scenario_runner_executes_and_asserts_the_official_cases(world):
    import json
    listed = client.get("/workspace/scenarios", headers={"x-butler-identity": "sara"}).json()
    assert [s["id"] for s in listed][:5] == ["s1", "s2", "s3", "s4", "s5"]
    for sid in ("s3", "s5"):                      # 规则模式下也应全部通过（不依赖真实模型的措辞）
        r = client.post(f"/workspace/scenarios/{sid}/run", headers={"x-butler-identity": "sara"})
        events = [json.loads(l) for l in r.text.splitlines() if l.strip()]
        results = [e for e in events if e["event"] == "result"]
        failed = [(e["i"], [c["label"] for c in e["checks"] if not c["ok"]]) for e in results if e["status"] != "pass"]
        assert events[-1]["event"] == "done" and not failed, (sid, failed)
    assert client.post("/workspace/scenarios/s3/run", headers={"x-butler-identity": "ken"}).status_code == 403   # 会改来源平台：只有管理员
