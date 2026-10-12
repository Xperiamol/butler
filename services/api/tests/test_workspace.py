import pytest
from fastapi.testclient import TestClient

from butler import main, workspace as w
from butler.database import Database

client = TestClient(main.app)


@pytest.fixture
def db(tmp_path, monkeypatch):
    database = Database(f"sqlite:///{tmp_path / 'workspace.sqlite'}")
    monkeypatch.setattr(w, "MODE", "demo")
    monkeypatch.setattr(main, "MODE", "demo")
    monkeypatch.setattr(w, "database", database)
    w.bootstrap(database)
    yield database
    database.engine.dispose()


def headers(who="sara"):
    return {"x-butler-identity": who}


def ask(who, session="test", question="支付 API 限流是多少？"):
    return client.post("/workspace/ask", headers=headers(who), json={"question": question, "session_id": session})


def test_configuration_access_and_persistence(db):
    assert client.get("/workspace/settings").status_code == 401
    assert client.get("/workspace/settings", headers=headers("ken")).status_code == 403
    value = {"organization": "测试工作区", "generation_model": "model-a", "judge_model": "model-b", "max_tokens": 800}
    assert client.put("/workspace/settings", headers=headers(), json=value).status_code == 200
    restarted = Database(str(db.engine.url))
    with restarted.transaction() as tx:
        assert tx.get("settings", "main") == value
        assert tx.all("audit_entry")[-1]["payload"]["event"] == "settings.updated"
    restarted.engine.dispose()
    assert client.get("/workspace/status", headers=headers("ken")).json()["audit_entries"] is None


def test_persistent_conversation_is_private_and_revocation_invalidates_history(db):
    r = ask("ken")
    assert r.status_code == 200 and "degraded" not in r.json()
    assert client.get("/workspace/conversations/test", headers=headers("ken")).json()["turns"]
    assert client.get("/workspace/conversations/test", headers=headers("alice")).status_code == 404
    changed = client.put("/workspace/members/ken", headers=headers(), json={"role": "contractor", "groups": [], "active": True})
    assert changed.status_code == 200
    assert client.get("/workspace/conversations/test", headers=headers("ken")).json() == {"id": "test", "turns": [], "stale": True}
    assert ask("ken").status_code == 409
    assert ask("ken", "new").json()["citations"] == []
    client.put("/workspace/members/ken", headers=headers(), json={"role": "contractor", "groups": [], "active": False})
    assert client.get("/workspace/me", headers=headers("ken")).status_code == 401


def test_import_is_atomic_and_fact_acl_tracks_source(db):
    body = {"documents": [{"id": "example", "source": "upload", "title": "测试资料", "text": "测试员工手册", "acl": ["eng"]}],
            "facts": [{"id": "restricted", "source_doc": "missing", "statement": "受限事实"}]}
    assert client.post("/workspace/knowledge/import", headers=headers(), json=body).status_code == 422
    with db.transaction() as tx:
        assert tx.get("document", "example") is None
    body["facts"][0]["source_doc"] = "example"
    assert client.post("/workspace/knowledge/import", headers=headers(), json=body).status_code == 200
    body["documents"][0]["acl"] = ["security"]
    body["facts"] = []
    client.post("/workspace/knowledge/import", headers=headers(), json=body)
    with db.transaction() as tx:
        assert tx.get("fact", "restricted")["acl"] == ["security"]
    assert "example" not in [d["id"] for d in client.get("/workspace/sources", headers=headers("alice")).json()["docs"]]


def test_cannot_remove_own_admin_or_spoof_identity(db):
    assert client.put("/workspace/members/sara", headers=headers(), json={"role": "employee", "groups": [], "active": True}).status_code == 409
    assert client.post("/workspace/ask", headers=headers("ken"), json={"question": "支付组是不是要被裁撤？", "session_id": "x", "identity_id": "pete"}).status_code == 422


def test_permission_revision_has_no_group_delimiter_collision(db):
    from butler.models import Identity
    with db.transaction() as tx:
        a = Identity("x", "x", frozenset({"a,b"}), "employee")
        b = Identity("x", "x", frozenset({"a", "b"}), "employee")
        assert w.revision(tx, a) != w.revision(tx, b)


def test_demo_database_cannot_be_reused_for_enterprise(db, monkeypatch):
    monkeypatch.setattr(w, "MODE", "enterprise")
    with pytest.raises(RuntimeError, match="separate databases"):
        w.bootstrap(db)


def test_workspace_audit_persists_and_detects_tampering(db):
    ask("ken")
    assert client.get("/workspace/audit", headers=headers("ken")).status_code == 403
    assert client.get("/workspace/audit/verify", headers=headers("amy")).json()["ok"]
    with db.transaction() as tx:
        entry = tx.all("audit_entry")[0]
        entry["payload"]["user"] = "changed"
        tx.put("audit_entry", "00000000000000000000", entry)
    assert client.get("/workspace/audit/verify", headers=headers("amy")).json()["first_bad_index"] == 0


def test_enterprise_generation_and_checking_are_separate_and_fail_closed(db, monkeypatch):
    import json
    import httpx
    monkeypatch.setattr(w, "MODE", "enterprise")
    monkeypatch.setenv("HUNYUAN_API_KEY", "test-only-not-a-real-key")
    with db.transaction() as tx:
        config = tx.get("settings", "main")
        tx.put("settings", "main", {**config, "generation_model": "generate", "judge_model": "check"})
    requests = []
    fail = False

    def complete(url, **options):
        body = options["json"]
        content = json.loads(body["messages"][1]["content"])
        requests.append((body["model"], content))
        if body["model"] == "generate":
            reply = f"支付组将被裁撤。[{content['documents'][0]['id']}]"
        else:
            reply = "not json" if fail else json.dumps({f["id"]: f["id"] == "f-reorg" and "裁撤" in content["answer"] for f in content["restricted_facts"]})
        return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", complete)
    response = ask("ken", "remote", "Payments 团队 Q4 预算为 0，供应商合同又暂停，这意味着什么？")
    assert response.status_code == 200 and "裁撤" not in response.json()["text"]
    assert [name for name, _ in requests] == ["generate", "check", "check"]  # 降级文本再检查一次
    assert "drive-hr-1" not in {d["id"] for d in requests[0][1]["documents"]}
    assert "f-reorg" in {f["id"] for f in requests[1][1]["restricted_facts"]}
    fail = True
    assert ask("ken", "failed", "Payments 团队 Q4 预算为 0，供应商合同又暂停，这意味着什么？").status_code == 503
    with db.transaction() as tx:
        assert tx.get("conversation", "ken:failed") is None


def test_enterprise_boundary_and_empty_workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(w, "MODE", "enterprise")
    monkeypatch.setattr(main, "MODE", "enterprise")
    monkeypatch.setenv("BUTLER_INTERNAL_TOKEN", "test-internal-token-32-characters-long")
    monkeypatch.setenv("BUTLER_OIDC_ISSUER", "https://identity.example")
    monkeypatch.setenv("BUTLER_AUTH_MODE", "oidc")
    monkeypatch.setenv("BUTLER_BOOTSTRAP_ADMIN_SUB", "owner-subject")
    fresh = Database(f"sqlite:///{tmp_path / 'enterprise-test.sqlite'}")
    monkeypatch.setattr(w, "database", fresh)
    w.bootstrap(fresh)
    with fresh.transaction() as tx:
        assert tx.all("member") == [] and tx.all("document") == [] and tx.all("fact") == []
    assert client.get("/identities").status_code == 404
    assert client.post("/compare", json={}).status_code == 404
    assert client.post("/workspace/provision", json={}).status_code == 401
    auth = {"authorization": "Bearer test-internal-token-32-characters-long"}
    body = {"issuer": "https://identity.example", "subject": "owner-subject", "name": "企业管理员"}
    admin = client.post("/workspace/provision", headers=auth, json=body).json()
    assert admin["role"] == "admin" and admin["groups"] == []
    body["subject"] = " owner-subject "
    whitespace_subject = client.post("/workspace/provision", headers=auth, json=body).json()
    assert whitespace_subject["role"] == "employee" and whitespace_subject["id"] != admin["id"]
    body["subject"] = "employee-subject"
    employee = client.post("/workspace/provision", headers=auth, json=body).json()
    assert employee["role"] == "employee" and employee["groups"] == []
    employee_headers = {**auth, "x-butler-identity": employee["id"]}
    assert client.get("/workspace/settings", headers=employee_headers).status_code == 403
    assert client.post("/workspace/ask", headers=employee_headers, json={"question": "你好", "session_id": "x"}).status_code == 503
    fresh.engine.dispose()


def test_fact_expires_when_source_text_changes(db):
    doc = {"id": "budget", "source": "upload", "title": "预算", "text": "正文预算 100 万", "acl": ["security"]}
    fact = {"id": "f-budget", "source_doc": "budget", "statement": "预算 100 万"}
    assert client.post("/workspace/knowledge/import", headers=headers(), json={"documents": [doc], "facts": [fact]}).status_code == 200
    # 只改 ACL、正文不变：事实保留
    assert client.post("/workspace/knowledge/import", headers=headers(), json={"documents": [{**doc, "acl": ["eng"]}], "facts": []}).status_code == 200
    with db.transaction() as tx:
        assert "f-budget" in [f.id for f in w.facts(tx)]
    # 正文改成 200 万且没有重新登记事实：旧的 100 万事实必须消失
    new = {**doc, "text": "正文预算 200 万"}
    assert client.post("/workspace/knowledge/import", headers=headers(), json={"documents": [new], "facts": []}).status_code == 200
    with db.transaction() as tx:
        assert tx.get("fact", "f-budget") is None and "f-budget" not in [f.id for f in w.facts(tx)]


def test_audit_export_requires_admin_and_signing_key(db, monkeypatch):
    from butler.audit.checkpoint import generate_keypair
    from butler.audit.verify_cli import check
    ask("ken")
    assert client.get("/workspace/audit/export", headers=headers("amy")).status_code == 403  # 范围受限的审计员拿不到原始链
    assert client.get("/workspace/audit/export", headers=headers()).status_code == 503  # 没配密钥就不签
    private, public = generate_keypair()
    monkeypatch.setenv("BUTLER_AUDIT_SIGNING_KEY", private.decode())
    out = client.get("/workspace/audit/export", headers=headers()).json()
    assert check(out["entries"], out["checkpoint"], public) == []
