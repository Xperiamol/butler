"""离线假适配器：仅用于开发/测试。真实适配器与它实现同一接口。"""
import json
from pathlib import Path

from ..models import Doc, Fact

DEFAULT_WORLD = Path(__file__).resolve().parents[4] / "seed" / "tidepool" / "world.json"
DATA_SOURCE = "fake"


def load_world(path: Path = DEFAULT_WORLD):
    w = json.loads(Path(path).read_text(encoding="utf-8"))
    docs = [Doc(d["id"], d["source"], d["title"], d["text"], frozenset(d["acl"])) for d in w["docs"]]
    facts = [Fact(f["id"], f["source_doc"], frozenset(f["acl"]), f["statement"], tuple(f["keywords"])) for f in w["facts"]]
    return w["identities"], docs, facts


def load_inferences(path: Path = DEFAULT_WORLD) -> list[dict]:
    """假生成器用的“拼图规则”，模拟大模型把碎片拼成结论的能力。"""
    return json.loads(Path(path).read_text(encoding="utf-8")).get("simulated_inferences", [])
