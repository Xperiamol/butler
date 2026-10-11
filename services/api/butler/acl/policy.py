from __future__ import annotations
from ..models import Doc, Fact, Identity


def can_read(identity: Identity, obj: Doc | Fact) -> bool:
    """不变量：未知/空 ACL ⇒ 拒绝；身份由服务端绑定，调用方不能自带权限。"""
    if not obj.acl:
        return False
    return bool(identity.groups & obj.acl)
