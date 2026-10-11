from fastapi import FastAPI, HTTPException

from .answer.mosaic import KeywordJudge
from .answer.pipeline import answer_question
from .audit.chain import AuditLog, verify
from .connectors.fake import DATA_SOURCE, load_world
from .identity import registry
from .retrieval.store import Store

app = FastAPI(title="Butler")
_identities, _docs, _facts = load_world()
registry.load(_identities)
store, audit, judge = Store(_docs), AuditLog(), KeywordJudge()


@app.get("/identities")
def identities():
    return [{"id": i.id, "name": i.name, "role": i.role} for i in registry.all_identities()]


@app.post("/ask")
def ask(identity_id: str, question: str, guard: bool = True):
    try:
        who = registry.get(identity_id)  # 身份由服务端绑定，模型不能指定 user_id
    except KeyError:
        raise HTTPException(404, "unknown identity")
    a = answer_question(who, question, store, _facts, judge, audit, guard)
    return {**a.__dict__, "data_source": DATA_SOURCE}


@app.get("/audit/verify")
def audit_verify():
    ok, bad = verify(audit.entries, audit.checkpoint())
    return {"ok": ok, "first_bad_index": bad, "length": len(audit.entries)}
