"""独立审计验证工具，不连接数据库，只依赖导出文件和公钥：

    python -m butler.audit.verify_cli keygen  私钥.pem 公钥.pem
    python -m butler.audit.verify_cli verify  导出.json 检查点.json 公钥.pem [--previous 旧检查点.json]

退出码 0 = 链完整、签名有效、链头与条数和检查点一致；非 0 = 失败原因打印在标准输出。
给 --previous 时还会确认新链以旧检查点为前缀（链没被整体改写）。
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

from .chain import GENESIS, verify
from .checkpoint import generate_keypair, verify_checkpoint


def check(entries: list[dict], checkpoint: dict, public_pem: bytes, previous: dict | None = None) -> list[str]:
    problems: list[str] = []
    if not verify_checkpoint(public_pem, checkpoint):
        problems.append("检查点签名无效")
    ok, bad = verify(entries)
    if not ok:
        problems.append(f"哈希链在第 {bad} 条处断裂")
    head = entries[-1]["hash"] if entries else GENESIS
    if checkpoint.get("count") != len(entries):
        problems.append(f"条数不一致：检查点 {checkpoint.get('count')}，导出 {len(entries)}（可能被截断或追加）")
    elif checkpoint.get("head") != head:
        problems.append("链头与检查点不一致")
    if previous is not None:
        n = previous["count"]
        if not verify_checkpoint(public_pem, previous):
            problems.append("旧检查点签名无效")
        elif n > len(entries):
            problems.append("新导出比旧检查点更短：链被截断")
        elif (entries[n - 1]["hash"] if n else GENESIS) != previous["head"]:
            problems.append("旧检查点不是新链的前缀：历史被改写")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[0] == "keygen":
        private, public = generate_keypair()
        Path(argv[1]).write_bytes(private)
        Path(argv[2]).write_bytes(public)
        Path(argv[1]).chmod(0o600)
        print("已生成密钥对。私钥只放服务端环境，公钥可以公开。")
        return 0
    if argv and argv[0] == "verify" and len(argv) in (4, 6):
        entries = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        checkpoint = json.loads(Path(argv[2]).read_text(encoding="utf-8"))
        previous = json.loads(Path(argv[5]).read_text(encoding="utf-8")) if len(argv) == 6 and argv[4] == "--previous" else None
        problems = check(entries, checkpoint, Path(argv[3]).read_bytes(), previous)
        print("通过" if not problems else "失败：\n- " + "\n- ".join(problems))
        return 1 if problems else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
