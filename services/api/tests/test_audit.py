from butler.audit.chain import AuditLog, verify


def make():
    log = AuditLog()
    for i in range(5):
        log.append({"n": i})
    return log


def test_intact():
    log = make()
    assert verify(log.entries, log.checkpoint()) == (True, None)


def test_tamper_detected():
    log = make()
    log.entries[2]["payload"]["n"] = 99
    assert verify(log.entries, log.checkpoint()) == (False, 2)


def test_truncation_detected_by_checkpoint():
    log = make()
    cp = log.checkpoint()
    assert verify(log.entries[:-1], cp)[0] is False
