import numpy as np
import pytest
from sqlalchemy import select

from butler import database as D
from butler.database import Database
from butler.ingest.embedding import HashingEmbedder
from butler.ingest.index import index_documents
from butler.models import Identity
from butler.retrieval.hybrid import IndexCache, build_store

EMB = HashingEmbedder()
STAFF = Identity("u", "U", frozenset({"staff"}), "employee")
HR = Identity("h", "H", frozenset({"staff", "hr"}), "hr")


def put(tx, i, title, text, acl=("staff",), source="upload"):
    tx.put("document", i, {"id": i, "source": source, "title": title, "text": text, "acl": list(acl)})


@pytest.fixture
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'h.sqlite'}")
    with d.transaction() as tx:
        put(tx, "travel", "Travel policy", "# Travel\n\nEmployees must book flights through the portal. Reimbursement of travel expenses "
            "requires receipts within 30 days.\n\n## Hotels\n\nHotel stays are capped at 180 euros per night in Europe.")
        put(tx, "menu", "Cafeteria", "The cafeteria menu changes every Monday and includes vegetarian options.")
        put(tx, "badge", "Badges", "Lost badges must be reported to security within one day.")
        put(tx, "secret", "Restructuring", "The payments team will be disbanded next quarter.", acl=("hr",))
        put(tx, "zh", "报销制度", "差旅报销上限为 500 元，需要在 30 天内提交申请并附发票。")
    index_documents(d, EMB)
    return d


def store(db, who_history=()):
    with db.transaction() as tx:
        return build_store(tx, EMB, IndexCache(), list(who_history))


def test_index_is_idempotent_and_reuses_vectors(db):
    again = index_documents(db, EMB)
    assert again.documents == 0 and again.skipped == 5
    with db.transaction() as tx:
        n_chunks = tx.connection.execute(select(D.chunks)).all()
        assert len(n_chunks) >= 5
        put(tx, "menu", "Cafeteria", "The cafeteria menu changes every Monday and includes vegetarian options. Soup on Fridays.")
    s = index_documents(db, EMB)
    assert s.documents == 1 and s.embedded >= 1
    with db.transaction() as tx:
        hashes = {r.content_hash for r in tx.connection.execute(select(D.chunks)) if r.doc_id == "menu"}
        assert len(hashes) == 1  # 旧版本的块已被换掉


def test_finds_passage_with_exact_positions(db):
    hit = store(db).search(STAFF, "hotel nightly cap in Europe")[0]
    assert hit.id == "travel" and "180 euros" in hit.text and hit.spans
    with db.transaction() as tx:
        full = tx.get("document", "travel")["text"]
    assert all(full[s:e] in hit.text for s, e in hit.spans)


def test_hybrid_survives_typos_and_chinese_and_refuses_offtopic(db):
    st = store(db)
    assert st.search(STAFF, "reimbursment of travle expenes")[0].id == "travel"
    assert st.search(STAFF, "差旅报销")[0].id == "zh"
    assert st.search(STAFF, "quantum chromodynamics lattice gauge") == []


def test_restricted_document_is_invisible_and_acl_change_needs_no_reindex(db):
    assert [d.id for d in store(db).search(STAFF, "payments team disbanded")] == []
    assert [d.id for d in store(db).search(HR, "payments team disbanded")] == ["secret"]
    with db.transaction() as tx:   # 撤权/授权：只改 ACL，不动正文
        d = tx.get("document", "secret")
        tx.put("document", "secret", {**d, "acl": ["staff"]})
    assert index_documents(db, EMB).documents == 0
    assert [d.id for d in store(db).search(STAFF, "payments team disbanded")] == ["secret"]


def test_unindexed_document_is_still_found_lexically(db):
    with db.transaction() as tx:
        put(tx, "fresh", "Parking", "Visitor parking permits are issued by reception on arrival.")
    assert [d.id for d in store(db).search(STAFF, "visitor parking permits")][:1] == ["fresh"]


def test_statistics_do_not_leak_restricted_terms(db):
    """受限文档的存在不能改变可见用户的打分：删掉它，可见用户的排序和结果必须完全一致。"""
    before = [d.id for d in store(db).search(STAFF, "travel expenses receipts hotel")]
    with db.transaction() as tx:
        from butler.ingest.index import remove_document
        remove_document(tx, "secret")
    assert [d.id for d in store(db).search(STAFF, "travel expenses receipts hotel")] == before


def test_session_history_text_loaded_only_for_requested_ids(db):
    st = store(db, ["travel"])
    assert [d.id for d in st.get_many(["travel", "menu"])] == ["travel"]
