from butler.acl.policy import can_read
from butler.connectors.fake import load_world
from butler.identity import registry
from butler.models import Doc


def world():
    ids, docs, facts = load_world()
    registry.load(ids)
    return docs, facts


def test_empty_acl_denied():
    docs, _ = world()
    assert not can_read(registry.get("pete"), Doc("x", "slack", "t", "t", frozenset()))


def test_contractor_cannot_read_hr_doc():
    docs, _ = world()
    hr = next(d for d in docs if d.id == "drive-hr-1")
    assert not can_read(registry.get("ken"), hr)
    assert can_read(registry.get("pete"), hr)


def test_search_never_returns_unauthorized():
    from butler.retrieval.store import Store
    docs, _ = world()
    for ident in registry.all_identities():
        for d in Store(docs).search(ident, "裁撤 密钥 组织调整", k=20):
            assert can_read(ident, d)
