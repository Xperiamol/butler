from fastapi.testclient import TestClient

from butler.main import app

client = TestClient(app)


def test_ask_hides_guard_verdict():
    r = client.post("/ask", json={"identity_id": "ken", "question": "Payments 团队 Q4 预算为 0，供应商合同又暂停，这意味着什么？"}).json()
    assert "裁撤" not in r["text"] and "degraded" not in r and "blocked_facts" not in r
    assert r["data_source"] == "fake" and all({"id", "source", "title"} <= c.keys() for c in r["citations"])


def test_compare_shows_baseline_leak():
    r = client.post("/compare", json={"identity_id": "ken", "question": "Payments 团队 Q4 预算为 0，供应商合同又暂停，这意味着什么？"}).json()
    assert "裁撤" in r["baseline"]["text"] and r["butler"]["blocked_facts"] == ["f-reorg"]


def test_audit_requires_auditor_and_masks_docs():
    client.post("/ask", json={"identity_id": "pete", "question": "支付组是不是要被裁撤？"})
    assert client.get("/audit", params={"viewer_id": "ken"}).status_code == 403
    rows = client.get("/audit", params={"viewer_id": "amy", "user": "pete"}).json()["entries"]
    assert rows and all("drive-hr-1" not in r["payload"]["docs"] for r in rows)


def test_tamper_breaks_chain_then_reset():
    client.post("/ask", json={"identity_id": "alice", "question": "支付 API 限流是多少？"})
    assert client.get("/audit/verify").json()["ok"]
    assert client.post("/audit/tamper", json={"index": 0}).json()["first_bad_index"] == 0
    client.post("/demo/reset")
    assert client.get("/audit/verify").json() == {"ok": True, "first_bad_index": None, "length": 0}


def test_eval_endpoint():
    r = client.get("/eval").json()
    assert r["butler"]["leaks"] == 0 and r["doc"]["leaks"] > 0
