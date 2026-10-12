"""资料入库的核心：手动导入和平台同步共用同一条路径（版本哈希、事实失效、ACL 继承、修订号）。"""
from __future__ import annotations
import hashlib

from . import database as D
from .ingest.index import remove_document


class KnowledgeError(ValueError):
    pass


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def upsert_documents(tx, documents: list[dict], facts: list[dict] = (), allow_empty_acl: bool = False) -> dict:
    """写入文档与受限事实。返回 {changed: [id], acl_changed: {id: (旧, 新)}, revision}。
    allow_empty_acl：同步时“权限展开不出任何本地组”要落成“无人可读”，而手动导入则要求必须填写。
    只读写涉及的行（按 id / source_doc 索引查），同步几千个文档不会变成全表扫描。"""
    new: dict[str, dict] = {}
    changed, acl_changed = set(), {}
    for incoming in documents:
        data = dict(incoming)
        data["acl"] = sorted({g.strip() for g in data["acl"] if g.strip()})
        if not data["acl"] and not allow_empty_acl:
            raise KnowledgeError("资料必须设置可读权限组。")
        data["content_hash"] = text_hash(data["text"])
        old = tx.get("document", data["id"])
        if old is None or (old.get("content_hash") or text_hash(old["text"])) != data["content_hash"]:
            changed.add(data["id"])
        if old is not None and sorted(old["acl"]) != data["acl"]:
            acl_changed[data["id"]] = (sorted(old["acl"]), data["acl"])
        if old is None or old != data:
            tx.put("document", data["id"], data)
        new[data["id"]] = data

    def doc(i):
        return new.get(i) or tx.get("document", i)

    supplied = {f["id"] for f in facts}
    for doc_id in changed:
        for fact in tx.query("fact", source_doc=doc_id):
            if fact["id"] not in supplied:
                tx.delete("fact", fact["id"])   # 正文已变：旧版本派生的事实整体失效
    for fact in facts:
        if doc(fact["source_doc"]) is None:
            raise KnowledgeError("受限事实必须关联已有资料。")
        if any(doc(p) is None for p in fact.get("premises", [])):
            raise KnowledgeError("前提资料必须是已有资料。")
        src = doc(fact["source_doc"])
        tx.put("fact", fact["id"], {**fact, "acl": src["acl"], "keywords": [], "content_hash": src["content_hash"]})
    for doc_id, data in new.items():   # 来源 ACL 变了，继承它的事实 ACL 一并更新
        for fact in tx.query("fact", source_doc=doc_id):
            if sorted(fact["acl"]) != data["acl"]:
                tx.put("fact", fact["id"], {**fact, "acl": data["acl"]})
    revision = tx.get("meta", "revision", {"value": 1})["value"]
    if changed or acl_changed:
        revision += 1
        tx.put("meta", "revision", {"value": revision})   # 修订号变化会让持有旧权限的会话失效
    return {"changed": sorted(changed), "acl_changed": acl_changed, "revision": revision}


def delete_document(tx, doc_id: str) -> bool:
    """删除文档及其派生数据：块、受限事实（以它为来源）。向量按内容哈希共享，留给维护任务回收。"""
    if tx.get("document", doc_id) is None:
        return False
    remove_document(tx, doc_id)
    for fact in tx.query("fact", source_doc=doc_id):
        tx.delete("fact", fact["id"])
    tx.put("meta", "revision", {"value": tx.get("meta", "revision", {"value": 1})["value"] + 1})
    return True


def refresh_auto_premises(tx) -> dict:
    """为没有人工登记前提的受限事实自动发现前提（管理侧离线计算，用全库词频）。
    人工登记的 premises 永远优先；自动发现不足两个资料时不启用（单个资料本身不构成"拼图"）。"""
    from .security import premises as P
    model = P.load_model()
    if model is None:
        return {"updated": 0}
    docs = tx.all("document")
    todo = [f for f in tx.all("fact") if not f.get("premises")]
    if not todo or not docs:
        return {"updated": 0}
    corpus = P.Corpus.build([(d["id"], d["title"] + "\n" + d["text"]) for d in docs])
    texts = {d["id"]: d["title"] + "\n" + d["text"] for d in docs}
    acls = {d["id"]: set(d["acl"]) for d in docs}
    updated = 0
    for f in todo:
        if f["source_doc"] not in acls:
            continue
        found = P.discover(corpus, texts, f["statement"], f["source_doc"], model,
                           eligible=P.eligible_premises(acls, f["source_doc"]))
        ids = [d for d, _ in found] if len(found) >= 2 else []
        if ids != f.get("auto_premises", []):
            tx.put("fact", f["id"], {**f, "auto_premises": ids, "auto_premise_probs": dict(found) if ids else {}})
            updated += 1
    return {"updated": updated}
