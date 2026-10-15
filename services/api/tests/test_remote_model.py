import pytest
import httpx
from butler.answer.remote import ModelFailure, RemoteJudge, RemoteModel
from butler.models import Fact


def test_provider_error_never_exposes_response_or_credentials(monkeypatch):
    def fail(*args, **kwargs):
        response = httpx.Response(401, text="provider secret response", request=httpx.Request("POST", "https://provider.example"))
        response.raise_for_status()
    monkeypatch.setattr(httpx, "post", fail)
    with pytest.raises(ModelFailure) as error:
        RemoteModel("https://provider.example", "private-key", "model").complete("private prompt", "secret fact")
    assert "secret" not in str(error.value) and "private" not in str(error.value)


@pytest.mark.parametrize("response", ['not json', '{"entails": "false"}', '{}', '[]'])
def test_malformed_security_verdict_fails_closed(response):
    class FakeModel:
        def complete(self, *args):
            return response
    with pytest.raises(ModelFailure):
        RemoteJudge(FakeModel()).entails("answer", Fact("id", "doc", frozenset(), "restricted"))


def reply(content, status=200, usage=None, text=None):
    def post(url, **kw):
        body = {"choices": [{"message": {"content": content}}], "usage": usage or {}}
        return httpx.Response(status, json=body if text is None else None, text=text, request=httpx.Request("POST", url))
    return post


def test_new_openai_models_get_max_completion_tokens_and_no_temperature(monkeypatch):
    seen = []

    def post(url, **kw):
        seen.append(dict(kw["json"]))
        b = kw["json"]
        if "max_tokens" in b:
            return httpx.Response(400, text='{"error":{"message":"Unsupported parameter: max_tokens. Use max_completion_tokens instead."}}', request=httpx.Request("POST", url))
        if "temperature" in b:
            return httpx.Response(400, text='{"error":{"message":"Unsupported value: temperature does not support 0"}}', request=httpx.Request("POST", url))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 7, "completion_tokens": 3}}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    m = RemoteModel("https://r.example/v1", "k", "gpt-x")
    assert m.complete("s", "c") == "ok"
    assert "max_completion_tokens" in seen[-1] and "max_tokens" not in seen[-1] and "temperature" not in seen[-1]
    assert m.stats["prompt_tokens"] == 7 and m.stats["calls"] == 1
    m.complete("s", "c")
    assert len(seen) == 4   # 第二次调用直接用已记住的参数，不再试错


def test_other_400_errors_are_not_retried_and_never_leak(monkeypatch):
    calls = []
    monkeypatch.setattr(httpx, "post", lambda url, **kw: (calls.append(1), httpx.Response(400, text="SECRET-BODY bad request", request=httpx.Request("POST", url)))[1])
    with pytest.raises(ModelFailure) as e:
        RemoteModel("https://r.example/v1", "k", "m").complete("s", "c")
    assert len(calls) == 1 and "SECRET" not in str(e.value)


def test_judge_accepts_json_wrapped_in_fences_or_prose():
    from butler.answer.remote import parse_json_object

    class M:
        def __init__(self, v): self.v = v
        def complete(self, *a): return self.v

    f = Fact("f1", "d", frozenset(), "restricted")
    assert RemoteJudge(M('```json\n{"f1": true}\n```')).entails_many("a", [f]) == [f]
    assert RemoteJudge(M('判定如下：{"f1": false}，以上。')).entails_many("a", [f]) == []
    assert parse_json_object('{"entails": true}') == {"entails": True}
    with pytest.raises(ValueError):
        parse_json_object("no json here")


def test_llm_env_prefers_generic_names_and_falls_back(monkeypatch):
    from butler.answer.remote import llm_env
    for k in ("LLM_API_KEY", "LLM_BASE_URL", "HUNYUAN_API_KEY", "HUNYUAN_BASE_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("HUNYUAN_API_KEY", "old")
    assert llm_env()[0] == "old" and llm_env()[1].startswith("https://api.hunyuan")
    monkeypatch.setenv("LLM_API_KEY", "new")
    monkeypatch.setenv("LLM_BASE_URL", "https://router.example/api/v1")
    assert llm_env() == ("new", "https://router.example/api/v1")
