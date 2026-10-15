"""真实模型评测程序的流程测试：用确定性的假模型（按系统提示扮演生成/判官/评分），不联网。"""
import json

import httpx
import pytest

from butler.redteam import eval_llm as L
from butler.redteam import eval_set as E

pytestmark = pytest.mark.skipif(not (E.CORPUS / "acquisitions").exists(), reason="先运行 scripts/fetch_eval_handbook.py")
CHAINS = {c["id"]: c for c in E.load("chains")}


def fake_post(url, **kw):
    msgs = kw["json"]["messages"]
    system, content = msgs[0]["content"], json.loads(msgs[1]["content"])
    if system.startswith("你是企业知识助手"):
        docs = content["documents"]
        text = "\n".join(f"- [{d['id']}] {d['text']}" for d in docs)
        ids = {d["id"] for d in docs}
        for cid, c in CHAINS.items():
            if {f"f:{cid}:{i}" for i in range(len(c["fragments"]))} <= ids:
                text += "\n综合来看：" + c["conclusion"]
        out = text
    elif "每条指定的受限事实" in system:
        out = json.dumps({f["id"]: f["statement"] in content["answer"] for f in content["restricted_facts"]})
    elif "严格的评分员" in system:
        out = "```json\n" + json.dumps({"states": content["conclusion"] in content["answer"]}) + "\n```"
    else:
        raise AssertionError("unexpected prompt")
    return httpx.Response(200, json={"choices": [{"message": {"content": out}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
                          request=httpx.Request("POST", url))


def test_llm_harness_runs_and_the_guard_beats_no_guard(monkeypatch, tmp_path):
    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(L, "CACHE", tmp_path / "cache")
    monkeypatch.setenv("LLM_API_KEY", "test-key-not-real")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1")
    out = tmp_path / "r.json"
    # CachedModel 的默认缓存目录在类定义时已绑定，这里直接传目录
    monkeypatch.setattr(L.CachedModel, "__init__", (lambda orig: lambda self, *a, **kw: orig(self, *a, cache_dir=tmp_path / "cache", **kw))(L.CachedModel.__init__))
    assert L.main(["--model", "fake", "--split", "dev", "--limit", "10", "--workers", "2", "--out", str(out), "--price-in", "1", "--price-out", "2"]) == 0
    r = json.loads(out.read_text())
    assert r["chains"]["doc"]["leak"] > r["chains"]["butler"]["leak"] == 0
    assert r["chains"]["butler"]["authorized_user_blocked"] == 0
    assert r["usage"]["generator"]["calls"] > 0 and r["usage"]["generator"]["cost_estimate"] > 0
    # 第二次运行全部命中缓存：没有新的真实调用
    calls = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append(1) or fake_post(*a, **k))
    L.main(["--model", "fake", "--split", "dev", "--limit", "10", "--workers", "2"])
    assert not calls


def test_test_split_is_one_shot_per_model(monkeypatch, tmp_path):
    monkeypatch.setattr(E, "EVAL", tmp_path)
    monkeypatch.setattr(L.E, "EVAL", tmp_path)
    (tmp_path / "support").mkdir()
    (tmp_path / "support" / "test-runs-llm.json").write_text(json.dumps([{"model": "m1", "time": "t"}]))
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://llm.example/v1")
    with pytest.raises(SystemExit) as e:
        L.main(["--model", "m1", "--split", "test"])
    assert "跑过" in str(e.value)
