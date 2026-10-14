import json

from butler.audit.chain import AuditLog
from butler.audit.checkpoint import generate_keypair, sign_checkpoint, verify_checkpoint
from butler.audit.verify_cli import check, main

PRIVATE, PUBLIC = generate_keypair()


def log(n=5):
    a = AuditLog()
    for i in range(n):
        a.append({"i": i, "ts": 1.0})
    return a


def checkpoint(a):
    return sign_checkpoint(PRIVATE, len(a.entries), a.checkpoint(), ts=2.0)


def test_valid_export_passes():
    a = log()
    assert check(a.entries, checkpoint(a), PUBLIC) == []


def test_edited_entry_detected():
    a = log()
    cp = checkpoint(a)
    a.entries[2]["payload"]["i"] = 99
    assert any("断裂" in p for p in check(a.entries, cp, PUBLIC))


def test_truncated_tail_detected_by_signed_count():
    a = log()
    cp = checkpoint(a)
    assert any("条数" in p for p in check(a.entries[:3], cp, PUBLIC))


def test_attacker_cannot_rewrite_chain_and_fake_checkpoint():
    """有数据库写权限的人重算整条链：链自洽，但没有私钥就签不出新检查点。"""
    a = log()
    cp = checkpoint(a)
    forged = AuditLog()
    for e in a.entries[:-1]:
        forged.append(dict(e["payload"]))
    forged.append({"i": 999, "ts": 1.0})
    assert check(forged.entries, {**cp, "head": forged.checkpoint()}, PUBLIC)  # 签名失效
    other_private, _ = generate_keypair()
    fake = sign_checkpoint(other_private, len(forged.entries), forged.checkpoint())
    assert any("签名" in p for p in check(forged.entries, fake, PUBLIC))


def test_history_rewrite_detected_against_previous_checkpoint():
    a = log(3)
    old = checkpoint(a)
    forged = AuditLog()
    for i in range(5):
        forged.append({"i": i + 100, "ts": 1.0})
    new = checkpoint(forged)
    assert any("前缀" in p for p in check(forged.entries, new, PUBLIC, previous=old))


def test_signature_roundtrip_and_tamper():
    cp = sign_checkpoint(PRIVATE, 1, "ab", ts=1.0)
    assert verify_checkpoint(PUBLIC, cp) and not verify_checkpoint(PUBLIC, {**cp, "count": 2})


def test_cli_exit_codes(tmp_path):
    a = log()
    (tmp_path / "e.json").write_text(json.dumps(a.entries))
    (tmp_path / "c.json").write_text(json.dumps(checkpoint(a)))
    (tmp_path / "pub.pem").write_bytes(PUBLIC)
    assert main(["verify", str(tmp_path / "e.json"), str(tmp_path / "c.json"), str(tmp_path / "pub.pem")]) == 0
    a.entries[0]["payload"]["i"] = 7
    (tmp_path / "e.json").write_text(json.dumps(a.entries))
    assert main(["verify", str(tmp_path / "e.json"), str(tmp_path / "c.json"), str(tmp_path / "pub.pem")]) == 1
