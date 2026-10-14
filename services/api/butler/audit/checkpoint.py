"""签名检查点：把链头用私钥签名后导出到库外，数据库写权限者无法在不被发现的情况下改写或截断审计链。

签名私钥只应存在于服务端环境（BUTLER_AUDIT_SIGNING_KEY，PEM），公钥可以公开给任何验证方。
"""
from __future__ import annotations
import base64
import hashlib
import json
import time

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.exceptions import InvalidSignature


def generate_keypair() -> tuple[bytes, bytes]:
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return private, public


def key_id(public_pem: bytes) -> str:
    return hashlib.sha256(public_pem).hexdigest()[:16]


def _message(count: int, head: str, ts: float) -> bytes:
    return json.dumps({"count": count, "head": head, "ts": ts}, sort_keys=True, separators=(",", ":")).encode()


def sign_checkpoint(private_pem: bytes, count: int, head: str, ts: float | None = None) -> dict:
    key = serialization.load_pem_private_key(private_pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("audit signing key must be Ed25519")
    ts = time.time() if ts is None else ts
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    return {"count": count, "head": head, "ts": ts, "key_id": key_id(public),
            "signature": base64.b64encode(key.sign(_message(count, head, ts))).decode()}


def verify_checkpoint(public_pem: bytes, checkpoint: dict) -> bool:
    try:
        key = serialization.load_pem_public_key(public_pem)
        if not isinstance(key, Ed25519PublicKey):
            return False
        key.verify(base64.b64decode(checkpoint["signature"]),
                   _message(checkpoint["count"], checkpoint["head"], checkpoint["ts"]))
        return True
    except (InvalidSignature, KeyError, ValueError, TypeError):
        return False
