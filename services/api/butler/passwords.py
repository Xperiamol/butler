"""Local credentials, stored separately from public member records."""
import hashlib
import os
import re
import secrets
import time
from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError, InvalidHashError

_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1, type=Type.ID)


def auth_mode():
    return os.getenv("BUTLER_AUTH_MODE", "local")


def username(value):
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.@-]{2,79}", value):
        raise ValueError("账号须为 3–80 位字母、数字或 _.@-。")
    return value


def validate(password):
    if not 15 <= len(password) <= 128 or not password.strip():
        raise ValueError("密码须为 15–128 个字符，可使用空格和中文。")


def credential(password):
    validate(password)
    return {"hash": _HASHER.hash(password), "algorithm": "argon2id"}


# Missing accounts do the same expensive work; no credential is created with this value.
_DUMMY_HASH = _HASHER.hash(secrets.token_hex(32))


def matches(password, stored):
    try:
        valid = _HASHER.verify(stored["hash"] if stored else _DUMMY_HASH, password)
        return bool(stored) and valid
    except (VerificationError, InvalidHashError):
        return False


def consume_attempt(tx, key, limit=5, window=900):
    """Persist failures/budgets so restarting the process cannot reset throttling."""
    now = time.time()
    row = tx.get("login_limit", key, {"start": now, "count": 0})
    if now - row["start"] >= window:
        row = {"start": now, "count": 0}
    if row["count"] >= limit:
        return False
    tx.put("login_limit", key, {**row, "count": row["count"] + 1})
    return True


def bootstrap(db):
    if auth_mode() != "local":
        return
    with db.transaction() as tx:
        # Once installed, bootstrap environment can never overwrite or recreate accounts.
        if tx.get("meta", "local_admin_initialized"):
            return
        login, password = os.getenv("BUTLER_ADMIN_USERNAME", ""), os.getenv("BUTLER_ADMIN_PASSWORD", "")
        if not login or not password:
            if os.getenv("BUTLER_MODE") == "enterprise":
                raise RuntimeError("First local deployment requires BUTLER_ADMIN_USERNAME and BUTLER_ADMIN_PASSWORD (15–128 characters)")
            return
        login = username(login)
        stored = credential(password)
        key = "local-" + hashlib.sha256(login.encode()).hexdigest()
        if tx.get("credential", login) or tx.get("member", key):
            raise RuntimeError("Bootstrap account already exists; refusing to overwrite")
        tx.put("credential", login, {**stored, "member": key})
        tx.put("member", key, {"id": key, "name": "管理员", "username": login, "role": "admin", "groups": [], "active": True, "session_version": 1})
        tx.put("meta", "local_admin_initialized", {"value": True})
