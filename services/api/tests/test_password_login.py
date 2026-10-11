import pytest
from fastapi.testclient import TestClient

from butler import main, workspace as w, passwords
from butler.database import Database

client = TestClient(main.app)
PASSWORD = "test-only password 12345"
NEW_PASSWORD = "replacement password 67890"
ADMIN = {"x-butler-identity": "sara"}


@pytest.fixture
def db(tmp_path, monkeypatch):
    database = Database(f"sqlite:///{tmp_path / 'local.sqlite'}")
    monkeypatch.setattr(w, "MODE", "demo")
    monkeypatch.setattr(main, "MODE", "demo")
    monkeypatch.setenv("BUTLER_AUTH_MODE", "local")
    monkeypatch.setattr(w, "database", database)
    w.bootstrap(database)
    yield database
    database.engine.dispose()


def create(username="alice.local"):
    return client.post("/workspace/members", headers=ADMIN, json={"username": username, "name": "测试员工", "password": PASSWORD})


def login(username="alice.local", password=PASSWORD):
    return client.post("/workspace/auth/password", json={"username": username, "password": password})


def test_creation_login_and_credentials_are_private(db):
    body = {"username": "alice.local", "name": "员工", "password": PASSWORD}
    assert client.post("/workspace/members", json=body).status_code == 401
    assert client.post("/workspace/members", headers={"x-butler-identity": "ken"}, json=body).status_code == 403
    member = create().json()
    assert member["role"] == "employee" and member["groups"] == []
    assert create("ALICE.LOCAL").status_code == 409
    assert login(" ALICE.LOCAL ").json()["id"] == member["id"]
    assert login(password="incorrect").status_code == 401
    with db.transaction() as tx:
        stored = tx.get("credential", "alice.local")
        assert stored["algorithm"] == "argon2id" and PASSWORD not in str(stored)
    for path in ("members", "audit"):
        response = client.get("/workspace/" + path, headers=ADMIN)
        assert PASSWORD not in response.text and stored["hash"] not in response.text


def test_failure_throttle_survives_database_reopen_and_unknowns_do_not_grow_rows(db, monkeypatch):
    create()
    for _ in range(5):
        assert login(password="incorrect").status_code == 401
    reopened = Database(str(db.engine.url))
    monkeypatch.setattr(w, "database", reopened)
    assert login().status_code == 429
    assert login("missing-user").status_code == 401
    with reopened.transaction() as tx:
        assert len(tx.all("login_limit")) == 2
        tx.put("login_limit", "account:alice.local", {"start": 0, "count": 5})
    assert login().status_code == 200
    reopened.engine.dispose()


def test_password_change_reset_and_disable_revoke_session_version(db):
    member = create().json()
    own = {"x-butler-identity": member["id"]}
    body = {"current_password": "incorrect", "password": NEW_PASSWORD}
    assert client.put("/workspace/account/password", headers=own, json=body).status_code == 400
    body["current_password"] = PASSWORD
    assert client.put("/workspace/account/password", headers=own, json=body).status_code == 200
    assert login().status_code == 401
    assert login(password=NEW_PASSWORD).json()["session_version"] == 2
    assert client.put(f"/workspace/members/{member['id']}/password", headers=own, json={"password": PASSWORD}).status_code == 403
    assert client.put(f"/workspace/members/{member['id']}/password", headers=ADMIN, json={"password": PASSWORD}).status_code == 200
    assert login().json()["session_version"] == 3
    for active in (False, True):
        assert client.put(f"/workspace/members/{member['id']}", headers=ADMIN, json={"role": "employee", "groups": [], "active": active}).status_code == 200
        if not active:
            assert login().status_code == 401
    assert login().json()["session_version"] == 5


def test_passwords_preserve_spaces_reject_short_and_use_distinct_salts(db):
    first, second = passwords.credential(PASSWORD), passwords.credential(PASSWORD)
    assert first["hash"] != second["hash"]
    spaced = "  my long pass phrase  "
    stored = passwords.credential(spaced)
    assert passwords.matches(spaced, stored) and not passwords.matches(spaced.strip(), stored)
    assert client.post("/workspace/members", headers=ADMIN, json={"username": "short-user", "name": "员工", "password": "short"}).status_code == 422
    assert create("invalid/username").status_code == 422


def test_bootstrap_is_one_time_and_oidc_disables_local(db, monkeypatch):
    monkeypatch.setenv("BUTLER_ADMIN_USERNAME", "owner")
    monkeypatch.setenv("BUTLER_ADMIN_PASSWORD", PASSWORD)
    passwords.bootstrap(db)
    owner = login("owner").json()
    assert owner["role"] == "admin" and owner["groups"] == []
    with db.transaction() as tx:
        tx.put("member", owner["id"], {**owner, "role": "employee", "active": False})
    monkeypatch.setenv("BUTLER_ADMIN_PASSWORD", NEW_PASSWORD)
    passwords.bootstrap(db)
    with db.transaction() as tx:
        assert not tx.get("member", owner["id"])["active"]
        assert passwords.matches(PASSWORD, tx.get("credential", "owner"))
    monkeypatch.setenv("BUTLER_AUTH_MODE", "oidc")
    assert login("owner").status_code == 403
    assert create().status_code == 403


def test_enterprise_password_login_still_requires_internal_token(db, monkeypatch):
    create()
    monkeypatch.setattr(main, "MODE", "enterprise")
    monkeypatch.setenv("BUTLER_INTERNAL_TOKEN", "internal-test-only-with-32-characters")
    assert login().status_code == 401
    response = client.post("/workspace/auth/password", headers={"authorization": "Bearer internal-test-only-with-32-characters"}, json={"username": "alice.local", "password": PASSWORD})
    assert response.status_code == 200


def test_fresh_enterprise_local_bootstrap_needs_no_oidc(tmp_path, monkeypatch):
    monkeypatch.setenv("BUTLER_AUTH_MODE", "local")
    monkeypatch.setenv("BUTLER_MODE", "enterprise")
    monkeypatch.setattr(w, "MODE", "enterprise")
    monkeypatch.delenv("BUTLER_ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("BUTLER_ADMIN_PASSWORD", raising=False)
    fresh = Database(f"sqlite:///{tmp_path / 'bootstrap.sqlite'}")
    w.bootstrap(fresh)
    with pytest.raises(RuntimeError, match="First local deployment"):
        passwords.bootstrap(fresh)
    monkeypatch.setenv("BUTLER_ADMIN_USERNAME", "owner")
    monkeypatch.setenv("BUTLER_ADMIN_PASSWORD", PASSWORD)
    passwords.bootstrap(fresh)
    with fresh.transaction() as tx:
        assert tx.all("document") == []
        assert len(tx.all("member")) == 1 and tx.all("member")[0]["role"] == "admin"
    monkeypatch.delenv("BUTLER_ADMIN_PASSWORD")
    passwords.bootstrap(fresh)  # Restarts no longer require the initialization secret.
    fresh.engine.dispose()
