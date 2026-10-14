"""从保存的同步配置构造连接器。地址与分支在这里再校验一次：配置来自数据库，不能当作可信输入。"""
from __future__ import annotations
import os
import re
from pathlib import Path

from ..connectors.gitrepo import GitRepoConnector

NAME = re.compile(r"^[a-z][a-z0-9-]{0,30}$")


def sync_dir() -> Path:
    return Path(os.getenv("BUTLER_SYNC_DIR") or Path(__file__).resolve().parents[4] / ".runtime" / "sync")


def build_connector(cfg: dict):
    if cfg.get("type") != "git" or not NAME.match(cfg.get("name", "")):
        raise ValueError("unsupported connector config")
    return GitRepoConnector(cfg["name"], cfg["location"], cfg.get("branch", "main"), sync_dir() / cfg["name"],
                            cfg.get("rules", []), allow_local=os.getenv("BUTLER_ALLOW_LOCAL_GIT") == "1")
