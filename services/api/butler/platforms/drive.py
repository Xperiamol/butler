"""Google Drive 模拟器：共享盘成员、文件夹/文件的共享设置（查看/评论/编辑），继承与“受限访问”。

语义：用户能打开文件，当且仅当下面任一成立（文件设为“受限”时只有第 1 条有效）：
  1. 文件上直接给了他（用户 / 所在组 / 全公司 / 任何知道链接的人）
  2. 他是该文件所在共享盘的成员
  3. 祖先文件夹上共享给了他（继承；文件夹同样可以直接给用户 / 组 / 全公司 / 任何人）
"""
from __future__ import annotations
from dataclasses import dataclass, field

from .base import Attachment, ChangeLog, NotFound, Throttle, paginate
from .people import Directory


@dataclass(frozen=True)
class Perm:
    kind: str          # user | group | domain | anyone
    who: str = ""      # user id / group 名 / ""（domain、anyone）
    role: str = "reader"   # reader | commenter | writer


@dataclass
class SharedDrive:
    id: str
    name: str
    members: dict[str, str] = field(default_factory=dict)      # person → organizer | writer | commenter | reader


@dataclass
class Folder:
    id: str
    name: str
    parent: str | None = None
    drive: str | None = None
    owner: str = ""
    perms: list[Perm] = field(default_factory=list)


@dataclass
class DriveFile:
    id: str
    name: str
    mime: str
    folder: str | None
    drive: str | None
    owner: str
    created: float
    modified: float
    text: str = ""                                  # 文档 / 表格 / 幻灯片的文字内容
    perms: list[Perm] = field(default_factory=list)
    limited: bool = False                           # 受限访问：不继承文件夹和共享盘的权限
    attachment: Attachment | None = None            # 多模态文件：图片 / 扫描 PDF / 录音 …
    links: list[str] = field(default_factory=list)
    version: int = 1


class DriveServer:
    name = "drive"

    def __init__(self, directory: Directory, throttle_every: int = 0):
        self.dir, self.groups = directory, directory.groups()
        self.drives: dict[str, SharedDrive] = {}
        self.folders: dict[str, Folder] = {}
        self.files: dict[str, DriveFile] = {}
        self.log = ChangeLog()
        self.throttle = Throttle(throttle_every)

    def add_drive(self, d: SharedDrive) -> None:
        self.drives[d.id] = d

    def add_folder(self, f: Folder) -> None:
        self.folders[f.id] = f

    def add_file(self, f: DriveFile) -> None:
        self.files[f.id] = f
        self.log.bump(f.id, ts=f.modified)

    def get(self, file_id: str) -> DriveFile:
        if file_id not in self.files:
            raise NotFound(file_id)
        return self.files[file_id]

    def list_files(self, page_token: int = 0, page_size: int = 100):
        self.throttle.hit()
        return paginate(sorted(self.files.values(), key=lambda f: f.id), page_token, page_size)

    # ---- 权限：原生语义 ----
    def _ancestors(self, f: DriveFile) -> list[Folder]:
        out, cur, seen = [], self.folders.get(f.folder) if f.folder else None, set()
        while cur is not None and cur.id not in seen:
            seen.add(cur.id)
            out.append(cur)
            cur = self.folders.get(cur.parent) if cur.parent else None
        return out

    def _perm_hits(self, person: str, perm: Perm) -> bool:
        p = self.dir.by_id[person]
        if perm.kind == "user":
            return perm.who == person
        if perm.kind == "group":
            return person in self.groups.get(perm.who, set())
        if perm.kind == "domain":
            return p.kind == "employee"
        return True    # anyone with the link

    def can_access(self, person: str, file_id: str) -> bool:
        f = self.get(file_id)
        if any(self._perm_hits(person, p) for p in f.perms):
            return True
        if f.limited:
            return False
        if f.drive and person in self.drives[f.drive].members:
            return True
        return any(self._perm_hits(person, p) for a in self._ancestors(f) for p in a.perms)

    # ---- 权限：编译成令牌 ----
    @staticmethod
    def _perm_token(p: Perm) -> str:
        return {"user": f"user:{p.who}", "group": f"grp:{p.who}", "domain": "org:all", "anyone": "pub:link"}[p.kind]

    def obj_tokens(self, file_id: str) -> frozenset[str]:
        f = self.get(file_id)
        toks = {self._perm_token(p) for p in f.perms}
        if not f.limited:
            if f.drive:
                toks.add(f"drive:sd:{f.drive}")
            toks |= {self._perm_token(p) for a in self._ancestors(f) for p in a.perms}
        return frozenset(toks)

    def user_tokens(self, person: str) -> set[str]:
        p = self.dir.by_id[person]
        out = {f"user:{person}", "pub:link"}
        if p.kind == "employee":
            out.add("org:all")
        out |= {f"grp:{g}" for g, members in self.groups.items() if person in members}
        out |= {f"drive:sd:{d.id}" for d in self.drives.values() if person in d.members}
        return out

    # ---- 演示用的变更 ----
    def unshare(self, file_id: str, kind: str, who: str, now: float) -> DriveFile:
        f = self.get(file_id)
        f.perms = [p for p in f.perms if not (p.kind == kind and p.who == who)]
        f.modified, f.version = now, f.version + 1
        self.log.bump(file_id, ts=now)
        return f

    def share(self, file_id: str, perm: Perm, now: float) -> DriveFile:
        f = self.get(file_id)
        f.perms = [p for p in f.perms if not (p.kind == perm.kind and p.who == perm.who)] + [perm]
        f.modified, f.version = now, f.version + 1
        self.log.bump(file_id, ts=now)
        return f

    def set_limited(self, file_id: str, limited: bool, now: float) -> DriveFile:
        f = self.get(file_id)
        f.limited, f.modified, f.version = limited, now, f.version + 1
        self.log.bump(file_id, ts=now)
        return f

    def edit(self, file_id: str, text: str, now: float) -> DriveFile:
        f = self.get(file_id)
        f.text, f.modified, f.version = text, now, f.version + 1
        self.log.bump(file_id, ts=now)
        return f
