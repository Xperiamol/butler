"""向量化。统一接口，离线默认用无需拟合的哈希 n-gram 嵌入，接入真实服务时换 RemoteEmbedder。

为什么默认不用 LSA/TF-IDF+SVD 这类需要在语料上拟合的嵌入：拟合用到了全部文档（包括提问者无权读的），
词频统计会把受限文档的信息带进每个人的检索基底。哈希嵌入没有任何语料统计量，权限边界不会因此变模糊。
它的能力是子词/字符级的模糊匹配（拼写、词形、中文部分重叠），不是真正的同义语义；语义召回要靠 RemoteEmbedder。
"""
from __future__ import annotations
import math
import re
import time
import zlib
from typing import Protocol

import httpx
import numpy as np

_TOKEN = re.compile(r"[a-z0-9]+|[一-鿿]+")
_EN_STOP = {"the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "and", "or", "in", "on", "for", "with", "at",
            "by", "from", "as", "it", "this", "that", "what", "which", "who", "how", "do", "does", "me", "my", "about",
            "tell", "can", "i", "we", "our", "your", "you", "please", "there", "any", "has", "have"}


class EmbeddingFailure(Exception):
    pass


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> np.ndarray: ...


def _h(feature: str) -> int:
    return zlib.crc32(feature.encode("utf-8"))


class HashingEmbedder:
    """签名哈希的词/子词/中文 n-gram 袋，亚线性词频，L2 归一化。无状态、确定、与语料无关。"""

    def __init__(self, dim: int = 512):
        self.dim, self.name = dim, f"hash-{dim}-v1"

    def features(self, text: str) -> dict[str, float]:
        feats: dict[str, float] = {}

        def add(f: str, w: float = 1.0):
            feats[f] = feats.get(f, 0.0) + w

        prev = ""
        for tok in _TOKEN.findall(text.lower()):
            if tok[0] >= "一":
                for i, ch in enumerate(tok):
                    add("c:" + ch, 0.5)
                    if i + 1 < len(tok):
                        add("b:" + tok[i:i + 2], 1.0)
                prev = ""
                continue
            if tok in _EN_STOP or len(tok) < 2:
                prev = ""
                continue
            add("w:" + tok, 1.0)
            if len(tok) >= 4:  # 词内 3-gram：容忍拼写错误和词形变化
                for i in range(len(tok) - 2):
                    add("t:" + tok[i:i + 3], 1.0)
            if prev:
                add("p:" + prev + "_" + tok, 0.7)
            prev = tok
        return feats

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for f, w in self.features(text).items():
                h = _h(f)
                out[row, h % self.dim] += (1.0 if (h >> 31) & 1 else -1.0) * (1.0 + math.log(w) if w > 1 else w)
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.maximum(norms, 1e-9)


class RemoteEmbedder:
    """OpenAI 兼容的 /embeddings 接口（混元等）。批量调用、限流/5xx 退避重试、维度校验；错误信息不带响应体。"""

    def __init__(self, base_url: str, key: str, model: str, dim: int | None = None, batch: int = 16,
                 retries: int = 3, timeout: float = 30.0, sleep=time.sleep):
        self.base_url, self.key, self.model, self.batch = base_url.rstrip("/"), key, model, batch
        self.retries, self.timeout, self._sleep = retries, timeout, sleep
        self.name, self.dim = f"remote:{model}", dim or 0

    def _call(self, inputs: list[str]) -> list[list[float]]:
        for attempt in range(self.retries + 1):
            try:
                r = httpx.post(f"{self.base_url}/embeddings", headers={"Authorization": f"Bearer {self.key}"},
                               json={"model": self.model, "input": inputs}, timeout=self.timeout)
                if r.status_code == 429 or r.status_code >= 500:
                    raise httpx.HTTPStatusError("retryable", request=r.request, response=r)
                r.raise_for_status()
                data = sorted(r.json()["data"], key=lambda d: d["index"])
                if len(data) != len(inputs):
                    raise ValueError("count mismatch")
                return [d["embedding"] for d in data]
            except httpx.HTTPStatusError as e:
                if e.response.status_code not in (429,) and e.response.status_code < 500 or attempt == self.retries:
                    raise EmbeddingFailure("向量化服务暂时不可用。") from e
            except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
                if attempt == self.retries:
                    raise EmbeddingFailure("向量化服务暂时不可用。") from e
            self._sleep(min(2 ** attempt, 8))
        raise EmbeddingFailure("向量化服务暂时不可用。")

    def embed(self, texts: list[str]) -> np.ndarray:
        rows: list[list[float]] = []
        for i in range(0, len(texts), self.batch):
            rows += self._call(texts[i:i + self.batch])
        arr = np.asarray(rows, dtype=np.float32)
        if arr.ndim != 2 or (self.dim and arr.shape[1] != self.dim):
            raise EmbeddingFailure("向量维度与配置不一致。")
        self.dim = arr.shape[1]
        return arr / np.maximum(np.linalg.norm(arr, axis=1, keepdims=True), 1e-9)


def to_bytes(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def from_bytes(blob: bytes, dim: int) -> np.ndarray:
    v = np.frombuffer(blob, dtype=np.float32)
    if v.shape[0] != dim:
        raise ValueError("stored vector dimension mismatch")
    return v
