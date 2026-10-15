import subprocess
import time

import pytest
from sqlalchemy import select

from butler import database as D
from butler.connectors.gitrepo import GitError, GitRepoConnector
from butler.connectors.sync import Event
from butler.database import Database
from butler.ingest.embedding import EmbeddingFailure, HashingEmbedder
from butler.models import Identity
from butler.retrieval.hybrid import IndexCache, build_store
from butler.workers import queue, sync

PMAP = {"everyone": ["all"], "team:security": ["security"], "role:exec": ["exec"]}
RULES = [{"prefix": "security/", "principals": ["team:security", "role:exec"]}, {"prefix": "", "principals": ["everyone"]}]
ALL, SEC = Identity("a", "A", frozenset({"all"}), "employee"), Identity("s", "S", frozenset({"all", "security"}), "security")
EMB = HashingEmbedder()


def git(repo, *args):
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args], check=True, capture_output=True)


def commit(repo, files: dict, remove=(), msg="c"):
    for path, text in files.items():
        f = repo / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8")
    for path in remove:
        (repo / path).unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


@pytest.fixture
def env(tmp_path):
    repo = tmp_path / "origin"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    commit(repo, {"handbook/travel.md": "# Travel\n\nHotel stays are capped at 180 euros per night in Europe.\n",
                  "handbook/menu.md": "# Cafeteria\n\nThe cafeteria menu changes every Monday.\n",
                  "security/keys.md": "# Key rotation\n\nSigning keys rotate every ninety days at midnight.\n",
                  "image.png": "ignored"})
    db = Database(f"sqlite:///{tmp_path / 'w.sqlite'}")
    conn = GitRepoConnector("handbook", str(repo), "main", tmp_path / "work", RULES, allow_local=True)
    return repo, db, conn


def search(db, who, q, as_of=None):
    with db.transaction() as tx:
        store = build_store(tx, EMB, IndexCache())
        if as_of is not None:
            store.as_of = as_of
        return [d.id for d in store.search(who, q)]


def sync_all(db, conn, now=None, ttl=3600.0):
    sync.pull(db, conn, now)
    return sync.drain(db, conn, PMAP, EMB, ttl, now=(lambda: now) if now else time.time)


def test_initial_sync_expands_permissions_and_indexes(env):
    repo, db, conn = env
    out = sync_all(db, conn)
    assert out["done"] == 3                                    # png 被过滤
    assert search(db, ALL, "hotel cap in Europe") == ["handbook:handbook/travel.md"]
    assert search(db, ALL, "signing keys rotate") == []        # 普通员工看不到 security/
    assert search(db, SEC, "signing keys rotate") == ["handbook:security/keys.md"]
    with db.transaction() as tx:
        doc = tx.get("document", "handbook:security/keys.md")
        assert doc["acl"] == ["exec", "security"] and doc["sync"]["principals"] == ["role:exec", "team:security"]


def test_incremental_update_add_delete_and_duplicate_events(env):
    repo, db, conn = env
    sync_all(db, conn)
    assert sync.pull(db, conn) == 0                            # head 没变：没有新任务
    commit(repo, {"handbook/travel.md": "# Travel\n\nHotel stays are capped at 200 euros per night.\n",
                  "handbook/new.md": "# Parking\n\nVisitor parking permits are issued at reception.\n"}, remove=["handbook/menu.md"])
    out = sync_all(db, conn)
    assert out == {"done": 2, "deleted": 1}
    assert search(db, ALL, "hotel nightly cap") == ["handbook:handbook/travel.md"]
    with db.transaction() as tx:
        assert "200 euros" in tx.get("document", "handbook:handbook/travel.md")["text"]
        assert tx.get("document", "handbook:handbook/menu.md") is None
        assert tx.connection.execute(select(D.chunks).where(D.chunks.c.doc_id == "handbook:handbook/menu.md")).first() is None
    assert search(db, ALL, "cafeteria menu changes") == []
    assert search(db, ALL, "visitor parking permits") == ["handbook:handbook/new.md"]


def test_replayed_and_out_of_order_events_do_not_resurrect_or_regress(env):
    repo, db, conn = env
    sync_all(db, conn)
    with db.transaction() as tx:
        v_old = tx.get("meta", "sync_state:handbook:handbook/menu.md")["version"]
    commit(repo, {}, remove=["handbook/menu.md"])
    sync_all(db, conn)
    # 旧的 upsert 事件迟到（版本更小）：必须丢弃，不能让已删除的文档复活
    with db.transaction() as tx:
        queue.enqueue(tx, "handbook", "handbook/menu.md", "upsert", v_old, "late-replay")
    assert sync.drain(db, conn, PMAP, EMB) == {"stale": 1}
    with db.transaction() as tx:
        assert tx.get("document", "handbook:handbook/menu.md") is None
    # 同一事件重复入队 = 去重
    with db.transaction() as tx:
        assert queue.enqueue(tx, "handbook", "x.md", "upsert", 5, "k") is True
        assert queue.enqueue(tx, "handbook", "x.md", "upsert", 5, "k") is False


def test_unchanged_document_is_a_noop_and_keeps_revision(env):
    repo, db, conn = env
    sync_all(db, conn)
    with db.transaction() as tx:
        rev = tx.get("meta", "revision")["value"]
    commit(repo, {"README-unrelated.md": "# Other\n\nSomething else entirely.\n"})
    sync_all(db, conn)
    with db.transaction() as tx:
        assert tx.get("meta", "revision")["value"] == rev + 1   # 只有新增文档提升修订号
    out = sync.reconcile(db, conn, ttl=3600)
    assert out["queued"] == 0                                    # 对账：没有差异


def test_revocation_is_detected_by_reconcile_and_timestamps_are_recorded(env):
    repo, db, conn = env
    sync_all(db, conn)
    assert search(db, SEC, "signing keys rotate")
    conn.rules = sorted([{"prefix": "security/", "principals": ["role:exec"]}, {"prefix": "", "principals": ["everyone"]}],
                        key=lambda r: -len(r["prefix"]))          # 平台上把 security 组从该空间移除
    t0 = time.time()
    assert sync.reconcile(db, conn)["queued"] == 1
    sync.drain(db, conn, PMAP, EMB)
    assert search(db, SEC, "signing keys rotate") == []
    with db.transaction() as tx:
        ev = next(e["payload"] for e in tx.all("audit_entry") if e["payload"].get("event") == "sync.acl_changed")
        assert ev["removed"] == ["security"] and ev["doc"] == "handbook:security/keys.md"
        assert ev["source_changed_at"] <= ev["detected_at"] <= ev["effective_at"] and ev["effective_at"] >= t0


def test_permission_lookup_failure_retries_then_dead_letters_and_acl_expiry_denies(env):
    repo, db, conn = env
    t = 1_000_000.0
    sync_all(db, conn, now=t, ttl=100.0)
    assert search(db, ALL, "hotel cap in Europe", as_of=t + 1) == ["handbook:handbook/travel.md"]
    # 复核有效期过去后，即使什么都没发生，文档也不可读（权限接口一直失败的情形）
    with db.transaction() as tx:
        stale = build_store(tx, EMB, IndexCache())
        stale.as_of = t + 101.0
        assert stale.search(ALL, "hotel cap in Europe") == [] and stale.visible(ALL) == []
    original = conn.fetch_principals

    def broken(ext):
        raise RuntimeError("platform 503 SECRET-TOKEN")

    conn.fetch_principals = broken
    commit(repo, {"handbook/travel.md": "# Travel\n\nChanged text.\n"})
    sync.pull(db, conn, t + 1)
    clock = [t]
    statuses = []
    for _ in range(queue.MAX_ATTEMPTS):
        clock[0] += 10_000
        sync.run_once(db, conn, PMAP, EMB, 100.0, now=lambda: clock[0])
        with db.transaction() as tx:
            statuses.append(tx.connection.execute(select(D.sync_jobs.c.status).where(D.sync_jobs.c.external_id == "handbook/travel.md").order_by(D.sync_jobs.c.created.desc()).limit(1)).scalar_one())
    assert statuses[:-1] == ["retry"] * (queue.MAX_ATTEMPTS - 1) and statuses[-1] == "dead"
    with db.transaction() as tx:
        s = queue.stats(tx, clock[0])
        assert s["dead_letters"][0]["error"] == "RuntimeError" and "SECRET" not in str(s)   # 只记异常类型
    conn.fetch_principals = original


def test_unmapped_principals_mean_nobody_can_read(env):
    repo, db, conn = env
    conn.rules = [{"prefix": "", "principals": ["team:unknown"]}]
    sync.pull(db, conn)
    sync.drain(db, conn, PMAP, EMB)
    with db.transaction() as tx:
        assert tx.get("document", "handbook:handbook/travel.md")["acl"] == []
    assert search(db, ALL, "hotel cap in Europe") == [] and search(db, SEC, "hotel cap in Europe") == []


def test_crashed_worker_lease_expires_and_embedding_outage_does_not_fail_sync(env):
    repo, db, conn = env
    sync.pull(db, conn, 100.0)
    with db.transaction() as tx:
        assert len(queue.claim(tx, 100.0, limit=10, lease=60)) == 3      # worker 领走后崩溃
        assert queue.claim(tx, 120.0, limit=10) == []                    # 租约内不会被重复领取
        assert len(queue.claim(tx, 200.0, limit=10)) == 3                # 租约到期后被重新领取

    class Down:
        name, dim = "down", 4

        def embed(self, texts):
            raise EmbeddingFailure("down")

    with db.transaction() as tx:
        for j in queue.claim(tx, 10_000.0):
            queue.finish(tx, j["id"], "pending")
    out = sync.drain(db, conn, PMAP, Down())
    assert out["done"] == 3 and out["index_pending"] == 3
    assert search(db, ALL, "hotel cap in Europe") == ["handbook:handbook/travel.md"]     # 词法兜底


def test_connector_rejects_unsafe_locations_and_branches(tmp_path):
    with pytest.raises(GitError):
        GitRepoConnector("x", "file:///etc", "main", tmp_path, [])
    with pytest.raises(GitError):
        GitRepoConnector("x", "ssh://host/repo", "main", tmp_path, [])
    with pytest.raises(GitError):
        GitRepoConnector("x", "https://example.com/r.git", "--upload-pack=evil", tmp_path, [])


def test_grant_then_immediate_revoke_both_take_effect(env):
    """回归：对账任务的去重键曾经按“分钟”取整，同一分钟里先授权再撤销，撤销会被当成重复任务丢掉。"""
    repo, db, conn = env
    sync_all(db, conn)
    assert search(db, ALL, "hotel cap in Europe") == ["handbook:handbook/travel.md"]
    base = list(conn.rules)
    revoked = sorted([{"prefix": "handbook/travel.md", "principals": ["role:exec"]}] + base, key=lambda r: -len(r["prefix"]))
    conn.rules = list(revoked)
    assert sync.reconcile(db, conn)["queued"] == 1
    sync.drain(db, conn, PMAP, EMB)
    assert search(db, ALL, "hotel cap in Europe") == []                       # 撤权生效
    conn.rules = list(base)
    assert sync.reconcile(db, conn)["queued"] == 1                              # 马上再授权，同一秒内也不被当成重复
    sync.drain(db, conn, PMAP, EMB)
    assert search(db, ALL, "hotel cap in Europe") == ["handbook:handbook/travel.md"]
    conn.rules = list(revoked)
    assert sync.reconcile(db, conn)["queued"] == 1                              # 再撤销：状态和第一次相同，也不被丢掉
    sync.drain(db, conn, PMAP, EMB)
    assert search(db, ALL, "hotel cap in Europe") == []
