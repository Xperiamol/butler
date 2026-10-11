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
