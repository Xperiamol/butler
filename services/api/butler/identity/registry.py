from ..models import Identity

_IDENTITIES: dict[str, Identity] = {}


def load(items: list[dict]) -> None:
    _IDENTITIES.clear()
    for i in items:
        _IDENTITIES[i["id"]] = Identity(i["id"], i["name"], frozenset(i["groups"]), i["role"])


def get(identity_id: str) -> Identity:
    if identity_id not in _IDENTITIES:
        raise KeyError(identity_id)
    return _IDENTITIES[identity_id]


def all_identities() -> list[Identity]:
    return list(_IDENTITIES.values())
