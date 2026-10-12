import httpx
import numpy as np
import pytest

from butler.ingest.embedding import EmbeddingFailure, HashingEmbedder, RemoteEmbedder, from_bytes, to_bytes


def cos(a, b):
    return float(a @ b)


def test_hashing_embedder_is_deterministic_normalized_and_stateless():
    e = HashingEmbedder()
    a, b = e.embed(["travel expense policy"]), HashingEmbedder().embed(["travel expense policy"])
    assert np.array_equal(a, b) and abs(np.linalg.norm(a[0]) - 1) < 1e-5
    assert e.embed(["x"]).shape == (1, 512)


def test_related_text_scores_higher_than_unrelated_including_typos_and_chinese():
    e = HashingEmbedder()
    q, rel, other = e.embed(["travel expenses reimbursement", "Employees submit travel expense reports for reimbursement.",
                             "The cafeteria menu changes every Monday."])
    assert cos(q, rel) > cos(q, other) + 0.15
    typo, = e.embed(["reimbursment of travle expenes"])
    assert cos(typo, rel) > cos(typo, other)
    zq, zr, zo = e.embed(["差旅报销上限", "差旅费用报销上限为五百元", "食堂每周一更新菜单"])
    assert cos(zq, zr) > cos(zq, zo) + 0.15


def test_vector_bytes_roundtrip_and_dimension_check():
    v = HashingEmbedder(64).embed(["abc def"])[0]
    assert np.array_equal(from_bytes(to_bytes(v), 64), v)
    with pytest.raises(ValueError):
        from_bytes(to_bytes(v), 32)


def reply(vectors, status=200):
    def post(url, **kw):
        n = len(kw["json"]["input"])
        data = [{"index": i, "embedding": vectors[i % len(vectors)]} for i in reversed(range(n))]  # 故意乱序
        return httpx.Response(status, json={"data": data}, request=httpx.Request("POST", url))
    return post


def test_remote_embedder_batches_orders_and_normalizes(monkeypatch):
    calls = []
    inner = reply([[3.0, 4.0], [0.0, 2.0]])
    monkeypatch.setattr(httpx, "post", lambda url, **kw: (calls.append(len(kw["json"]["input"])), inner(url, **kw))[1])
    out = RemoteEmbedder("https://x/v1", "k", "m", batch=2).embed(["a", "b", "c"])
    assert calls == [2, 1] and out.shape == (3, 2)
    assert np.allclose(out[0], [0.6, 0.8]) and np.allclose(out[1], [0.0, 1.0])  # 乱序返回按 index 还原


def test_remote_embedder_retries_then_fails_without_leaking_provider_text(monkeypatch):
    n = {"c": 0}

    def flaky(url, **kw):
        n["c"] += 1
        if n["c"] < 3:
            return httpx.Response(429, json={"error": "SECRET-PROVIDER-TEXT"}, request=httpx.Request("POST", url))
        return reply([[1.0, 0.0]])(url, **kw)

    monkeypatch.setattr(httpx, "post", flaky)
    slept = []
    assert RemoteEmbedder("https://x/v1", "k", "m", sleep=slept.append).embed(["a"]).shape == (1, 2) and slept == [1, 2]
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Response(500, json={"error": "SECRET"}, request=httpx.Request("POST", url)))
    with pytest.raises(EmbeddingFailure) as err:
        RemoteEmbedder("https://x/v1", "k", "m", retries=1, sleep=lambda s: None).embed(["a"])
    assert "SECRET" not in str(err.value)


def test_client_errors_are_not_retried_and_dimension_mismatch_fails(monkeypatch):
    calls = []
    monkeypatch.setattr(httpx, "post", lambda url, **kw: (calls.append(1), httpx.Response(401, request=httpx.Request("POST", url)))[1])
    with pytest.raises(EmbeddingFailure):
        RemoteEmbedder("https://x/v1", "k", "m", sleep=lambda s: None).embed(["a"])
    assert len(calls) == 1
    monkeypatch.setattr(httpx, "post", reply([[1.0, 0.0]]))
    with pytest.raises(EmbeddingFailure):
        RemoteEmbedder("https://x/v1", "k", "m", dim=3).embed(["a"])
