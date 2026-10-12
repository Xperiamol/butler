"""Git 仓库连接器：一个不需要平台账号、真实可用的数据源（公开手册、内部文档仓库都适用）。

- 内容：分支上的 .md/.txt 文件；变更检测用 git diff（含删除、重命名按删+增）
- 版本：提交序号（git rev-list --count），沿历史严格递增；首次全量使用 head 序号
- 权限：按路径前缀的规则展开成平台主体，最长前缀优先；没有任何规则命中 ⇒ 空集合 ⇒ 无人可读
  例：[{"prefix": "security/", "principals": ["team:security", "role:exec"]}, {"prefix": "", "principals": ["everyone"]}]
- 安全：只用参数列表调用 git（不经 shell），禁用交互提示，设超时；路径只取自 git ls-tree / diff，不接受外部传入的路径片段
"""
from __future__ import annotations
import os
import re
import subprocess
import time
from pathlib import Path

from .sync import Event, ExternalDoc

TEXT_SUFFIXES = (".md", ".txt")
MAX_BYTES = 400_000


class GitError(RuntimeError):
    pass


class GitRepoConnector:
    data_source = "real"

    def __init__(self, name: str, location: str, branch: str, workdir: Path, rules: list[dict],
                 allow_local: bool = False, include: tuple[str, ...] = TEXT_SUFFIXES, timeout: float = 120.0, partial: bool = False):
        if not (location.startswith("https://") or (allow_local and Path(location).exists())):
            raise GitError("仓库地址必须是 https:// 开头（本地路径仅测试允许）。")
        if not re.fullmatch(r"[\w./-]{1,100}", branch) or branch.startswith("-"):
            raise GitError("分支名不合法。")
        self.name, self.location, self.branch, self.workdir = name, location, branch, Path(workdir)
        self.rules = sorted(rules, key=lambda r: -len(r.get("prefix", "")))
        self.include, self.timeout, self.partial = include, timeout, partial
        self._head: str | None = None

    # ---- git ----
    def _git(self, *args: str, cwd: Path | None = None, check: bool = True) -> str:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "true", "LC_ALL": "C"}
        try:
            r = subprocess.run(["git", *args], cwd=cwd or self.workdir, env=env, capture_output=True, timeout=self.timeout)
        except (subprocess.TimeoutExpired, OSError) as error:
            raise GitError("git 调用失败或超时。") from error
        if check and r.returncode != 0:
            raise GitError("git 命令失败。")   # 不回传 stderr：可能带地址、凭据片段
        return r.stdout.decode("utf-8", errors="replace")

    def refresh(self) -> str:
        """拉到分支最新提交并返回 head 哈希。"""
        if not (self.workdir / ".git").exists():
            self.workdir.parent.mkdir(parents=True, exist_ok=True)
            flags = ["--filter=blob:none"] if self.partial else []
            self._git("clone", "--quiet", *flags, "--no-checkout", "--", self.location, str(self.workdir), cwd=self.workdir.parent)
        self._git("fetch", "--quiet", "origin", self.branch)
        self._head = self._git("rev-parse", "FETCH_HEAD").strip()
        return self._head

    def head(self) -> str:
        return self._head or self.refresh()

    def _index_of(self, commit: str) -> float:
        return float(self._git("rev-list", "--count", commit).strip())

    def _wanted(self, path: str) -> bool:
        return path.endswith(self.include) and not path.startswith(".git/") and ".." not in Path(path).parts

    def _commit_time(self, commit: str) -> float:
        return float(self._git("show", "-s", "--format=%ct", commit).strip())

    # ---- SyncConnector ----
    def events(self, cursor: str | None) -> tuple[list[Event], str]:
        head = self.refresh()
        if head == cursor:
            return [], head
        version, observed = self._index_of(head), self._commit_time(head)
        if cursor is None:
            paths = [p for p in self._git("ls-tree", "-r", "--name-only", head).splitlines() if self._wanted(p)]
            return [Event("upsert", p, version, f"{head}:{p}", observed) for p in paths], head
        events = []
        tokens = self._git("diff", "--name-status", "--no-renames", "-z", cursor, head).split("\0")
        for status, path in zip(tokens[0::2], tokens[1::2]):
            if not self._wanted(path):
                continue
            events.append(Event("delete" if status.startswith("D") else "upsert", path, version, f"{head}:{path}", observed))
        return events, head

    def list_ids(self) -> list[tuple[str, float]]:
        head = self.head()
        version = self._index_of(head)
        return [(p, version) for p in self._git("ls-tree", "-r", "--name-only", head).splitlines() if self._wanted(p)]

    def fetch(self, external_id: str) -> ExternalDoc | None:
        if not self._wanted(external_id):
            return None
        head = self.head()
        listed = set(self._git("ls-tree", "-r", "--name-only", head, "--", external_id).splitlines())
        if external_id not in listed:
            return None
        raw = subprocess.run(["git", "show", f"{head}:{external_id}"], cwd=self.workdir, capture_output=True, timeout=self.timeout,
                             env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
        if raw.returncode != 0:
            raise GitError("读取文件失败。")
        text = raw.stdout[:MAX_BYTES].decode("utf-8", errors="replace")
        title = self._title(text, external_id)
        url = f"{self.location.rstrip('/').removesuffix('.git')}/-/blob/{self.branch}/{external_id}" if self.location.startswith("https://") else ""
        return ExternalDoc(external_id, title, text, url)

    @staticmethod
    def _title(text: str, path: str) -> str:
        m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
        if m and (t := re.search(r"^title:\s*[\"']?(.+?)[\"']?\s*$", m.group(1), re.M)):
            return t.group(1)[:200]
        if h := re.search(r"^#\s+(.+)$", text, re.M):
            return h.group(1).strip()[:200]
        return Path(path).stem.replace("-", " ").replace("_", " ").title()

    def fetch_principals(self, external_id: str) -> frozenset[str]:
        for rule in self.rules:
            if external_id.startswith(rule.get("prefix", "")):
                return frozenset(rule.get("principals", []))
        return frozenset()   # 没有规则 ⇒ 无人可读
