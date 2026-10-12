from sqlalchemy import select

from butler import database as D
from butler.database import Database


def test_typed_tables_are_used_and_queryable(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'a.sqlite'}")
    with db.transaction() as tx:
        tx.put("conversation", "u1:a", {"id": "a", "owner": "u1", "updated": 1.0})
        tx.put("conversation", "u1:b", {"id": "b", "owner": "u1", "updated": 3.0})
        tx.put("conversation", "u2:a", {"id": "a", "owner": "u2", "updated": 2.0})
        tx.put("document", "d1", {"id": "d1", "source": "slack", "text": "x", "acl": ["a"], "content_hash": "h"})
        tx.put("settings", "main", {"v": 1})
        assert [c["id"] for c in tx.query("conversation", order_by="updated", descending=True, owner="u1")] == ["b", "a"]
        assert tx.count("conversation") == 3 and tx.count("settings") == 1
        assert tx.get("settings", "main") == {"v": 1}
        assert tx.connection.execute(select(D.records.c.kind).where(D.records.c.kind == "document")).first() is None
        assert tx.connection.execute(select(D.documents.c.source)).scalar_one() == "slack"


def test_legacy_rows_migrate_idempotently(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'b.sqlite'}")
    with db.engine.begin() as c:
        c.execute(D.records.insert().values(kind="member", id="m1", data={"id": "m1", "active": True}))
        c.execute(D.records.insert().values(kind="audit_entry", id="00000000000000000000", data={"payload": {}, "hash": "h"}))
    db2 = Database(str(db.engine.url))  # 重启即迁移
    Database(str(db.engine.url))
    with db2.transaction() as tx:
        assert tx.get("member", "m1")["active"] is True and tx.count("audit_entry") == 1
        assert tx.connection.execute(select(D.records.c.id).where(D.records.c.kind.in_(list(D.TYPED)))).first() is None


def test_iter_pages_through_large_tables(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'c.sqlite'}")
    with db.transaction() as tx:
        for i in range(25):
            tx.put("audit_entry", f"{i:020d}", {"i": i})
        assert [r["i"] for r in tx.iter("audit_entry", batch=7)] == list(range(25))
        assert [i for i, _ in tx.tail("audit_entry", 3)] == [f"{i:020d}" for i in (22, 23, 24)]
